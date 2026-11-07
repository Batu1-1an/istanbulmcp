"""Transactional per-provider snapshots and stable source identities."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
import json
from pathlib import Path
import threading

from app.core.events import EventObservation, search_text, stable_id
from app.storage.db import connect

_schema_lock = threading.Lock()
_initialized_files: dict[str, int] = {}

SCHEMA = """
CREATE TABLE IF NOT EXISTS event_series (
 id TEXT PRIMARY KEY, source TEXT NOT NULL, source_key TEXT NOT NULL, title TEXT NOT NULL,
 UNIQUE(source, source_key)
);
CREATE TABLE IF NOT EXISTS event_venues (
 id TEXT PRIMARY KEY, name TEXT NOT NULL, district TEXT, lat REAL, lon REAL
);
CREATE TABLE IF NOT EXISTS event_occurrences (
 id TEXT PRIMARY KEY, event_id TEXT NOT NULL REFERENCES event_series(id),
 venue_id TEXT NOT NULL REFERENCES event_venues(id), source TEXT NOT NULL,
 source_id TEXT NOT NULL, start_at TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
 name_norm TEXT NOT NULL, venue_norm TEXT NOT NULL, payload TEXT NOT NULL,
 first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
 UNIQUE(source, source_id)
);
CREATE INDEX IF NOT EXISTS event_occurrences_start ON event_occurrences(active,start_at);
CREATE INDEX IF NOT EXISTS event_occurrences_series ON event_occurrences(event_id,active);
CREATE TABLE IF NOT EXISTS event_offers (
 id TEXT PRIMARY KEY, occurrence_id TEXT NOT NULL REFERENCES event_occurrences(id) ON DELETE CASCADE,
 source TEXT NOT NULL, payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_external_ids (
 source TEXT NOT NULL, source_id TEXT NOT NULL,
 occurrence_id TEXT NOT NULL REFERENCES event_occurrences(id),
 PRIMARY KEY(source,source_id)
);
CREATE TABLE IF NOT EXISTS event_detail_checks (
 event_id TEXT PRIMARY KEY REFERENCES event_series(id) ON DELETE CASCADE,
 attempted_at TEXT NOT NULL, last_successful_at TEXT, error_type TEXT,
 next_check_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS event_source_snapshots (
 source TEXT PRIMARY KEY, refreshed_at TEXT NOT NULL, checked_at TEXT NOT NULL,
 metadata TEXT NOT NULL, last_error TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS event_fts USING fts5(
 name_norm, venue_norm, content='event_occurrences',content_rowid='rowid',
 tokenize='unicode61 remove_diacritics 2',prefix='2 3'
);
CREATE TRIGGER IF NOT EXISTS event_fts_insert AFTER INSERT ON event_occurrences BEGIN
 INSERT INTO event_fts(rowid,name_norm,venue_norm) VALUES(new.rowid,new.name_norm,new.venue_norm);
END;
CREATE TRIGGER IF NOT EXISTS event_fts_delete AFTER DELETE ON event_occurrences BEGIN
 INSERT INTO event_fts(event_fts,rowid,name_norm,venue_norm) VALUES('delete',old.rowid,old.name_norm,old.venue_norm);
END;
CREATE TRIGGER IF NOT EXISTS event_fts_update AFTER UPDATE ON event_occurrences BEGIN
 INSERT INTO event_fts(event_fts,rowid,name_norm,venue_norm) VALUES('delete',old.rowid,old.name_norm,old.venue_norm);
 INSERT INTO event_fts(rowid,name_norm,venue_norm) VALUES(new.rowid,new.name_norm,new.venue_norm);
END;
CREATE VIRTUAL TABLE IF NOT EXISTS event_rtree USING rtree(rowid,min_lon,max_lon,min_lat,max_lat);
"""


class EventRepository:
    def __init__(self, path: Path):
        self.path = path

    def initialize(self):
        key = str(self.path.resolve())
        with _schema_lock:
            if self.path.exists() and _initialized_files.get(key) == self.path.stat().st_ino:
                return
            with connect(self.path) as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.executescript(SCHEMA)
            if len(_initialized_files) >= 64:
                _initialized_files.pop(next(iter(_initialized_files)))
            _initialized_files[key] = self.path.stat().st_ino

    def publish(self, source: str, observations: list[EventObservation], metadata: dict, *, series_key: str | None = None):
        # Validate every row before a transaction can retire any previous records.
        rows = [EventObservation.model_validate(r.model_dump()) for r in observations]
        if any(row.source != source or (series_key is not None and row.series_key != series_key) for row in rows):
            raise ValueError("Source snapshot contains mismatched records")
        if len({row.source_id for row in rows}) != len(rows):
            raise ValueError("Source snapshot contains duplicate identities")
        self.initialize()
        now = datetime.now(timezone.utc).isoformat()
        with connect(self.path) as conn:
            conn.execute("BEGIN IMMEDIATE")
            if series_key is None:
                retained_details = {}
                if source == "biletinial":
                    series_keys = {row.series_key for row in rows if not row.detail_checked}
                    for previous in conn.execute("SELECT payload FROM event_occurrences WHERE source=? AND active=1", (source,)):
                        old = EventObservation.model_validate_json(previous[0])
                        if old.detail_checked and old.series_key in series_keys and old.observed_at >= datetime.now(timezone.utc) - timedelta(days=1):
                            retained_details[old.source_id] = old
                    verified_series = {row.series_key for row in retained_details.values()}
                    rows = [row for row in rows if row.series_key not in verified_series] + list(retained_details.values())
                conn.execute("UPDATE event_occurrences SET active=0 WHERE source=?", (source,))
            else:
                event_id = stable_id("event", source, series_key)
                conn.execute("UPDATE event_occurrences SET active=0 WHERE event_id=?", (event_id,))
            for row in rows:
                # A later catalogue must not overwrite a recent verified detail.
                previous = conn.execute("SELECT payload FROM event_occurrences WHERE id=?", (row.performance_id,)).fetchone()
                if previous and not row.detail_checked:
                    old = EventObservation.model_validate_json(previous[0])
                    if old.detail_checked and old.observed_at >= row.observed_at:
                        row = old
                venue_id = stable_id("venue", row.source, search_text(row.venue.name), row.venue.address or "")
                conn.execute("INSERT INTO event_series VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title",
                             (row.event_id, source, row.series_key, row.title))
                conn.execute("INSERT INTO event_venues VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET district=excluded.district,lat=excluded.lat,lon=excluded.lon",
                             (venue_id, row.venue.name, row.venue.district, row.venue.lat, row.venue.lon))
                conn.execute("""INSERT INTO event_occurrences
                  (id,event_id,venue_id,source,source_id,start_at,active,name_norm,venue_norm,payload,first_seen_at,last_seen_at)
                  VALUES(?,?,?,?,?,?,1,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET
                  venue_id=excluded.venue_id,start_at=excluded.start_at,active=1,name_norm=excluded.name_norm,
                  venue_norm=excluded.venue_norm,payload=excluded.payload,last_seen_at=excluded.last_seen_at""",
                             (row.performance_id, row.event_id, venue_id, source, row.source_id,
                              row.start_at.astimezone(timezone.utc).isoformat(), search_text(row.title),
                              search_text(row.venue.name), row.model_dump_json(), now, now))
                conn.execute("INSERT OR IGNORE INTO event_external_ids VALUES(?,?,?)", (source, row.source_id, row.performance_id))
                rowid = conn.execute("SELECT rowid FROM event_occurrences WHERE id=?", (row.performance_id,)).fetchone()[0]
                conn.execute("DELETE FROM event_rtree WHERE rowid=?", (rowid,))
                if row.venue.lat is not None and row.venue.lon is not None:
                    conn.execute("INSERT INTO event_rtree VALUES(?,?,?,?,?)", (rowid, row.venue.lon, row.venue.lon, row.venue.lat, row.venue.lat))
                conn.execute("DELETE FROM event_offers WHERE occurrence_id=?", (row.performance_id,))
                for index, offer in enumerate(row.offers):
                    conn.execute("INSERT INTO event_offers VALUES(?,?,?,?)", (stable_id("offer", row.performance_id, str(index)), row.performance_id, source, offer.model_dump_json()))
            if series_key is None:
                conn.execute("""INSERT INTO event_source_snapshots VALUES(?,?,?,?,NULL)
                  ON CONFLICT(source) DO UPDATE SET refreshed_at=excluded.refreshed_at,
                  checked_at=excluded.checked_at,metadata=excluded.metadata,last_error=NULL""", (source, now, now, json.dumps(metadata)))
            # Bound retired content retention; identities remain stable by deterministic IDs.
            retired = conn.execute("SELECT rowid FROM event_occurrences WHERE active=0 AND julianday(last_seen_at) < julianday('now','-2 days')").fetchall()
            for retired_row in retired:
                conn.execute("DELETE FROM event_rtree WHERE rowid=?", (retired_row[0],))
            conn.execute("DELETE FROM event_external_ids WHERE occurrence_id IN (SELECT id FROM event_occurrences WHERE active=0 AND julianday(last_seen_at) < julianday('now','-2 days'))")
            conn.execute("DELETE FROM event_occurrences WHERE active=0 AND julianday(last_seen_at) < julianday('now','-2 days')")
            conn.execute("DELETE FROM event_series WHERE id NOT IN (SELECT event_id FROM event_occurrences)")
            conn.execute("DELETE FROM event_venues WHERE id NOT IN (SELECT venue_id FROM event_occurrences)")

    def failure(self, source: str, error: str):
        self.initialize()
        with connect(self.path) as conn:
            conn.execute("UPDATE event_source_snapshots SET checked_at=?,last_error=? WHERE source=?",
                         (datetime.now(timezone.utc).isoformat(), error, source))

    def snapshots(self) -> dict:
        self.initialize()
        with connect(self.path) as conn:
            return {row["source"]: {**dict(row), "metadata": json.loads(row["metadata"])} for row in conn.execute("SELECT * FROM event_source_snapshots")}

    def search(self, start: datetime, end: datetime, *, query: str | None = None, query_scope="title", match_mode="words", bbox=None, max_rows=10000) -> list[EventObservation]:
        self.initialize()
        sql = "SELECT o.payload FROM event_occurrences o"
        params = []
        if query:
            sql += " JOIN event_fts f ON f.rowid=o.rowid"
        if bbox:
            sql += " JOIN event_rtree r ON r.rowid=o.rowid"
        sql += " WHERE o.active=1 AND o.start_at>=? AND o.start_at<?"
        params.extend((start.astimezone(timezone.utc).isoformat(), end.astimezone(timezone.utc).isoformat()))
        if query:
            tokens = search_text(query).split()
            if not tokens:
                return []
            sql += " AND event_fts MATCH ?"
            expression = " AND ".join('"' + token + '"' + ("*" if match_mode == "prefix" else "") for token in tokens)
            params.append("name_norm : (" + expression + ")" if query_scope == "title" else expression)
        if bbox:
            min_lon, min_lat, max_lon, max_lat = bbox
            sql += " AND r.max_lon>=? AND r.min_lon<=? AND r.max_lat>=? AND r.min_lat<=?"
            params.extend((min_lon, max_lon, min_lat, max_lat))
        sql += " ORDER BY o.start_at,o.id LIMIT ?"
        params.append(max_rows + 1)
        with connect(self.path) as conn:
            rows = conn.execute(sql, params).fetchall()
        if len(rows) > max_rows:
            raise ValueError("Indexed query exceeds event row budget")
        return [EventObservation.model_validate_json(row[0]) for row in rows]

    def detail(self, identifier: str) -> list[EventObservation]:
        self.initialize()
        with connect(self.path) as conn:
            identity = conn.execute("SELECT event_id FROM event_occurrences WHERE id=?", (identifier,)).fetchone()
            event_id = identity[0] if identity else identifier
            rows = conn.execute("SELECT payload FROM event_occurrences WHERE event_id=? AND active=1 ORDER BY start_at,id LIMIT 1001", (event_id,)).fetchall()
        if len(rows) > 1000:
            raise ValueError("Event detail exceeds session budget")
        return [EventObservation.model_validate_json(row[0]) for row in rows]

    def observation(self, identifier: str) -> EventObservation | None:
        self.initialize()
        with connect(self.path) as conn:
            row = conn.execute("SELECT payload FROM event_occurrences WHERE id=?", (identifier,)).fetchone()
        return EventObservation.model_validate_json(row[0]) if row else None

    def pending_details(self, *, limit: int, ttl_seconds: int) -> list[str]:
        self.initialize()
        cutoff = (datetime.now(timezone.utc) - timedelta(seconds=ttl_seconds)).isoformat()
        with connect(self.path) as conn:
            rows = conn.execute("""SELECT o.event_id,MIN(json_extract(payload,'$.detail_checked')) AS verified,
              MIN(julianday(json_extract(payload,'$.observed_at'))) AS observed
              FROM event_occurrences o LEFT JOIN event_detail_checks c ON c.event_id=o.event_id
              WHERE active=1 AND source='biletinial'
              AND julianday(start_at)>=julianday('now') AND julianday(start_at)<julianday('now','+31 days')
              AND (c.next_check_at IS NULL OR julianday(c.next_check_at)<=julianday('now'))
              GROUP BY o.event_id HAVING verified=0 OR observed<julianday(?)
              ORDER BY MIN(julianday(start_at)),observed,o.event_id LIMIT ?""", (cutoff, limit)).fetchall()
        return [row["event_id"] for row in rows]

    def detail_checked(self, event_id: str, *, succeeded: bool, retry_seconds: int, error_type=None):
        self.initialize()
        now = datetime.now(timezone.utc)
        with connect(self.path) as conn:
            conn.execute("""INSERT INTO event_detail_checks VALUES(?,?,?,?,?)
              ON CONFLICT(event_id) DO UPDATE SET attempted_at=excluded.attempted_at,
              last_successful_at=COALESCE(excluded.last_successful_at,event_detail_checks.last_successful_at),
              error_type=excluded.error_type,next_check_at=excluded.next_check_at""",
                         (event_id, now.isoformat(), now.isoformat() if succeeded else None, error_type,
                          (now + timedelta(seconds=retry_seconds)).isoformat()))
