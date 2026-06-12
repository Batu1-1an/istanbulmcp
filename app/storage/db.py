from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA_VERSION = 1


def connect(database_path: Path) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(database_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_database(database_path: Path) -> dict[str, str | int]:
    with connect(database_path) as conn:
        journal_mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        conn.execute("PRAGMA foreign_keys=ON")
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
              version INTEGER PRIMARY KEY,
              applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS cache_entries (
              key TEXT PRIMARY KEY,
              source_name TEXT NOT NULL,
              request_hash TEXT,
              response_hash TEXT,
              raw_body_path TEXT,
              retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              ttl_seconds INTEGER,
              status TEXT NOT NULL DEFAULT 'unknown'
            );

            CREATE TABLE IF NOT EXISTS tool_calls (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              tool_name TEXT NOT NULL,
              ok INTEGER NOT NULL,
              created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              duration_ms INTEGER,
              warning TEXT
            );
            """
        )
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (SCHEMA_VERSION,),
        )
        conn.commit()
        return {
            "database_path": str(database_path),
            "journal_mode": str(journal_mode),
            "schema_version": SCHEMA_VERSION,
        }


def readiness(database_path: Path) -> dict[str, str | int | bool]:
    status = init_database(database_path)
    with connect(database_path) as conn:
        conn.execute("SELECT 1").fetchone()
    return {**status, "ready": True}
