"""A schedule snapshot is published atomically, separately from the geo index."""
from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from app.storage.db import connect

# Identifiers below are internal constants, never caller-supplied SQL.
TABLES = ("calendar", "calendar_dates", "routes", "stops", "trips", "stop_times")
SCHEMA = """
CREATE TABLE IF NOT EXISTS gtfs_schedule_calendar (
 service_id TEXT PRIMARY KEY, weekdays TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gtfs_schedule_calendar_dates (
 service_id TEXT NOT NULL, date TEXT NOT NULL, exception_type INTEGER NOT NULL,
 PRIMARY KEY(service_id, date)
);
CREATE TABLE IF NOT EXISTS gtfs_schedule_routes (
 route_id TEXT PRIMARY KEY, line TEXT NOT NULL, route_name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS gtfs_schedule_stops (
 stop_id TEXT PRIMARY KEY, stop_name TEXT NOT NULL, lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS gtfs_schedule_trips (
 trip_id TEXT PRIMARY KEY, route_id TEXT NOT NULL, service_id TEXT NOT NULL,
 headsign TEXT NOT NULL, direction_id TEXT
);
CREATE TABLE IF NOT EXISTS gtfs_schedule_stop_times (
 trip_id TEXT NOT NULL, stop_id TEXT NOT NULL, stop_sequence INTEGER NOT NULL,
 departure_seconds INTEGER, timepoint INTEGER NOT NULL, pickup_type INTEGER NOT NULL,
 PRIMARY KEY(trip_id, stop_sequence)
);
CREATE INDEX IF NOT EXISTS gtfs_schedule_departures
 ON gtfs_schedule_stop_times(stop_id, departure_seconds);
CREATE TABLE IF NOT EXISTS gtfs_schedule_meta (
 id INTEGER PRIMARY KEY CHECK(id=1), snapshot_id TEXT NOT NULL, profile TEXT NOT NULL
);
"""


def publish_schedule(database_path: Path, staged_path: Path, *, snapshot_id: str, profile: str) -> None:
    with closing(connect(database_path)) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(SCHEMA)
        conn.execute("ATTACH DATABASE ? AS staged", (str(staged_path),))
        try:
            conn.execute("BEGIN IMMEDIATE")
            for table in TABLES:
                conn.execute(f"DELETE FROM gtfs_schedule_{table}")
                conn.execute(f"INSERT INTO gtfs_schedule_{table} SELECT * FROM staged.gtfs_schedule_{table}")
            conn.execute("DELETE FROM gtfs_schedule_meta")
            conn.execute("INSERT INTO gtfs_schedule_meta VALUES (1, ?, ?)", (snapshot_id, profile))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.execute("DETACH DATABASE staged")


def require_snapshot(conn: sqlite3.Connection, snapshot_id: str, profile: str) -> None:
    row = conn.execute("SELECT snapshot_id, profile FROM gtfs_schedule_meta WHERE id=1").fetchone()
    if row is None or row["snapshot_id"] != snapshot_id or row["profile"] != profile:
        raise ValueError("GTFS schedule snapshot was replaced; revalidation required")
