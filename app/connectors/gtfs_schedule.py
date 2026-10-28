"""Bounded, disk-backed ingestion of the complete İETT published timetable.

The public stop_times CSV/DataStore is a PREVIEW. Only its full ZIP is used.
Downloads and uncompressed rows have independent, aggregate budgets. No ZIP
member is extracted to a caller/source-controlled path.
"""
from __future__ import annotations

import asyncio
import csv
from datetime import datetime
import io
import math
from pathlib import Path
import re
import sqlite3
import tempfile
from typing import Any, BinaryIO
from urllib.parse import urlsplit
import uuid
import zipfile

import httpx

from app.connectors.ckan import CkanClient
from app.connectors.gtfs import GTFS_DATASET_ID, GTFS_METADATA_MAX_BYTES, parse_gtfs_coordinate
from app.core.settings import Settings
from app.core.source_limits import ckan_rate_limiter
from app.storage.gtfs_schedule import SCHEMA, publish_schedule
from app.connectors.ibb_relay import ibb_http_client

KINDS = ("agency", "calendar", "routes", "stops", "trips", "stop_times")
REQUIRED = {
    "agency": {"agency_timezone"},
    "calendar": {"service_id", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "start_date", "end_date"},
    "calendar_dates": {"service_id", "date", "exception_type"},
    "routes": {"route_id", "route_short_name", "route_long_name"},
    "stops": {"stop_id", "stop_name", "stop_lat", "stop_lon"},
    "trips": {"trip_id", "route_id", "service_id", "trip_headsign"},
    "stop_times": {"trip_id", "stop_id", "stop_sequence", "arrival_time", "departure_time"},
}
WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
MAX_DEPARTURE_SECONDS = 72 * 3600 - 1
TABLE_ROW_CAPS = {"agency": 100, "calendar": 1000, "calendar_dates": 10000,
                  "routes": 20000, "stops": 100000, "trips": 500000, "stop_times": 10000000}

# Arrival times are needed for validation but not for departure queries. Keep
# them only in the disposable staging DB; the published schema stays unchanged.
STAGING_VALIDATION_SCHEMA = """
ALTER TABLE gtfs_schedule_stop_times ADD COLUMN arrival_seconds INTEGER;
ALTER TABLE gtfs_schedule_stops ADD COLUMN source_location_type TEXT;
CREATE TRIGGER reject_conflicting_stop_times BEFORE INSERT ON gtfs_schedule_stop_times
WHEN EXISTS (
 SELECT 1 FROM gtfs_schedule_stop_times s
 WHERE s.trip_id=NEW.trip_id AND s.stop_sequence=NEW.stop_sequence
 AND NOT (
  s.timepoint=NEW.timepoint AND s.pickup_type=NEW.pickup_type AND (
   (s.stop_id=NEW.stop_id AND s.arrival_seconds IS NEW.arrival_seconds
    AND s.departure_seconds IS NEW.departure_seconds)
   OR (s.timepoint=0 AND s.arrival_seconds IS NULL AND s.departure_seconds IS NULL
       AND NEW.arrival_seconds IS NULL AND NEW.departure_seconds IS NULL)
  )
 )
)
BEGIN
 SELECT RAISE(ABORT, 'Conflicting GTFS stop-time key');
END;
"""


class GtfsScheduleError(ValueError):
    """Invalid, incomplete or over-budget timetable; never a checked-empty result."""


def validate_schedule_settings(settings: Settings) -> None:
    for name, cap in (
        ("max_bytes", 128 * 1024 * 1024),
        ("max_uncompressed_bytes", 1024 * 1024 * 1024),
        ("max_rows", 10000000), ("cache_ttl_seconds", 86400),
    ):
        value = getattr(settings, "gtfs_schedule_" + name)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
            raise ValueError(f"GTFS_SCHEDULE_{name.upper()} must be between 1 and {cap}")
    if not math.isfinite(settings.gtfs_schedule_load_timeout_seconds) or not 0 < settings.gtfs_schedule_load_timeout_seconds <= 300:
        raise ValueError("GTFS_SCHEDULE_LOAD_TIMEOUT_SECONDS must be finite and between 0 and 300")
    if not 0 <= settings.gtfs_schedule_stale_if_error_seconds <= 604800:
        raise ValueError("GTFS_SCHEDULE_STALE_IF_ERROR_SECONDS must be between 0 and 604800")


def schedule_url(resource: dict[str, Any], kind: str) -> str:
    url = str(resource.get("url") or "")
    extension = "zip" if kind == "stop_times" else "(?:csv|txt)"
    try:
        parsed = urlsplit(url)
        match = re.fullmatch(rf"/dataset/[A-Za-z0-9-]+/resource/([A-Za-z0-9-]+)/download/{kind}\.{extension}", parsed.path)
        safe = (
            parsed.scheme == "https" and parsed.hostname == "data.ibb.gov.tr"
            and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
            and not parsed.query and not parsed.fragment and match is not None
            and match[1] == resource.get("id")
        )
    except ValueError:
        safe = False
    if not safe:
        raise GtfsScheduleError(f"{kind} requires its canonical HTTPS data.ibb.gov.tr download URL")
    return url


def select_resources(package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    resources = package.get("resources")
    if not isinstance(resources, list):
        raise GtfsScheduleError("GTFS package has no resources list")
    selected = {}
    for kind in (*KINDS, "calendar_dates"):
        candidates = []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            try:
                filename = urlsplit(str(resource.get("url") or "")).path.rsplit("/", 1)[-1]
            except ValueError:
                continue
            extensions = ("zip",) if kind == "stop_times" else ("csv", "txt")
            if filename in {f"{kind}.{extension}" for extension in extensions}:
                candidates.append(resource)
        if kind == "calendar_dates" and not candidates:
            if any(isinstance(r, dict) and str(r.get("name", "")).casefold().split(".")[0] == kind for r in resources):
                raise GtfsScheduleError("Advertised calendar_dates has no canonical download")
            continue
        if len(candidates) != 1:
            raise GtfsScheduleError(f"Expected one complete {kind} resource, found {len(candidates)}; preview CSV is not a timetable")
        resource = dict(candidates[0])
        schedule_url(resource, kind)
        selected[kind] = resource
    # Do not silently ignore future headway-based services this implementation
    # cannot expand. Current İETT metadata publishes no frequencies table.
    for resource in resources:
        if not isinstance(resource, dict):
            continue
        name = str(resource.get("name", "")).casefold().split(".")[0]
        url = str(resource.get("url", "")).casefold().split("?", 1)[0]
        if name == "frequencies" or url.endswith(("/frequencies.txt", "/frequencies.csv")):
            raise GtfsScheduleError("Frequency-based GTFS is not supported")
    return selected


def _text(row: dict[str, str], key: str, *, required: bool = True, cap: int = 500) -> str:
    value = row.get(key, "").strip()
    if (required and not value) or len(value) > cap or "\x00" in value:
        raise GtfsScheduleError(f"Invalid GTFS {key}")
    return value


def _date(value: str) -> str:
    if not re.fullmatch(r"[0-9]{8}", value):
        raise GtfsScheduleError("Invalid GTFS service date")
    try:
        datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise GtfsScheduleError("Invalid GTFS service date") from exc
    return value


def _enum(value: str, allowed: set[str], default: str = "") -> int:
    value = value or default
    if value not in allowed:
        raise GtfsScheduleError("Invalid GTFS enum value")
    return int(value)


def parse_schedule_time(value: str) -> int | None:
    if not value:
        return None  # Never invent/interpolate an untimed intermediate stop.
    if not re.fullmatch(r"[0-9]{1,2}:[0-5][0-9]:[0-5][0-9]", value):
        raise GtfsScheduleError("Invalid GTFS departure time")
    hours, minutes, seconds = map(int, value.split(":"))
    total = hours * 3600 + minutes * 60 + seconds
    if total > MAX_DEPARTURE_SECONDS:
        raise GtfsScheduleError("GTFS time exceeds supported 72-hour service day")
    return total


class GtfsScheduleClient:
    def __init__(self, settings: Settings, *, ckan_client: CkanClient | None = None,
                 http_client: httpx.AsyncClient | None = None, rate_limiter=None):
        validate_schedule_settings(settings)
        self.settings = settings
        self.ckan = ckan_client or CkanClient(timeout=settings.request_timeout_seconds)
        self._client = http_client
        self._rate_limiter = rate_limiter or ckan_rate_limiter()

    async def load(self, *, profile: str) -> dict[str, Any]:
        settings = self.settings
        loop = asyncio.get_running_loop()
        deadline = loop.time() + settings.gtfs_schedule_load_timeout_seconds
        settings.database_path.parent.mkdir(parents=True, exist_ok=True)
        async with asyncio.timeout(settings.gtfs_schedule_load_timeout_seconds):
            package = await self.ckan.package_show_bounded(GTFS_DATASET_ID, max_bytes=GTFS_METADATA_MAX_BYTES)
            resources = select_resources(package)
            # Temporary files live on the configured data volume, not in RAM.
            with tempfile.TemporaryDirectory(prefix=".gtfs-stage-", dir=settings.database_path.parent) as directory:
                stage_path = Path(directory) / "schedule.sqlite3"
                # Validation, aggregation and publish run in worker threads;
                # access stays serialized because each call is awaited.
                conn = sqlite3.connect(stage_path, check_same_thread=False)
                try:
                    conn.executescript(SCHEMA)
                    conn.executescript(STAGING_VALIDATION_SCHEMA)
                    counts, skipped, downloaded, expanded = {}, {}, 0, 0
                    async with ibb_http_client(timeout=settings.request_timeout_seconds) as owned:
                        client = self._client or owned
                        for kind, resource in resources.items():
                            path = Path(directory) / kind
                            size = await self._download(client, resource, kind, path, settings.gtfs_schedule_max_bytes - downloaded)
                            downloaded += size
                            with path.open("rb") as stream:
                                if kind == "stop_times":
                                    with zipfile.ZipFile(stream) as archive:
                                        members = archive.infolist()
                                        if len(members) != 1 or members[0].filename not in {"stop_times.csv", "stop_times.txt"}:
                                            raise GtfsScheduleError("Full stop_times ZIP must contain exactly one canonical table")
                                        member = members[0]
                                        if member.flag_bits & 1 or member.file_size > settings.gtfs_schedule_max_uncompressed_bytes - expanded:
                                            raise GtfsScheduleError("Encrypted/over-budget GTFS ZIP")
                                        expanded += member.file_size
                                        with archive.open(member) as data:
                                            counts[kind], skipped[kind] = await self._ingest(conn, data, kind, settings.gtfs_schedule_max_rows - sum(counts.values()) - sum(skipped.values()), deadline)
                                else:
                                    expanded += size
                                    if expanded > settings.gtfs_schedule_max_uncompressed_bytes:
                                        raise GtfsScheduleError("GTFS uncompressed byte budget exceeded")
                                    counts[kind], skipped[kind] = await self._ingest(conn, stream, kind, settings.gtfs_schedule_max_rows - sum(counts.values()) - sum(skipped.values()), deadline)
                            path.unlink()
                    await asyncio.to_thread(self._validate_relations, conn)
                    max_seconds, untimed, invalid_coords, invalid_location_types, calendar_bounds = (
                        await asyncio.to_thread(self._finalize, conn))
                except (csv.Error, UnicodeError, sqlite3.IntegrityError, zipfile.BadZipFile, NotImplementedError) as exc:
                    raise GtfsScheduleError("Malformed or inconsistent GTFS schedule") from exc
                finally:
                    conn.close()
                await asyncio.sleep(0)  # Observe cancellation before publishing.
                if loop.time() >= deadline:
                    raise TimeoutError("GTFS schedule load deadline exceeded")
                snapshot_id = uuid.uuid4().hex
                await asyncio.to_thread(
                    publish_schedule, settings.database_path, stage_path,
                    snapshot_id=snapshot_id, profile=profile)
                return {"snapshot_id": snapshot_id, "counts": counts, "skipped": skipped, "received_bytes": downloaded,
                        "uncompressed_bytes": expanded, "max_departure_seconds": max_seconds, "untimed_total": untimed,
                        "invalid_coordinate_total": invalid_coords, "resources": list(resources.values()),
                        "invalid_location_type_total": invalid_location_types,
                        "calendar_start": calendar_bounds[0], "calendar_end": calendar_bounds[1]}

    async def _download(self, client, resource, kind, path, remaining):
        url = schedule_url(resource, kind)
        expected = resource.get("size")
        has_size = isinstance(expected, int) and not isinstance(expected, bool) and expected > 0
        if has_size and expected > remaining:
            raise GtfsScheduleError("GTFS aggregate download byte budget exceeded")
        await self._rate_limiter.acquire("ckan")
        async with client.stream("GET", url, follow_redirects=False, timeout=self.settings.request_timeout_seconds,
                                 headers={"Accept-Encoding": "identity"}) as response:
            response.raise_for_status()
            if response.status_code != 200 or response.headers.get("content-encoding", "identity").lower() != "identity":
                raise GtfsScheduleError("Partial/compressed GTFS HTTP response rejected")
            allowed = {"application/zip", "application/octet-stream", "application/x-zip-compressed"} if kind == "stop_times" else {"text/csv", "text/plain", "application/csv", "application/octet-stream"}
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in allowed:
                raise GtfsScheduleError("Unexpected GTFS content type")
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > remaining):
                raise GtfsScheduleError("GTFS download Content-Length exceeds budget")
            received = 0
            with path.open("wb") as target:
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    received += len(chunk)
                    if received > remaining:
                        raise GtfsScheduleError("GTFS aggregate download byte budget exceeded")
                    target.write(chunk)
            if (has_size and received != expected) or (length is not None and received != int(length)):
                raise GtfsScheduleError("GTFS download is incomplete or differs from catalog size")
            return received

    async def _ingest(self, conn: sqlite3.Connection, stream: BinaryIO, kind: str, remaining: int, deadline: float) -> tuple[int, int]:
        # TextIOWrapper streams the CSV and ZIP member. csv.field_size_limit's
        # default also bounds individual fields. No list of source rows is kept.
        text = io.TextIOWrapper(stream, encoding="utf-8-sig", newline="")
        try:
            first = text.readline(8193)
            if len(first) > 8192:
                raise GtfsScheduleError("GTFS header too large")
            delimiter = ";" if ";" in first else ","
            fields = next(csv.reader([first], delimiter=delimiter, strict=True), [])
            fields = [field.strip() for field in fields]
            named = [field for field in fields if field]
            if not REQUIRED[kind] <= set(named) or len(named) != len(set(named)) or any(not f for f in fields[:-1]):
                raise GtfsScheduleError(f"Invalid {kind} schema")
            remaining = min(remaining, TABLE_ROW_CAPS[kind])
            count = 0
            skipped = 0
            scanned = 0
            batch = []
            for values in csv.reader(text, delimiter=delimiter, strict=True):
                if not values:
                    continue
                scanned += 1
                if len(values) != len(fields) or scanned > remaining:
                    raise GtfsScheduleError("GTFS row width or aggregate row budget exceeded")
                row = {field: value for field, value in zip(fields, values) if field}
                if kind == "routes" and not _text(row, "route_id", required=False):
                    # The published feed contains a few unusable route rows with
                    # a blank primary key. No trip references them; keep them out
                    # of the schedule and report the count instead of aborting.
                    skipped += 1
                    continue
                batch.append(self._values(kind, row))
                if len(batch) >= 1000:
                    inserted = self._insert(conn, kind, batch)
                    count += inserted
                    skipped += len(batch) - inserted
                    batch.clear()
                    await asyncio.sleep(0)
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("GTFS parsing exceeded deadline")
            if batch:
                inserted = self._insert(conn, kind, batch)
                count += inserted
                skipped += len(batch) - inserted
            if not count:
                raise GtfsScheduleError(f"Empty {kind} table")
            return count, skipped
        finally:
            text.detach()  # The caller owns the binary stream.

    @staticmethod
    def _insert(conn, kind, batch):
        if not batch:
            return 0
        if kind == "agency":
            return len(batch)
        marks = ",".join("?" for _ in batch[0])
        if kind == "stop_times":
            before = conn.total_changes
            # The staging trigger rejects conflicting values, including across
            # batches. Only identical records and the known untimed source
            # duplicates may reach this targeted primary-key no-op.
            conn.executemany(f"INSERT INTO gtfs_schedule_{kind} VALUES ({marks}) "
                             "ON CONFLICT(trip_id, stop_sequence) DO NOTHING", batch)
            return conn.total_changes - before
        conn.executemany(f"INSERT INTO gtfs_schedule_{kind} VALUES ({marks})", batch)
        return len(batch)

    @staticmethod
    def _values(kind, row):
        get = lambda key, **kw: _text(row, key, **kw)
        if kind == "agency":
            if get("agency_timezone") != "Europe/Istanbul":
                raise GtfsScheduleError("Only Europe/Istanbul timetables are supported")
            return ()
        if kind == "calendar":
            days = "".join(str(_enum(get(day), {"0", "1"})) for day in WEEKDAYS)
            start, end = _date(get("start_date")), _date(get("end_date"))
            if start > end:
                raise GtfsScheduleError("Inverted GTFS service date range")
            return get("service_id"), days, start, end
        if kind == "calendar_dates":
            return get("service_id"), _date(get("date")), _enum(get("exception_type"), {"1", "2"})
        if kind == "routes":
            return get("route_id"), get("route_short_name", required=False), get("route_long_name", required=False)
        if kind == "stops":
            lat = parse_gtfs_coordinate(get("stop_lat", required=False), axis="lat")
            lon = parse_gtfs_coordinate(get("stop_lon", required=False), axis="lon")
            if lat is None or lon is None:
                lat = lon = None
            location_type = get("location_type", required=False)
            return (get("stop_id"), get("stop_name"), lat, lon,
                    get("stop_code", required=False) or None, get("stop_desc", required=False) or None,
                    int(location_type) if location_type in {"0", "1", "2", "3", "4"} else None,
                    location_type or None)
        if kind == "trips":
            return get("trip_id"), get("route_id"), get("service_id"), get("trip_headsign", required=False), get("direction_id", required=False) or None
        arrival = parse_schedule_time(get("arrival_time", required=False))
        departure = parse_schedule_time(get("departure_time", required=False))
        if arrival is not None and departure is not None and arrival > departure:
            raise GtfsScheduleError("GTFS departure precedes arrival")
        sequence = get("stop_sequence")
        if not re.fullmatch(r"[0-9]{1,8}", sequence):
            raise GtfsScheduleError("Invalid GTFS stop_sequence")
        timepoint = _enum(get("timepoint", required=False), {"0", "1"}, "1")
        if timepoint == 1 and (arrival is None or departure is None):
            raise GtfsScheduleError("Exact timepoint is missing arrival or departure time")
        return (get("trip_id"), get("stop_id"), int(sequence), departure, timepoint,
                _enum(get("pickup_type", required=False), {"0", "1", "2", "3"}, "0"), arrival)

    @staticmethod
    def _finalize(conn):
        max_seconds = conn.execute("SELECT MAX(departure_seconds) FROM gtfs_schedule_stop_times").fetchone()[0]
        untimed = conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stop_times WHERE departure_seconds IS NULL").fetchone()[0]
        invalid_coords = conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stops WHERE lat IS NULL OR lon IS NULL").fetchone()[0]
        invalid_location_types = conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stops WHERE source_location_type IS NOT NULL AND location_type IS NULL").fetchone()[0]
        calendar_bounds = conn.execute("""SELECT MIN(first), MAX(last) FROM (
            SELECT MIN(start_date) AS first, MAX(end_date) AS last FROM gtfs_schedule_calendar
            UNION ALL SELECT MIN(date), MAX(date) FROM gtfs_schedule_calendar_dates WHERE exception_type=1
        )""").fetchone()
        conn.commit()
        return max_seconds, untimed, invalid_coords, invalid_location_types, calendar_bounds

    @staticmethod
    def _validate_relations(conn):
        checks = (
            "SELECT 1 FROM gtfs_schedule_trips t LEFT JOIN gtfs_schedule_routes r USING(route_id) WHERE r.route_id IS NULL LIMIT 1",
            "SELECT 1 FROM gtfs_schedule_trips t WHERE service_id NOT IN (SELECT service_id FROM gtfs_schedule_calendar UNION SELECT service_id FROM gtfs_schedule_calendar_dates) LIMIT 1",
            "SELECT 1 FROM gtfs_schedule_stop_times s LEFT JOIN gtfs_schedule_trips t USING(trip_id) LEFT JOIN gtfs_schedule_stops p USING(stop_id) WHERE t.trip_id IS NULL OR p.stop_id IS NULL LIMIT 1",
            # Complete ZIP must cover every published trip; a preview cannot pass.
            "SELECT 1 FROM gtfs_schedule_trips t WHERE NOT EXISTS (SELECT 1 FROM gtfs_schedule_stop_times s WHERE s.trip_id=t.trip_id) LIMIT 1",
        )
        if any(conn.execute(query).fetchone() for query in checks):
            raise GtfsScheduleError("Incomplete GTFS schedule or broken foreign IDs")
        if not conn.execute("SELECT 1 FROM gtfs_schedule_stop_times WHERE departure_seconds IS NOT NULL LIMIT 1").fetchone():
            raise GtfsScheduleError("GTFS has no timed departures")
        # Compare known times in stop_sequence order, not CSV order. Filtering
        # untimed rows before the window preserves the constraint across gaps.
        # Arrival-only rows constrain later stops too; equal times are valid.
        backwards = conn.execute("""SELECT 1 FROM (
            SELECT arrival_seconds, departure_seconds,
                   MAX(COALESCE(departure_seconds, arrival_seconds)) OVER (
                       PARTITION BY trip_id ORDER BY stop_sequence
                       ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING
                   ) AS previous_time
            FROM gtfs_schedule_stop_times
            WHERE arrival_seconds IS NOT NULL OR departure_seconds IS NOT NULL
        ) WHERE COALESCE(arrival_seconds, departure_seconds) < previous_time LIMIT 1""").fetchone()
        if backwards:
            raise GtfsScheduleError("GTFS trip times run backwards in stop_sequence order")
