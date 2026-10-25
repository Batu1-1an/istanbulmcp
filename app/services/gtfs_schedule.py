"""Next *scheduled* departures. No real-time ETA or routing claims."""
from __future__ import annotations

import asyncio
from datetime import datetime, time, timedelta
from contextlib import closing
import hashlib
import heapq
import logging
import sqlite3
import time as monotonic_time
from zoneinfo import ZoneInfo

from app.connectors.gtfs import GTFS_DATASET_ID
from app.connectors.gtfs_schedule import GtfsScheduleClient, GtfsScheduleError
from app.core.envelope import Freshness, Pagination, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import validation_error_envelope
from app.core.geo import google_maps_url, haversine_m, radius_bbox
from app.core.settings import Settings
from app.core.source_cache import SourceLoadResult, cached_source_data_with_status
from app.core.validation import InputValidationError, resolve_limit, validate_lat_lon, validate_line_code, validate_radius, validate_text
from app.services.stop_search import StopSearchResult, search_stops, validate_stop_query
from app.storage.db import connect
from app.storage.gtfs_schedule import require_snapshot

ISTANBUL = ZoneInfo("Europe/Istanbul")
logger = logging.getLogger("istanbul_mcp.gtfs_schedule")
_warmup_active = False
_warmup_done = asyncio.Event()
_warmup_error: str | None = None


def reset_warmup_state() -> None:
    global _warmup_active, _warmup_done, _warmup_error
    _warmup_active = False
    _warmup_done = asyncio.Event()
    _warmup_error = None


def begin_warmup() -> bool:
    global _warmup_active
    if _warmup_active or _warmup_done.is_set():
        return False
    _warmup_active = True
    return True


async def run_warmup(settings: Settings) -> None:
    global _warmup_active, _warmup_error
    try:
        await GtfsScheduleService(settings)._snapshot()
        logger.info("GTFS timetable warm-up completed")
    except Exception as exc:
        _warmup_error = type(exc).__name__
        logger.warning("GTFS timetable warm-up failed: %s", type(exc).__name__)
    finally:
        _warmup_active = False
        _warmup_done.set()


class ScheduleValidityError(GtfsScheduleError):
    """A request outside the supported calendar must not be a checked empty."""


STATIC_WARNING = "Published GTFS timetable only; not live ETA, delay, cancellation or proof a trip operates today. Verify with IETT before travel."


class GtfsScheduleService:
    def __init__(self, settings: Settings, *, client: GtfsScheduleClient | None = None):
        self.settings = settings
        self.client = client or GtfsScheduleClient(settings)
        profile = (str(settings.database_path.resolve()), getattr(self.client.ckan, "base_url", None),
                   settings.gtfs_schedule_max_bytes, settings.gtfs_schedule_max_uncompressed_bytes,
                   settings.gtfs_schedule_max_rows, settings.gtfs_schedule_load_timeout_seconds,
                   settings.gtfs_schedule_cache_ttl_seconds, settings.gtfs_schedule_stale_if_error_seconds)
        self.profile = hashlib.sha256(repr(profile).encode()).hexdigest()
        self.cache_key = "ckan.gtfs_schedule." + self.profile

    async def next_departures(self, *, stop_id: str | None = None, lat: float | None = None,
                              lon: float | None = None, line: str | None = None, at: str | None = None,
                              radius_m: int = 500, limit: int | None = None, stop_query: str | None = None) -> dict:
        searching = stop_query is not None
        limits = (["mode=stop_search", "stop_name_search_only", "suggested_names_max=5",
                   "search_timeout_seconds=1", "stops_max=100000", "no_district_or_direction_inference"] if searching else
                  ["published_timetable_not_live_eta", "search_window_hours=24", "nearest_stops_max=5",
                   "service_timezone=Europe/Istanbul", "max_gtfs_time=71:59:59",
                   f"gtfs_schedule_max_bytes={self.settings.gtfs_schedule_max_bytes}",
                   f"gtfs_schedule_max_uncompressed_bytes={self.settings.gtfs_schedule_max_uncompressed_bytes}",
                   f"gtfs_schedule_max_rows={self.settings.gtfs_schedule_max_rows}",
                   f"gtfs_schedule_load_timeout_seconds={self.settings.gtfs_schedule_load_timeout_seconds:g}"])
        unavailable = Source(name="IETT GTFS published timetable", dataset_id=GTFS_DATASET_ID,
                             operator="iett", coverage_kind="published_timetable", coverage_status="unavailable",
                             url="https://data.ibb.gov.tr/dataset/iett-gtfs-verisi")
        try:
            safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
            validate_radius(radius_m, self.settings.max_radius_m)
            if searching:
                stop_query = validate_stop_query(stop_query)
                if any(value is not None for value in (stop_id, lat, lon, line, at)) or radius_m != 500:
                    raise InputValidationError(
                        "stop_query searches names only; do not mix with stop_id, coordinates, line, at or radius_m",
                        field="stop_query",
                    )
            elif stop_id is not None:
                stop_id = validate_text(stop_id, field="stop_id", max_length=500)
                if lat is not None or lon is not None:
                    raise InputValidationError("stop_id cannot be mixed with coordinates", field="stop_id")
            elif lat is None or lon is None:
                raise InputValidationError("Provide stop_query for name search, stop_id, or both lat and lon", field="stop_id")
            else:
                validate_lat_lon(lat, lon)
            if line is not None:
                line = validate_line_code(line)
            when = None if searching else self._query_time(at)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[unavailable])
        limits.append(f"limit={safe_limit}")
        if not searching:
            limits.extend([f"radius_m={radius_m}", f"at={when.isoformat()}"])
        if not self.settings.gtfs_schedule_enabled:
            return error_envelope(summary="GTFS timetable lookup is disabled pending live source acceptance.",
                                  warning="GTFS_SCHEDULE_ENABLED=false; no timetable was checked.", sources=[unavailable], limits=limits)
        if _warmup_active:
            return error_envelope(
                summary="GTFS timetable is warming up; no stops were searched." if searching else "GTFS timetable is warming up; no departures were checked.",
                warning="The complete published timetable is loading. Retry in about 60 seconds.",
                sources=[unavailable],
                freshness_status="unknown",
                data=[{"error_code": "warming_up", "retry_after_seconds": 60}],
                limits=limits,
            )
        try:
            cached = await self._snapshot()
            metadata = cached.metadata or {}
            with closing(connect(self.settings.database_path)) as conn:
                # Protect queries against another worker/profile replacing this DB.
                conn.execute("BEGIN")
                require_snapshot(conn, cached.value, self.profile)
                deadline = monotonic_time.monotonic() + 1
                conn.set_progress_handler(lambda: int(monotonic_time.monotonic() > deadline), 1000)
                if searching:
                    found = search_stops(conn, stop_query, safe_limit)
                else:
                    data = self._query(conn, stop_id, lat, lon, radius_m, line, when, safe_limit, metadata["max_departure_seconds"])
            untimed = metadata.get("untimed_total", 0)
            invalid_coords = metadata.get("invalid_coordinate_total", 0)
            sources = [Source(
                name=f"IETT GTFS {resource.get('name') or 'table'}", dataset_id=GTFS_DATASET_ID,
                resource_id=resource["id"], operator="iett", coverage_kind="published_timetable",
                coverage_status="unavailable" if cached.is_stale else "checked",
                scope="published_gtfs_stops" if searching else "complete_published_schedule", url=resource["url"],
                received_total=metadata["counts"].get(resource.get("name"), 0) + metadata.get("skipped", {}).get(resource.get("name"), 0),
                accepted_total=metadata["counts"].get(resource.get("name")),
                skipped_total=metadata.get("skipped", {}).get(resource.get("name"), 0),
                source_updated_at=resource.get("last_modified") or resource.get("metadata_modified"),
                last_successful_refresh_at=cached.refreshed_at_iso,
                last_checked_at=utc_now_iso() if cached.is_stale else cached.refreshed_at_iso,
            ) for resource in metadata["resources"] if not searching or resource.get("name") == "stops"]
            if searching:
                return self._stop_search_envelope(found, cached, sources, limits, safe_limit)
            warnings = [STATIC_WARNING, "Cache freshness records retrieval age, not the age of the published timetable."]
            skipped_routes = metadata.get("skipped", {}).get("routes", 0)
            if skipped_routes:
                warnings.append(f"{skipped_routes} route row(s) without route_id were excluded; no trip referenced them.")
            skipped_stop_times = metadata.get("skipped", {}).get("stop_times", 0)
            if skipped_stop_times:
                warnings.append(f"{skipped_stop_times} identical or fully untimed duplicate (trip_id, stop_sequence) stop-time row(s) were excluded; the first row was kept. Conflicting timed rows reject the snapshot.")
            if untimed:
                warnings.append(f"{untimed} untimed stop-time row(s) have no departure time; no interpolation performed.")
            if invalid_coords:
                warnings.append(f"{invalid_coords} stops have no usable Istanbul coordinates; coordinate search excludes them.")
            if cached.is_stale:
                warnings.append("Source refresh failed; last successful snapshot served within its bounded stale window.")
            return success_envelope(
                summary=f"{len(data)} scheduled departure(s) in the next 24 hours; not live ETA.", data=data,
                sources=sources, limits=limits, warnings=warnings,
                freshness=Freshness(status="stale" if cached.is_stale else "fresh",
                                    retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
                                    source_updated_at=min((s.source_updated_at for s in sources if s.source_updated_at), default=None),
                                    ttl_seconds=self.settings.gtfs_schedule_cache_ttl_seconds),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[unavailable])
        except ScheduleValidityError:
            return error_envelope(summary="Requested time is outside the published GTFS calendar.",
                                  warning="No timetable covers this time. Obtain an updated feed; do not infer no service.",
                                  sources=[unavailable], limits=limits,
                                  data=[{"error_code": "outside_calendar", "field": "at"}])
        except Exception as exc:
            # Never leak source text, local paths, SQL or credentials.
            return error_envelope(summary="GTFS stop search is unavailable; no stops were verified." if searching else "GTFS timetable is unavailable; no departures were verified.",
                                  warning=f"Complete timetable lookup failed ({type(exc).__name__}). {STATIC_WARNING}",
                                  sources=[unavailable], limits=limits)

    def _stop_search_envelope(self, found: StopSearchResult, cached, sources: list[Source],
                              limits: list[str], limit: int) -> dict:
        warnings = [
            "Published GTFS stop names and coordinates only; not live arrivals, address geocoding or proof of service.",
            "Select a stop_id using its name and map before querying departures. Same-name stops remain separate; no stop, direction or district was selected automatically.",
            "Cache freshness records retrieval age, not the age of the published stops.",
        ]
        total = found.matched_total or found.suggested_total
        if found.suggested_total:
            summary = f"No matching stop names; {len(found.rows)} possible spelling suggestion(s). Confirm before selecting a stop_id."
            warnings.append("Suggestions are approximate name similarities, not verified matches to the requested stop.")
        elif not found.matched_total:
            summary = "No matching stop names in the published GTFS snapshot."
            warnings.append("No name match does not mean no transport service. Check spelling or use coordinates.")
        else:
            summary = f"{len(found.rows)} of {found.matched_total} matching GTFS stop candidate(s); select a stop_id for departures."
        if total > len(found.rows):
            warnings.append("Results are truncated by limit; increase limit or use a more specific stop name.")
        if any(row["lat"] is None or row["lon"] is None for row in found.rows):
            warnings.append("Some stop candidates have no usable coordinates; their map links are unavailable. Do not invent a location.")
        if cached.is_stale:
            warnings.append("Source refresh failed; last successful snapshot served within its bounded stale window.")
        for source in sources:
            source.matched_total = found.matched_total
            source.returned_total = len(found.rows)
        return success_envelope(
            summary=summary, data=found.rows, sources=sources,
            limits=[*limits, f"matched_total={found.matched_total}", f"suggested_total={found.suggested_total}"],
            warnings=warnings, pagination=Pagination(limit=limit, total_estimate=total),
            freshness=Freshness(status="stale" if cached.is_stale else "fresh",
                                retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
                                source_updated_at=min((s.source_updated_at for s in sources if s.source_updated_at), default=None),
                                ttl_seconds=self.settings.gtfs_schedule_cache_ttl_seconds),
        )

    async def _snapshot(self):
        async def load():
            metadata = await self.client.load(profile=self.profile)
            return SourceLoadResult(value=metadata["snapshot_id"], metadata=metadata,
                                    max_cache_age_seconds=self.settings.gtfs_schedule_cache_ttl_seconds + self.settings.gtfs_schedule_stale_if_error_seconds)

        return await asyncio.wait_for(cached_source_data_with_status(
            self.cache_key, ttl_seconds=self.settings.gtfs_schedule_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.gtfs_schedule_stale_if_error_seconds, loader=load,
        ), timeout=self.settings.gtfs_schedule_load_timeout_seconds + 1)

    @staticmethod
    def _query_time(at: str | None) -> datetime:
        if at is None:
            return datetime.now(ISTANBUL)
        try:
            text = validate_text(at, field="at", max_length=64)
            value = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if value.tzinfo is None or value.utcoffset() is None or value.year < 2000 or value.year > 2100:
                raise ValueError
            return value.astimezone(ISTANBUL)
        except (ValueError, OverflowError) as exc:
            raise InputValidationError("at must be an ISO datetime with a UTC offset (years 2000–2100)", field="at") from exc

    @staticmethod
    def _query(conn, stop_id, lat, lon, radius_m, line, when, limit, max_seconds):
        if stop_id is not None:
            stops = [dict(row) for row in conn.execute("SELECT * FROM gtfs_schedule_stops WHERE stop_id=?", (stop_id,))]
            if not stops:
                raise InputValidationError("Unknown GTFS stop_id; use stop_query to search published stop names", field="stop_id")
        else:
            min_lon, min_lat, max_lon, max_lat = radius_bbox(lat, lon, radius_m)
            def nearby_stops():
                for row in conn.execute("SELECT * FROM gtfs_schedule_stops WHERE lat BETWEEN ? AND ? AND lon BETWEEN ? AND ?", (min_lat, max_lat, min_lon, max_lon)):
                    distance = haversine_m(lat, lon, row["lat"], row["lon"])
                    if distance <= radius_m:
                        yield {**dict(row), "distance_m": round(distance, 1)}
            stops = heapq.nsmallest(5, nearby_stops(), key=lambda row: (row["distance_m"], row["stop_id"]))
        bounds = conn.execute("""SELECT MIN(first), MAX(last) FROM (
            SELECT MIN(start_date) AS first, MAX(end_date) AS last FROM gtfs_schedule_calendar
            UNION ALL SELECT MIN(date), MAX(date) FROM gtfs_schedule_calendar_dates WHERE exception_type=1
        )""").fetchone()
        if not bounds[0] or max_seconds is None:
            raise GtfsScheduleError("No published GTFS validity")
        first = datetime.combine(datetime.strptime(bounds[0], "%Y%m%d").date(), time(), tzinfo=ISTANBUL)
        last = datetime.combine(datetime.strptime(bounds[1], "%Y%m%d").date(), time(), tzinfo=ISTANBUL)
        if not first <= when < last + timedelta(seconds=max(86400, max_seconds + 1)):
            raise ScheduleValidityError("Query date is outside published GTFS validity")
        stop_map = {row["stop_id"]: row for row in stops}
        data = []
        # A service day can run up to 71:59:59; include two preceding days
        # and tomorrow's service in the fixed 24-hour result window.
        for offset in range(-2, 2):
            date = when.date() + timedelta(days=offset)
            day = date.strftime("%Y%m%d")
            active = {row["service_id"] for row in conn.execute(
                "SELECT * FROM gtfs_schedule_calendar WHERE start_date<=? AND end_date>=?", (day, day),
            ) if row["weekdays"][date.weekday()] == "1"}
            for exception in conn.execute("SELECT * FROM gtfs_schedule_calendar_dates WHERE date=?", (day,)):
                if exception["exception_type"] == 1:
                    active.add(exception["service_id"])
                else:
                    active.discard(exception["service_id"])
            if not stops or not active:
                continue
            midnight = datetime.combine(date, time(), tzinfo=ISTANBUL)
            lower = (when - midnight).total_seconds()
            upper = (when + timedelta(hours=24) - midnight).total_seconds()
            stop_marks = ",".join("?" for _ in stops)
            service_marks = ",".join("?" for _ in active)
            query = f"""SELECT s.*, t.route_id, t.service_id, t.headsign, t.direction_id, r.line, r.route_name
                FROM gtfs_schedule_stop_times s JOIN gtfs_schedule_trips t USING(trip_id)
                JOIN gtfs_schedule_routes r USING(route_id)
                WHERE s.stop_id IN ({stop_marks}) AND t.service_id IN ({service_marks})
                AND s.departure_seconds>=? AND s.departure_seconds<? AND s.pickup_type!=1"""
            args = [*stop_map, *sorted(active), lower, upper]
            if line is not None:
                query += " AND UPPER(r.line)=?"
                args.append(line)
            query += " ORDER BY s.departure_seconds, s.stop_id, s.trip_id, s.stop_sequence LIMIT ?"
            args.append(limit)
            for row in conn.execute(query, args):
                stop = stop_map[row["stop_id"]]
                seconds = row["departure_seconds"]
                data.append({
                    "stop_id": row["stop_id"], "stop_name": stop["stop_name"],
                    "lat": stop["lat"], "lon": stop["lon"], "maps_url": google_maps_url(stop["lat"], stop["lon"]),
                    "distance_m": stop.get("distance_m"), "route_id": row["route_id"], "line": row["line"],
                    "route_name": row["route_name"], "trip_id": row["trip_id"], "service_id": row["service_id"],
                    "trip_headsign": row["headsign"], "direction_id": row["direction_id"],
                    "service_date": date.isoformat(), "scheduled_departure": (midnight + timedelta(seconds=seconds)).isoformat(),
                    "gtfs_departure_time": f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}",
                    "timepoint": row["timepoint"], "pickup_type": row["pickup_type"],
                    "departure_kind": "scheduled_exact" if row["timepoint"] else "scheduled_approximate",
                })
        data.sort(key=lambda row: (row["scheduled_departure"], row["stop_id"], row["trip_id"]))
        return data[:limit]
