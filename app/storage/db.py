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

            CREATE TABLE IF NOT EXISTS datasets (
              id TEXT PRIMARY KEY,
              ckan_id TEXT,
              slug TEXT,
              title TEXT NOT NULL,
              description TEXT,
              organization TEXT,
              groups_json TEXT,
              tags_json TEXT,
              license TEXT,
              source_url TEXT,
              metadata_json TEXT,
              last_modified TEXT,
              retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE TABLE IF NOT EXISTS resources (
              id TEXT PRIMARY KEY,
              dataset_id TEXT NOT NULL,
              ckan_resource_id TEXT,
              name TEXT,
              format TEXT,
              url TEXT,
              datastore_active INTEGER NOT NULL DEFAULT 0,
              schema_json TEXT,
              size_bytes INTEGER,
              hash TEXT,
              retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
              FOREIGN KEY(dataset_id) REFERENCES datasets(id) ON DELETE CASCADE
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS dataset_fts USING fts5(
              dataset_id UNINDEXED,
              title,
              description,
              tags
            );

            CREATE TABLE IF NOT EXISTS geo_features (
              id TEXT PRIMARY KEY,
              source TEXT NOT NULL,
              feature_type TEXT NOT NULL,
              source_id TEXT NOT NULL,
              name TEXT NOT NULL,
              lat REAL NOT NULL,
              lon REAL NOT NULL,
              geometry_json TEXT,
              district TEXT,
              neighborhood TEXT,
              properties_json TEXT,
              valid_at TEXT,
              retrieved_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS geo_features_rtree USING rtree(
              rowid,
              min_lon,
              max_lon,
              min_lat,
              max_lat
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
