"""Atomic, restart-safe daily request quotas stored beside other SQLite tables."""
from __future__ import annotations

from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from math import ceil
import sqlite3


@dataclass(frozen=True)
class QuotaResult:
    allowed: bool
    remaining: int
    reset_at: int
    retry_after: int


class DailyQuota:
    def __init__(self, database_path: Path, limit: int):
        if limit <= 0:
            raise ValueError("MCP_API_KEY_DAILY_QUOTA must be positive")
        self.database_path = database_path
        self.limit = limit
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as conn, conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS api_daily_usage (
                key_hash TEXT NOT NULL, day TEXT NOT NULL, used INTEGER NOT NULL,
                PRIMARY KEY(key_hash, day)
            )""")

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.database_path, timeout=1.0)

    def consume(self, key_hash: str, now: datetime | None = None) -> QuotaResult:
        now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
        day = now.date().isoformat()
        reset = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
        with closing(self._connect()) as conn, conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("DELETE FROM api_daily_usage WHERE day < ?", (day,))
            row = conn.execute(
                "SELECT used FROM api_daily_usage WHERE key_hash=? AND day=?", (key_hash, day)
            ).fetchone()
            used = row[0] if row else 0
            allowed = used < self.limit
            if allowed:
                used += 1
                conn.execute(
                    """INSERT INTO api_daily_usage(key_hash,day,used) VALUES (?,?,?)
                    ON CONFLICT(key_hash,day) DO UPDATE SET used=excluded.used""",
                    (key_hash, day, used),
                )
        return QuotaResult(allowed, max(0, self.limit - used), int(reset.timestamp()),
                           max(1, ceil((reset - now).total_seconds())))
