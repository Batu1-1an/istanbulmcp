"""Read-only SQLite over one isolated in-memory table, never the application DB."""
from __future__ import annotations

from contextlib import closing
import json
import math
import re
import sqlite3
import time
from typing import Any

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

from app.core.validation import InputValidationError, validate_text

MAX_SQL_CHARS = 4096
MAX_RESULT_BYTES = 256 * 1024
MAX_VM_STEPS = 2_000_000
ALLOWED_FUNCTIONS = frozenset({
    "count", "sum", "avg", "min", "max", "total", "round", "abs",
    "coalesce", "ifnull", "nullif", "lower", "upper", "length",
    "substr", "substring", "trim", "ltrim", "rtrim", "like", "glob",
    "date", "datetime", "strftime", "julianday",
})


class QueryRejected(ValueError):
    pass


class SnapshotRejected(ValueError):
    pass


def validate_sql(sql: str) -> str:
    sql = validate_text(sql, field="sql", max_length=MAX_SQL_CHARS)
    if not re.match(r"(?is)^select\b", sql) or "\x00" in sql:
        raise InputValidationError("Only a single SELECT over records is supported", field="sql")
    try:
        statements = sqlglot.parse(sql, read="sqlite", max_nodes=256)
        if len(statements) != 1 or not isinstance(statements[0], exp.Select):
            raise ValueError("single SELECT required")
        tree = statements[0]
        tables = list(tree.find_all(exp.Table))
        if (len(tables) != 1 or tables[0].name.casefold() != "records"
                or tables[0].db or tables[0].catalog
                or len(list(tree.find_all(exp.Select))) != 1
                or tree.find(exp.Join, exp.Subquery, exp.CTE, exp.Window) is not None):
            raise ValueError("one records table; no joins, subqueries, CTEs or windows")
        # Anonymous functions are checked before any source request. Built-in
        # parser nodes are still checked by SQLite's independent authorizer.
        for function in tree.find_all(exp.Anonymous):
            if function.name.lower() not in ALLOWED_FUNCTIONS:
                raise ValueError("function not allowlisted")
        return tree.sql(dialect="sqlite", comments=False)
    except (SqlglotError, RecursionError, ValueError) as exc:
        raise InputValidationError(
            "SQL requires one bounded SELECT from records; no joins/subqueries/CTEs/windows or arbitrary functions",
            field="sql", code="sql_rejected",
        ) from exc


def validate_fields(fields: Any) -> tuple[tuple[str, str], ...]:
    if not isinstance(fields, list) or not 1 <= len(fields) <= 80:
        raise SnapshotRejected("Snapshot requires 1-80 source columns")
    normalized = []
    for field in fields:
        if not isinstance(field, dict):
            raise SnapshotRejected("Malformed source column")
        name, kind = field.get("id"), field.get("type", "text")
        if not isinstance(name, str) or not name or len(name) > 100 or "\x00" in name:
            raise SnapshotRejected("Malformed source column name")
        if not isinstance(kind, str):
            raise SnapshotRejected("Malformed source column type")
        normalized.append((name, kind))
    if len({name.casefold() for name, _kind in normalized}) != len(normalized):
        raise SnapshotRejected("Source columns collide in SQLite")
    if "_id" not in {name for name, _kind in normalized}:
        raise SnapshotRejected("Stable _id pagination is required")
    return tuple(normalized)


def _quote(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _affinity(kind: str) -> str:
    if kind.lower() in {"int", "int2", "int4", "int8", "integer", "bigint", "smallint", "bool", "boolean"}:
        return "INTEGER"
    if kind.lower() in {"float", "float4", "float8", "real", "double", "numeric", "decimal"}:
        return "REAL"
    return "TEXT"


def _cell(value: Any, kind: str) -> Any:
    affinity = _affinity(kind)
    if value is not None and affinity in {"INTEGER", "REAL"}:
        try:
            if affinity == "INTEGER":
                if isinstance(value, float) and not value.is_integer():
                    raise ValueError("fractional integer")
                value = int(value)
            else:
                value = float(value)
        except (ValueError, TypeError, OverflowError) as exc:
            raise SnapshotRejected("Numeric source value does not match its declared type") from exc
    if isinstance(value, float) and not math.isfinite(value):
        raise SnapshotRejected("Non-finite source values")
    if isinstance(value, int) and not -(2 ** 63) <= value < 2 ** 63:
        raise SnapshotRejected("Source integer exceeds SQLite range")
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, allow_nan=False)
    if isinstance(value, str) and len(value.encode("utf-8")) > 65536:
        raise SnapshotRejected("Source cell exceeds SQLite length budget")
    return value


def execute_snapshot_query(
    fields: tuple[tuple[str, str], ...], records: list[dict], sql: str, *,
    limit: int, timeout_seconds: float,
) -> tuple[list[dict], bool]:
    """Engine authorization is deny-by-default, including functions and metadata."""
    try:
        sql = validate_sql(sql)
    except InputValidationError as exc:
        raise QueryRejected(str(exc)) from exc
    with closing(sqlite3.connect(":memory:")) as conn:
        conn.setlimit(sqlite3.SQLITE_LIMIT_LENGTH, 65536)
        conn.setlimit(sqlite3.SQLITE_LIMIT_SQL_LENGTH, 8192)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COLUMN, 100)
        conn.setlimit(sqlite3.SQLITE_LIMIT_EXPR_DEPTH, 30)
        conn.setlimit(sqlite3.SQLITE_LIMIT_COMPOUND_SELECT, 5)
        conn.setlimit(sqlite3.SQLITE_LIMIT_ATTACHED, 0)
        conn.setlimit(sqlite3.SQLITE_LIMIT_VDBE_OP, 20000)
        conn.execute("PRAGMA trusted_schema=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA max_page_count=32768")
        columns = {name for name, _kind in fields}
        definitions = ", ".join(f"{_quote(name)} {_affinity(kind)}" for name, kind in fields)
        try:
            conn.execute(f"CREATE TABLE records ({definitions})")
            placeholders = ",".join("?" for _ in fields)
            conn.executemany(
                f"INSERT INTO records VALUES ({placeholders})",
                (tuple(_cell(row.get(name), kind) for name, kind in fields) for row in records),
            )
            conn.commit()
        except (sqlite3.Error, OverflowError, TypeError, ValueError) as exc:
            raise SnapshotRejected("Source values exceed the local snapshot format/budget") from exc

        conn.execute("PRAGMA query_only=ON")

        def authorize(action, arg1, arg2, database, _trigger):
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and arg1 == "records":
                if database == "main" and arg2 in columns:
                    return sqlite3.SQLITE_OK
                # COUNT(*) and constant projections report an empty column and
                # may supply no database name in SQLite's authorizer callback.
                if database in {"main", None} and arg2 == "":
                    return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and (arg2 or "").lower() in ALLOWED_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        conn.set_authorizer(authorize)
        deadline = time.monotonic() + timeout_seconds
        steps = 0

        def progress():
            nonlocal steps
            steps += 1000
            return int(steps > MAX_VM_STEPS or time.monotonic() >= deadline)

        conn.set_progress_handler(progress, 1000)
        try:
            # execute(), never executescript(). The user cannot escape this
            # subquery with a second statement; LIMIT is independently enforced.
            cursor = conn.execute(f"SELECT * FROM ({sql}) AS bounded_result LIMIT ?", (limit + 1,))
            names = [column[0] for column in cursor.description or []]
            if len({name.casefold() for name in names}) != len(names):
                raise QueryRejected("Output columns need unique aliases")
            data, size, truncated = [], 0, False
            for row in cursor:
                if len(data) == limit:
                    truncated = True
                    break
                result = dict(zip(names, row))
                encoded = json.dumps(result, ensure_ascii=False, allow_nan=False).encode("utf-8")
                size += len(encoded)
                if size > MAX_RESULT_BYTES:
                    raise QueryRejected("SQL result exceeds 256 KiB; select fewer/smaller fields")
                data.append(result)
            return data, truncated
        except (sqlite3.Error, MemoryError, ValueError, TypeError) as exc:
            if isinstance(exc, QueryRejected):
                raise
            raise QueryRejected("SQL rejected: check columns, allowed functions and execution budget") from exc
