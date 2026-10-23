"""Opt-in full-ZIP ingest + real SQLite schedule acceptance, never production DB."""
from contextlib import closing
from datetime import datetime, time, timedelta
import json
import os
import time as clock

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.gtfs_schedule import GtfsScheduleService, ISTANBUL
from app.storage.db import connect

pytestmark = [pytest.mark.integration, pytest.mark.skipif(
    os.getenv("RUN_LIVE_GTFS_SCHEDULE_TESTS") != "1", reason="requires explicit full GTFS download opt-in",
)]


@pytest.mark.asyncio
async def test_full_zip_schedule_and_nine_published_departure_rows(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "live-schedule.sqlite3", gtfs_schedule_enabled=True)
    service = GtfsScheduleService(settings)
    try:
        started = clock.monotonic()
        snapshot = await service._snapshot()
        cold_seconds = clock.monotonic() - started
        metadata = snapshot.metadata
        assert metadata and metadata["counts"]["stop_times"] > 0
        assert any(r["url"].endswith("/stop_times.zip") for r in metadata["resources"])
        cases = []
        with closing(connect(settings.database_path)) as conn:
            # Independent source-row checks: one published trip from each of
            # three routes, and the first three timed boarding stops per trip.
            trips = conn.execute("""SELECT t.*, c.weekdays, c.start_date, c.end_date
                FROM gtfs_schedule_trips t JOIN gtfs_schedule_calendar c USING(service_id)
                WHERE t.trip_id IN (SELECT MIN(trip_id) FROM gtfs_schedule_trips GROUP BY route_id)
                ORDER BY route_id LIMIT 3""").fetchall()
            assert len(trips) == 3
            for trip in trips:
                start = datetime.strptime(trip["start_date"], "%Y%m%d").date()
                days = [start + timedelta(days=i) for i in range(7)]
                days = [day for day in days if trip["weekdays"][day.weekday()] == "1" and day.strftime("%Y%m%d") <= trip["end_date"]
                        and not conn.execute("SELECT 1 FROM gtfs_schedule_calendar_dates WHERE service_id=? AND date=? AND exception_type=2", (trip["service_id"], day.strftime("%Y%m%d"))).fetchone()]
                assert days
                midnight = datetime.combine(days[0], time(), tzinfo=ISTANBUL)
                line = conn.execute("SELECT line FROM gtfs_schedule_routes WHERE route_id=?", (trip["route_id"],)).fetchone()[0]
                rows = conn.execute("""SELECT stop_id, departure_seconds FROM gtfs_schedule_stop_times
                    WHERE trip_id=? AND departure_seconds IS NOT NULL AND pickup_type!=1
                    ORDER BY stop_sequence LIMIT 3""", (trip["trip_id"],)).fetchall()
                assert len(rows) == 3
                for row in rows:
                    at = (midnight + timedelta(seconds=row["departure_seconds"])).isoformat()
                    cases.append((row["stop_id"], line, at, trip["trip_id"]))
        samples = []
        for stop, line, at, trip_id in cases:
            started = clock.monotonic()
            result = await service.next_departures(stop_id=stop, line=line, at=at, limit=100)
            samples.append(clock.monotonic() - started)
            assert result["ok"], result
            assert any(r["trip_id"] == trip_id and r["scheduled_departure"] == at for r in result["data"]), result
        stop, line, at, _ = cases[0]
        for _ in range(40):
            started = clock.monotonic()
            result = await service.next_departures(stop_id=stop, line=line, at=at, limit=5)
            samples.append(clock.monotonic() - started)
            assert result["ok"], result
        p95 = sorted(samples)[int(.95 * (len(samples) - 1))]
        print(json.dumps({"cold_seconds": round(cold_seconds, 3), "warm_p95_seconds": round(p95, 4),
                          "source_counts": metadata["counts"], "download_bytes": metadata["received_bytes"],
                          "uncompressed_bytes": metadata["uncompressed_bytes"],
                          "database_bytes": settings.database_path.stat().st_size, "published_rows_checked": len(cases)}))
        assert p95 < .3
    finally:
        clear_source_cache()
