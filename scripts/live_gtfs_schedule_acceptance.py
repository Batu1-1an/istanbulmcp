from __future__ import annotations

import asyncio
import json
import tempfile
import time
from contextlib import closing
from datetime import datetime, time as dt_time, timedelta
from pathlib import Path

from app.core.settings import Settings, get_settings
from app.core.source_cache import clear_source_cache
from app.services.gtfs_schedule import GtfsScheduleService, ISTANBUL
from app.storage.db import connect


async def main() -> None:
    clear_source_cache()
    runtime = get_settings()
    print(json.dumps({
        "relay_configured": bool(runtime.ibb_relay_base_url and runtime.ibb_relay_token),
        "request_timeout_seconds": runtime.request_timeout_seconds,
        "schedule_enabled_in_env": runtime.gtfs_schedule_enabled,
    }), flush=True)
    with tempfile.TemporaryDirectory(prefix="gtfs-live-") as directory:
        database = Path(directory) / "schedule.sqlite3"
        settings = Settings(database_path=database, gtfs_schedule_enabled=True)
        service = GtfsScheduleService(settings)
        started = time.monotonic()
        snapshot = await service._snapshot()
        cold_seconds = time.monotonic() - started
        metadata = snapshot.metadata or {}
        if not metadata or metadata.get("counts", {}).get("stop_times", 0) <= 0:
            raise SystemExit("no stop_times ingested")
        if not any(str(resource.get("url", "")).endswith("/stop_times.zip") for resource in metadata.get("resources", [])):
            raise SystemExit("full stop_times.zip was not used")
        print(json.dumps({
            "cold_seconds": round(cold_seconds, 3),
            "source_counts": metadata.get("counts"),
            "source_skipped": metadata.get("skipped"),
            "download_bytes": metadata.get("received_bytes"),
            "uncompressed_bytes": metadata.get("uncompressed_bytes"),
            "database_bytes": database.stat().st_size,
        }, ensure_ascii=False), flush=True)

        cases = []
        with closing(connect(database)) as conn:
            trips = conn.execute(
                """SELECT t.*, c.weekdays, c.start_date, c.end_date,
                          (SELECT COUNT(*) FROM gtfs_schedule_stop_times s
                           WHERE s.trip_id=t.trip_id AND s.departure_seconds IS NOT NULL
                           AND s.pickup_type!=1) AS timed_count
                   FROM gtfs_schedule_trips t JOIN gtfs_schedule_calendar c USING(service_id)
                   WHERE t.trip_id IN (SELECT MIN(trip_id) FROM gtfs_schedule_trips GROUP BY route_id)
                   ORDER BY t.route_id LIMIT 20"""
            ).fetchall()
            selected = [trip for trip in trips if trip["timed_count"] > 0][:3]
            if len(selected) < 3:
                raise SystemExit("fewer than three routes with timed stops")
            for trip in selected:
                start = datetime.strptime(trip["start_date"], "%Y%m%d").date()
                days = [
                    start + timedelta(days=i)
                    for i in range(14)
                    if trip["weekdays"][(start + timedelta(days=i)).weekday()] == "1"
                    and (start + timedelta(days=i)).strftime("%Y%m%d") <= trip["end_date"]
                    and not conn.execute(
                        "SELECT 1 FROM gtfs_schedule_calendar_dates WHERE service_id=? AND date=? AND exception_type=2",
                        (trip["service_id"], (start + timedelta(days=i)).strftime("%Y%m%d")),
                    ).fetchone()
                ]
                if not days:
                    raise SystemExit("no active service day")
                midnight = datetime.combine(days[0], dt_time(), tzinfo=ISTANBUL)
                line = conn.execute("SELECT line FROM gtfs_schedule_routes WHERE route_id=?", (trip["route_id"],)).fetchone()[0]
                rows = conn.execute(
                    """SELECT stop_id, departure_seconds FROM gtfs_schedule_stop_times
                       WHERE trip_id=? AND departure_seconds IS NOT NULL AND pickup_type!=1
                       ORDER BY stop_sequence LIMIT 3""",
                    (trip["trip_id"],),
                ).fetchall()
                if not rows:
                    raise SystemExit("no timed stops")
                for row in rows:
                    at = (midnight + timedelta(seconds=row["departure_seconds"])).isoformat()
                    cases.append((row["stop_id"], line, at, trip["trip_id"]))

        samples = []
        for stop, line, at, trip_id in cases:
            started = time.monotonic()
            result = await service.next_departures(stop_id=stop, line=line, at=at, limit=100)
            samples.append(time.monotonic() - started)
            if not result.get("ok"):
                raise SystemExit(f"departure query failed: {result.get('summary')}")
            if not any(row["trip_id"] == trip_id and row["scheduled_departure"] == at for row in result["data"]):
                raise SystemExit("published departure row not found")
        stop, line, at, _ = cases[0]
        for _ in range(40):
            started = time.monotonic()
            result = await service.next_departures(stop_id=stop, line=line, at=at, limit=5)
            samples.append(time.monotonic() - started)
            if not result.get("ok"):
                raise SystemExit("warm query failed")
        p95 = sorted(samples)[int(0.95 * (len(samples) - 1))]
        print(json.dumps({
            "cold_seconds": round(cold_seconds, 3),
            "warm_p95_seconds": round(p95, 4),
            "source_counts": metadata.get("counts"),
            "download_bytes": metadata.get("received_bytes"),
            "uncompressed_bytes": metadata.get("uncompressed_bytes"),
            "database_bytes": database.stat().st_size,
            "published_rows_checked": len(cases),
        }, ensure_ascii=False), flush=True)
        if p95 >= 0.3:
            raise SystemExit(f"warm p95 {p95:.4f}s exceeds 0.3s")
    clear_source_cache()


asyncio.run(main())
