"""Offline complete-ZIP acceptance and timetable edge cases; no live APIs."""
import asyncio
from dataclasses import replace
import io
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
import zipfile

import httpx
import pytest
from starlette.testclient import TestClient

from app.connectors.gtfs_schedule import GtfsScheduleClient, GtfsScheduleError, KINDS, parse_schedule_time, select_resources, validate_schedule_settings
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache
from app.main import create_app
from app.mcp.registry import create_mcp_server
from app.services.gtfs_schedule import GtfsScheduleService
from app.storage.db import connect

FIXTURES = Path(__file__).parent / "fixtures" / "gtfs_schedule"
AT = "2026-10-16T08:00:00+03:00"


def zipped(body: bytes, name="stop_times.csv") -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(name, body)
    return stream.getvalue()


def feed(tmp_path, *, changes=None, settings=None):
    settings = settings or Settings(database_path=tmp_path / "city.sqlite3", gtfs_schedule_enabled=True)
    bodies = {kind: (FIXTURES / f"{kind}.csv").read_bytes() for kind in (*KINDS, "calendar_dates")}
    bodies.update(changes or {})
    bodies["stop_times"] = zipped(bodies["stop_times"])
    resources = [{"id": "id-" + kind.replace("_", "-"), "name": kind, "size": len(body),
                  "last_modified": "2026-03-17T08:25:48", "format": "ZIP" if kind == "stop_times" else "CSV",
                  "url": f"https://data.ibb.gov.tr/dataset/iett/resource/id-{kind.replace('_', '-')}/download/{kind}.{'zip' if kind == 'stop_times' else 'csv'}"}
                 for kind, body in bodies.items()]
    by_url = {resource["url"]: bodies[resource["name"]] for resource in resources}
    requests = []

    def respond(request):
        requests.append(request)
        return httpx.Response(200, content=by_url[str(request.url)], headers={"content-type": "application/zip" if str(request.url).endswith("zip") else "text/csv"})

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ckan = SimpleNamespace(base_url="https://data.ibb.gov.tr/api/3/action", package_show_bounded=AsyncMock(return_value={"resources": resources}))
    client = GtfsScheduleClient(settings, ckan_client=ckan, http_client=http, rate_limiter=SimpleNamespace(acquire=AsyncMock()))
    service = GtfsScheduleService(settings, client=client)
    return SimpleNamespace(service=service, client=client, resources=resources, bodies=bodies, requests=requests, http=http)


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


@pytest.mark.asyncio
async def test_next_departures_reports_warmup_without_blocking(tmp_path, monkeypatch):
    import app.services.gtfs_schedule as schedule

    monkeypatch.setattr(schedule, "_warmup_active", True)
    f = feed(tmp_path)

    result = await f.service.next_departures(stop_id="S1", at=AT)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "warming_up"
    assert result["data"][0]["retry_after_seconds"] == 60
    assert result["freshness"]["status"] == "unknown"
    assert not f.requests


def test_warmup_can_start_only_once():
    from app.services.gtfs_schedule import begin_warmup, reset_warmup_state

    reset_warmup_state()
    try:
        assert begin_warmup() is True
        assert begin_warmup() is False
    finally:
        reset_warmup_state()


@pytest.mark.asyncio
async def test_duplicate_stop_time_keys_are_ignored_with_warning(tmp_path):
    stop_times = (FIXTURES / "stop_times.csv").read_bytes() + b"W;S3;4;;;0;0\n"
    f = feed(tmp_path, changes={"stop_times": stop_times})
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT, limit=3)

    assert result["ok"], result
    source = next(s for s in result["sources"] if s["resource_id"] == "id-stop-times")
    assert source["received_total"] == 24
    assert source["accepted_total"] == 23
    assert source["skipped_total"] == 1
    assert any("duplicate" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_blank_route_id_rows_are_excluded_without_dropping_referenced_routes(tmp_path):
    routes = (FIXTURES / "routes.csv").read_bytes() + b"\n;KM43_G_D2081;\n"
    f = feed(tmp_path, changes={"routes": routes})
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT, limit=3)

    assert result["ok"], result
    source = next(s for s in result["sources"] if s["resource_id"] == "id-routes")
    assert source["received_total"] == 4
    assert source["accepted_total"] == 3
    assert source["skipped_total"] == 1
    assert any("without route_id" in warning for warning in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("stop,minutes", [("S1", [10, 12, 14]), ("S2", [15, 17, 19]), ("S3", [20, 22, 24])])
async def test_three_stops_and_three_lines_match_published_rows(tmp_path, stop, minutes):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id=stop, at=AT, limit=3)
    assert result["ok"], result
    assert [r["line"] for r in result["data"]] == ["500T", "15B", "30D"]
    assert [r["scheduled_departure"][14:16] for r in result["data"]] == [str(m) for m in minutes]
    assert all(r["service_date"] == "2026-10-16" for r in result["data"])
    assert all(r["maps_url"] for r in result["data"])
    assert all(s["scope"] == "complete_published_schedule" and s["coverage_status"] == "checked" for s in result["sources"])
    assert any("not live ETA" in w for w in result["warnings"])
    assert result["data"][2]["departure_kind"] == "scheduled_approximate"


@pytest.mark.asyncio
@pytest.mark.parametrize("at,trip", [("2026-10-17T08:00:00+03:00", "A"), ("2026-10-18T08:00:00+03:00", "U"), ("2026-10-23T08:00:00+03:00", "X")])
async def test_weekend_and_calendar_exceptions(tmp_path, at, trip):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=at, limit=1)
    assert result["ok"] and result["data"][0]["trip_id"] == trip


@pytest.mark.asyncio
async def test_overnight_service_uses_previous_service_date_and_offset_conversion(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", line="500t", at="2026-10-16T21:55:00Z", limit=1)
    row = result["data"][0]
    assert row["service_date"] == "2026-10-16"
    assert row["gtfs_departure_time"] == "25:10:00"
    assert row["scheduled_departure"] == "2026-10-17T01:10:00+03:00"


@pytest.mark.asyncio
async def test_49_hour_times_include_two_preceding_service_days(tmp_path):
    body = (FIXTURES / "stop_times.csv").read_bytes().replace(b"25:", b"49:")
    f = feed(tmp_path, changes={"stop_times": body})
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", line="500T", at="2026-10-18T01:00:00+03:00", limit=1)
    row = result["data"][0]
    assert row["service_date"] == "2026-10-16" and row["gtfs_departure_time"] == "49:10:00"
    assert row["scheduled_departure"] == "2026-10-18T01:10:00+03:00"


@pytest.mark.asyncio
async def test_calendar_end_allows_real_overnight_tail_but_not_expired_empty_success(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        tail = await f.service.next_departures(stop_id="S1", at="2027-01-01T00:30:00+03:00", limit=1)
        expired = await f.service.next_departures(stop_id="S1", at="2027-01-01T02:30:00+03:00")
    assert tail["ok"] and tail["data"][0]["service_date"] == "2026-12-31"
    assert not expired["ok"] and "outside" in expired["summary"]


@pytest.mark.asyncio
async def test_nearby_sorted_departures_and_untimed_no_pickup_not_returned(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(lat=41.01917, lon=28.684353, at=AT, limit=20)
    assert result["ok"], result
    rows = result["data"]
    assert rows == sorted(rows, key=lambda r: (r["scheduled_departure"], r["stop_id"], r["trip_id"]))
    assert all(r["pickup_type"] != 1 and r["scheduled_departure"] and r["distance_m"] is not None for r in rows)
    assert any("untimed" in w for w in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("args,field", [
    ({"limit": 0, "stop_id": "S1"}, "limit"), ({"limit": -1, "stop_id": "S1"}, "limit"),
    ({}, "stop_id"), ({"lat": 41}, "stop_id"), ({"stop_id": "S1", "lat": 41, "lon": 29}, "stop_id"),
    ({"stop_id": "S1", "at": "2026-10-16T08:00:00"}, "at"),
    ({"lat": float("nan"), "lon": 29}, "lat"), ({"lat": 41, "lon": 29, "radius_m": 5001}, "radius_m"),
    ({"stop_id": "S1", "line": "500T';DROP"}, "line_code"),
])
async def test_invalid_input_rejected_before_source_access(tmp_path, args, field):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(**args)
    assert not result["ok"] and result["data"][0]["field"] == field
    f.client.ckan.package_show_bounded.assert_not_awaited()


@pytest.mark.asyncio
async def test_outside_calendar_is_unavailable_not_no_departures(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at="2027-01-05T08:00:00+03:00")
    assert not result["ok"] and result["freshness"]["status"] == "broken"
    assert result["sources"][0]["coverage_status"] == "unavailable"


def test_resolver_requires_full_zip_and_rejects_preview_csv(tmp_path):
    f = feed(tmp_path)
    resources = [r for r in f.resources if r["name"] != "stop_times"]
    resources.append({"id": "preview", "name": "stop_times", "url": "https://data.ibb.gov.tr/dataset/x/resource/preview/download/stop_times.csv"})
    with pytest.raises(GtfsScheduleError, match="preview CSV"):
        select_resources({"resources": resources})


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [
    {"stop_times": b"trip_id,stop_id,stop_sequence,arrival_time,departure_time\nmissing,S1,1,08:00:00,08:00:00\n"},
    {"trips": b"trip_id,route_id,service_id,trip_headsign\nW,R1,WK,Known\nMISSING,R1,WK,Incomplete\n"},
    {"calendar": b"service_id;monday\nWK;1\n"},
    {"agency": b"agency_timezone\nEurope/London\n"},
])
async def test_invalid_partial_feeds_do_not_publish(tmp_path, change):
    f = feed(tmp_path, changes=change)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"]
    assert not list(tmp_path.glob(".gtfs-stage-*"))
    with connect(f.service.settings.database_path) as conn:
        assert not conn.execute("SELECT name FROM sqlite_master WHERE name='gtfs_schedule_meta'").fetchall()


@pytest.mark.asyncio
@pytest.mark.parametrize("setting,value", [("gtfs_schedule_max_rows", 2), ("gtfs_schedule_max_bytes", 30), ("gtfs_schedule_max_uncompressed_bytes", 100)])
async def test_aggregate_budgets_fail_closed(tmp_path, setting, value):
    settings = replace(Settings(database_path=tmp_path / "budget.sqlite3", gtfs_schedule_enabled=True), **{setting: value})
    f = feed(tmp_path, settings=settings)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"] and not list(tmp_path.glob(".gtfs-stage-*"))


@pytest.mark.asyncio
async def test_fresh_cache_single_flight_and_failed_refresh_preserves_snapshot(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        results = await asyncio.gather(*(f.service.next_departures(stop_id="S1", at=AT, limit=1) for _ in range(5)))
        assert all(r["ok"] for r in results)
        assert len(f.requests) == 7
        entry = source_cache._entries[f.service.cache_key]
        refreshed = entry.refreshed_at_iso
        entry.expires_at_monotonic = 0
        f.client.ckan.package_show_bounded.side_effect = TimeoutError("private debug URL")
        stale = await f.service.next_departures(stop_id="S1", at=AT, limit=1)
        assert stale["ok"] and stale["freshness"]["status"] == "stale"
        assert stale["freshness"]["retrieved_at"] == refreshed
        assert stale["data"] == results[0]["data"]
        assert "private debug URL" not in json.dumps(stale)
        # Stale errors must not move the original expiry/max age.
        entry.max_age_at_monotonic = 0
        failed = await f.service.next_departures(stop_id="S1", at=AT)
        assert not failed["ok"]


@pytest.mark.asyncio
async def test_restart_without_provenance_does_not_trust_persisted_tables(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        clear_source_cache()
        f.client.ckan.package_show_bounded.side_effect = TimeoutError
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"]


@pytest.mark.parametrize("value", ["99:00:00", "24:61:00", "08:10", "-1:00:00"])
def test_bad_gtfs_time_is_not_guessed(value):
    with pytest.raises(GtfsScheduleError):
        parse_schedule_time(value)


@pytest.mark.parametrize("field,value", [("gtfs_schedule_max_bytes", 0), ("gtfs_schedule_max_rows", 10000001), ("gtfs_schedule_load_timeout_seconds", float("nan")), ("gtfs_schedule_stale_if_error_seconds", -1)])
def test_settings_have_hard_bounds(field, value):
    with pytest.raises(ValueError):
        validate_schedule_settings(replace(Settings(), **{field: value}))


@pytest.mark.asyncio
async def test_feature_gate_and_discovery_surface(tmp_path):
    default = create_mcp_server(Settings())
    enabled = create_mcp_server(Settings(gtfs_schedule_enabled=True))
    assert "istanbul_next_departures" not in {t.name for t in await default.list_tools()}
    tools = {t.name: t for t in await enabled.list_tools()}
    assert len(tools) == 17 and tools["istanbul_next_departures"].output_schema
    f = feed(tmp_path, settings=Settings(database_path=tmp_path / "disabled.sqlite3"))
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"]
    f.client.ckan.package_show_bounded.assert_not_awaited()


@pytest.mark.parametrize("modern", [False, True])
def test_real_mcp_call_returns_matching_structured_and_text_envelopes(tmp_path, monkeypatch, modern):
    f = feed(tmp_path)
    monkeypatch.setenv("GTFS_SCHEDULE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_PATH", str(f.service.settings.database_path))
    monkeypatch.setattr("app.mcp.server.GtfsScheduleService", lambda _: f.service)
    monkeypatch.setattr("app.main.begin_warmup", lambda: False)
    params = {"name": "istanbul_next_departures", "arguments": {"stop_id": "S1", "at": AT, "limit": 3}}
    headers = {"accept": "application/json, text/event-stream"}
    if modern:
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        headers.update({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": "istanbul_next_departures"})
    with TestClient(create_app(), base_url="http://localhost") as client:
        r = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert not result.get("isError")
    payload = result["structuredContent"]
    assert payload["ok"] and len(payload["data"]) == 3, payload
    assert payload == json.loads(result["content"][0]["text"])


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "https://example.org/dataset/x/resource/id-stop-times/download/stop_times.zip",
    "http://data.ibb.gov.tr/dataset/x/resource/id-stop-times/download/stop_times.zip",
    "https://user:secret@data.ibb.gov.tr/dataset/x/resource/id-stop-times/download/stop_times.zip",
    "https://data.ibb.gov.tr/dataset/x/resource/id-stop-times/download/stop_times.zip?token=hidden",
])
async def test_untrusted_urls_rejected_before_download(tmp_path, url):
    f = feed(tmp_path)
    next(r for r in f.resources if r["name"] == "stop_times")["url"] = url
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"] and f.requests == []
    assert "secret" not in json.dumps(result) and "token=" not in json.dumps(result)


@pytest.mark.asyncio
@pytest.mark.parametrize("status,headers", [(302, {"location": "https://example.org/"}), (206, {}), (200, {"content-encoding": "gzip"}), (200, {"content-type": "text/html"})])
async def test_download_rejects_redirects_partial_compression_and_html(tmp_path, status, headers):
    f = feed(tmp_path)
    await f.http.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(status, headers=headers, content=b"invalid"))) as http:
        f.client._client = http
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"] and not list(tmp_path.glob(".gtfs-stage-*"))


@pytest.mark.asyncio
@pytest.mark.parametrize("member", ["../stop_times.csv", "nested/stop_times.txt", "stops.csv"])
async def test_zip_member_paths_cannot_escape_or_select_wrong_table(tmp_path, member):
    f = feed(tmp_path)
    body = zipped((FIXTURES / "stop_times.csv").read_bytes(), member)
    resource = next(r for r in f.resources if r["name"] == "stop_times")
    resource["size"] = len(body)
    await f.http.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(200, content=body if str(req.url).endswith("zip") else f.bodies[str(req.url).rsplit("/", 1)[1].removesuffix(".csv")]))) as http:
        f.client._client = http
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"] and not list(tmp_path.glob(".gtfs-stage-*"))


@pytest.mark.asyncio
async def test_short_download_fails_catalog_size_check(tmp_path):
    f = feed(tmp_path)
    f.resources[0]["size"] += 1
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"] and not list(tmp_path.glob(".gtfs-stage-*"))


@pytest.mark.asyncio
async def test_cancel_closes_stream_and_removes_staging_files(tmp_path):
    entered = asyncio.Event()
    closed = asyncio.Event()

    class SlowStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            entered.set()
            await asyncio.Event().wait()
            yield b"unused"

        async def aclose(self):
            closed.set()

    f = feed(tmp_path)
    await f.http.aclose()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=SlowStream()))) as http:
        f.client._client = http
        task = asyncio.create_task(f.service.next_departures(stop_id="S1", at=AT))
        await asyncio.wait_for(entered.wait(), 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert closed.is_set() and not list(tmp_path.glob(".gtfs-stage-*"))


@pytest.mark.asyncio
async def test_sqlite_publish_failure_rolls_back_previous_snapshot(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        with connect(f.service.settings.database_path) as conn:
            original = conn.execute("SELECT snapshot_id FROM gtfs_schedule_meta").fetchone()[0]
            conn.execute("CREATE TRIGGER refuse_schedule BEFORE INSERT ON gtfs_schedule_stops BEGIN SELECT RAISE(ABORT, 'test'); END;")
        source_cache._entries[f.service.cache_key].expires_at_monotonic = 0
        stale = await f.service.next_departures(stop_id="S1", at=AT)
    assert stale["ok"] and stale["freshness"]["status"] == "stale"
    with connect(f.service.settings.database_path) as conn:
        assert conn.execute("SELECT snapshot_id FROM gtfs_schedule_meta").fetchone()[0] == original
        assert conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stops").fetchone()[0] == 3


@pytest.mark.asyncio
async def test_cache_metadata_must_match_the_database_snapshot(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        with connect(f.service.settings.database_path) as conn:
            conn.execute("UPDATE gtfs_schedule_meta SET snapshot_id='another-worker'")
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"]


@pytest.mark.asyncio
async def test_fixture_warm_query_p95_under_300_ms(tmp_path):
    import time
    f = feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        samples = []
        for _ in range(40):
            started = time.monotonic()
            assert (await f.service.next_departures(stop_id="S1", at=AT, limit=3))["ok"]
            samples.append(time.monotonic() - started)
    assert sorted(samples)[37] < .3
    assert len(f.requests) == 7  # This is a fixture check, not a production benchmark.
