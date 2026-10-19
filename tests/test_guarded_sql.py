import pytest

from app.core.validation import InputValidationError
from app.storage.guarded_sql import QueryRejected, SnapshotRejected, execute_snapshot_query, validate_fields, validate_sql
import app.storage.guarded_sql as engine

FIELDS = (("_id", "int"), ("district", "text"))
ROWS = [{"_id": 1, "district": "Kadıköy"}, {"_id": 2, "district": "Beşiktaş"}]


def run(sql, **kwargs):
    return execute_snapshot_query(FIELDS, ROWS, sql, limit=10, timeout_seconds=0.5, **kwargs)


@pytest.mark.parametrize("sql", [
    "DELETE FROM records", "DROP TABLE records", "PRAGMA table_info(records)",
    "ATTACH DATABASE 'anything' AS external", "SELECT * FROM records; DELETE FROM records",
    "SELECT * FROM records UNION SELECT * FROM records",
    "SELECT * FROM records a CROSS JOIN records b",
    "SELECT * FROM records a, records b",
    "SELECT * FROM (SELECT * FROM records)",
    "WITH RECURSIVE x AS (SELECT 1) SELECT * FROM records",
    "SELECT ROW_NUMBER() OVER () FROM records",
    "SELECT * FROM main.records", "SELECT * FROM sqlite_master",
    "SELECT * FROM pragma_table_info('records')",
    "SELECT readfile('/etc/passwd') FROM records",
    "SELECT load_extension('fixture') FROM records",
    "SELECT randomblob(999999999) FROM records",
    "SELECT printf('%999999999s', 'x') FROM records",
    "SELECT * FROM records\x00",
])
def test_sql_parser_rejects_writes_metadata_and_unbounded_shapes(sql):
    with pytest.raises((InputValidationError, QueryRejected)):
        validate_sql(sql)


@pytest.mark.parametrize("sql", [
    "SELECT load_extension('fixture') FROM records",
    "SELECT randomblob(999999999) FROM records",
    "SELECT * FROM sqlite_master",
    "SELECT * FROM pragma_table_info('records')",
])
def test_sqlite_authorizer_independently_rejects_unsafe_operations(monkeypatch, sql):
    # A parser regression must not turn into filesystem/extension/schema access.
    monkeypatch.setattr(engine, "validate_sql", lambda value: value)
    with pytest.raises(QueryRejected):
        run(sql)


def test_sqlite_quoting_keeps_source_column_names_as_data():
    fields = (("_id", "int"), ('name"; DROP TABLE records; --', "text"))
    result, _ = execute_snapshot_query(fields, [{"_id": 1, fields[1][0]: "safe"}],
                                      "SELECT * FROM records", limit=10, timeout_seconds=0.5)
    assert result == [{"_id": 1, fields[1][0]: "safe"}]


def test_parser_preserves_quoted_literals_semicolons_and_comments():
    rows, _ = run("SELECT '; DROP TABLE records' AS note FROM records;")
    assert rows[0]["note"] == "; DROP TABLE records"
    assert run("SELECT _id FROM records -- comment")[0] == [{"_id": 1}, {"_id": 2}]


def test_sqlite_vm_budget_interrupts_costly_queries(monkeypatch):
    monkeypatch.setattr(engine, "MAX_VM_STEPS", 1000)
    rows = [{"_id": i, "district": str(i)} for i in range(1000)]
    with pytest.raises(QueryRejected, match="execution budget"):
        execute_snapshot_query(FIELDS, rows, "SELECT district, COUNT(*) FROM records GROUP BY district",
                               limit=10, timeout_seconds=0.5)


def test_results_have_unique_names_and_bounded_bytes():
    # SQLite rewrites duplicate projection labels to unique suffixes. Explicitly
    # test output rather than assuming the original alias spelling survives.
    rows, _ = run("SELECT district AS label, district AS label FROM records")
    assert len(rows[0]) == 2
    long_rows = [{"_id": i, "district": "x" * 30000} for i in range(20)]
    with pytest.raises(QueryRejected, match="256 KiB"):
        execute_snapshot_query(FIELDS, long_rows, "SELECT * FROM records",
                               limit=20, timeout_seconds=0.5)


@pytest.mark.parametrize("fields", [
    [], [{"id": "x", "type": "text"}],
    [{"id": "_id"}, {"id": "name"}, {"id": "NAME"}],
    [{"id": "_id"}, {"id": "x\x00"}],
])
def test_snapshot_schema_is_bounded_and_case_safe(fields):
    with pytest.raises(SnapshotRejected):
        validate_fields(fields)


def test_numeric_source_fields_are_not_silently_summed_as_zero():
    with pytest.raises(SnapshotRejected):
        execute_snapshot_query((("_id", "int"), ("value", "numeric")),
                               [{"_id": 1, "value": "not-a-number"}],
                               "SELECT SUM(value) FROM records", limit=10, timeout_seconds=0.5)


def test_query_has_no_application_database_connection(tmp_path):
    import sqlite3
    database = tmp_path / "application.sqlite3"
    with sqlite3.connect(database) as conn:
        conn.execute("CREATE TABLE private (token TEXT)")
        conn.execute("INSERT INTO private VALUES ('fixture-not-accessible')")
    with pytest.raises(QueryRejected):
        run("SELECT * FROM private")
    assert run("SELECT COUNT(*) AS n FROM records")[0] == [{"n": 2}]
