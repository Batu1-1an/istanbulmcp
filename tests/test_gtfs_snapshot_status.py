"""Snapshot diagnostics and source metadata use complete synthetic feeds only."""
from datetime import datetime, timedelta, timezone
import json

import pytest
from starlette.testclient import TestClient

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache
from app.main import create_app
from app.mcp.registry import create_mcp_server
from app.storage.db import connect
from tests.test_gtfs_schedule import AT, FIXTURES, feed

STOPS = """stop_id;stop_name;stop_lat;stop_lon;stop_code;stop_desc;location_type;
S1;Same stop;41.01917;28.68435;001001;direction: AVCILAR;0;
S2;Same stop;41.01920;28.68440;001002;direction: BOĞAZKÖY;1;
S3;Third stop;41.02000;28.68500;;;;
""".encode()


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


@pytest.mark.asyncio
async def test_stop_metadata_survives_ingestion_search_and_departures(tmp_path):
    f = feed(tmp_path, changes={"stops": STOPS})
    async with f.http:
        search = await f.service.next_departures(stop_query="Same stop")
        departures = await f.service.next_departures(stop_id="S1", at=AT, limit=1)
    assert [row["stop_code"] for row in search["data"]] == ["001001", "001002"]
    assert [row["location_type"] for row in search["data"]] == [0, 1]
    assert search["data"][1]["platform_direction_text"] == "direction: BOĞAZKÖY"
    assert search["data"][1]["stop_desc"] == "direction: BOĞAZKÖY"
    row = departures["data"][0]
    assert row["stop_code"] == "001001"
    assert row["platform_direction_text"] == "direction: AVCILAR"
    assert row["realtime"] is False and row["schedule_relationship"] == "STATIC"
    assert row["data_source"] == "gtfs_static"
    assert "district" not in search["data"][0] and "direction_id" not in search["data"][0]


@pytest.mark.asyncio
async def test_absent_optional_metadata_stays_null(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert result["ok"], result
    for key in ("stop_code", "stop_desc", "platform_direction_text", "location_type"):
        assert result["data"][0][key] is None


@pytest.mark.parametrize("location_type", ["-1", "5", "direction: outbound", "2,83E+14", "2,91E+12", "2,91E+14"])
@pytest.mark.asyncio
async def test_invalid_optional_location_type_is_null_and_counted_without_losing_departures(tmp_path, location_type):
    f = feed(tmp_path, changes={"stops": STOPS.replace(b"AVCILAR;0;", f"AVCILAR;{location_type};".encode())})
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
        search = await f.service.next_departures(stop_query="Same stop")
        status = await f.service.snapshot_status()
    assert result["ok"] and search["ok"] and status["ok"]
    assert result["data"][0]["location_type"] is None
    assert search["data"][0]["location_type"] is None
    assert search["data"][1]["location_type"] == 1
    assert status["data"][0]["invalid_location_type_total"] == 1
    assert all(any("invalid optional location_type" in warning for warning in response["warnings"])
               for response in (result, search, status))


@pytest.mark.asyncio
async def test_existing_four_column_stop_table_is_upgraded_atomically(tmp_path):
    f = feed(tmp_path, changes={"stops": STOPS})
    with connect(f.service.settings.database_path) as conn:
        conn.execute("CREATE TABLE gtfs_schedule_stops (stop_id TEXT PRIMARY KEY, stop_name TEXT NOT NULL, lat REAL, lon REAL)")
        conn.execute("INSERT INTO gtfs_schedule_stops VALUES ('old', 'old', 41, 29)")
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert result["ok"], result
    with connect(f.service.settings.database_path) as conn:
        assert conn.execute("SELECT stop_code FROM gtfs_schedule_stops WHERE stop_id='S1'").fetchone()[0] == "001001"
        assert conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stops WHERE stop_id='old'").fetchone()[0] == 0


@pytest.mark.asyncio
async def test_failed_publication_preserves_old_stop_schema_and_rows(tmp_path):
    f = feed(tmp_path, changes={"stops": STOPS})
    with connect(f.service.settings.database_path) as conn:
        conn.execute("CREATE TABLE gtfs_schedule_stops (stop_id TEXT PRIMARY KEY, stop_name TEXT NOT NULL, lat REAL, lon REAL)")
        conn.execute("INSERT INTO gtfs_schedule_stops VALUES ('old', 'old', 41, 29)")
        conn.execute("CREATE TRIGGER reject_publish BEFORE INSERT ON gtfs_schedule_stops BEGIN SELECT RAISE(ABORT, 'test'); END")
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT)
    assert not result["ok"]
    with connect(f.service.settings.database_path) as conn:
        assert len(conn.execute("PRAGMA table_info(gtfs_schedule_stops)").fetchall()) == 4
        assert conn.execute("SELECT stop_id FROM gtfs_schedule_stops").fetchone()[0] == "old"


@pytest.mark.asyncio
async def test_status_never_loads_a_missing_snapshot(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.snapshot_status()
    assert not result["ok"] and result["error"]["code"] == "snapshot_unavailable"
    f.client.ckan.package_show_bounded.assert_not_awaited()
    assert not f.requests


@pytest.mark.asyncio
async def test_status_reports_disabled_and_warming_states_without_source_access(tmp_path, monkeypatch):
    disabled = feed(tmp_path, settings=Settings(database_path=tmp_path / "disabled.db"))
    assert (await disabled.service.snapshot_status())["error"]["code"] == "feature_disabled"
    monkeypatch.setattr("app.services.gtfs_schedule._warmup_active", True)
    f = feed(tmp_path)
    result = await f.service.snapshot_status()
    assert result["error"]["code"] == "warming_up"
    assert result["error"]["retry_after_ms"] == 60000
    assert not f.requests and not disabled.requests


@pytest.mark.asyncio
async def test_status_exposes_counts_calendar_and_age_without_refresh(tmp_path):
    stop_times = (FIXTURES / "stop_times.csv").read_bytes() + b"W;S1;1;08:10:00;08:10:00;1;0\n"
    f = feed(tmp_path, changes={"stop_times": stop_times})
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        entry = source_cache._entries[f.service.cache_key]
        entry.refreshed_at_iso = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        count = len(f.requests)
        status = await f.service.snapshot_status()
    assert status["ok"], status
    assert len(f.requests) == count
    f.client.ckan.package_show_bounded.assert_awaited_once()
    row = status["data"][0]
    assert row["rows"]["stops"] == 3 and row["rows"]["stop_times"] == 23
    assert row["skipped"]["stop_times"] == 1
    assert row["untimed_total"] > 0
    assert 3599 <= row["age_seconds"] <= 3602
    assert row["calendar"]["min_date"] == "2026-01-01"
    assert row["calendar"]["max_date"] == "2026-12-31"
    assert row["realtime_available"] is False
    assert status["sources"][0]["coverage_status"] is None  # Not a live health probe.
    assert row["upstream_health"] == "not_checked"


@pytest.mark.asyncio
async def test_status_stale_expired_and_replaced_snapshots_are_not_hidden(tmp_path):
    f = feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_id="S1", at=AT))["ok"]
        entry = source_cache._entries[f.service.cache_key]
        # Keep within the real bounded stale window without a sleep.
        import time
        entry.expires_at_monotonic = time.monotonic() - 1
        entry.metadata["calendar_end"] = "20200101"
        stale = await f.service.snapshot_status()
        assert stale["ok"] and stale["freshness"]["status"] == "stale"
        assert stale["data"][0]["calendar"]["expired"] is True
        assert any("expired" in warning for warning in stale["warnings"])
        with connect(f.service.settings.database_path) as conn:
            conn.execute("UPDATE gtfs_schedule_meta SET snapshot_id='replaced'")
        replaced = await f.service.snapshot_status()
        assert not replaced["ok"] and replaced["error"]["code"] == "snapshot_unavailable"
        entry.max_age_at_monotonic = 0
        expired = await f.service.snapshot_status()
        assert not expired["ok"] and expired["error"]["code"] == "snapshot_unavailable"
    f.client.ckan.package_show_bounded.assert_awaited_once()


@pytest.mark.parametrize("limit,truncated", [(1, True), (100, False)])
@pytest.mark.asyncio
async def test_departures_detect_truncation_with_bounded_lookahead(tmp_path, limit, truncated):
    f = feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_id="S1", at=AT, limit=limit)
    assert result["ok"]
    assert result["result_info"]["truncated"] is truncated
    assert result["result_info"]["returned"] == len(result["data"])
    assert result["result_info"]["matched"] == (None if truncated else len(result["data"]))
    assert "next_offset" not in result["result_info"]


@pytest.mark.asyncio
async def test_stop_suggestion_count_is_not_a_verified_match_count(tmp_path):
    f = feed(tmp_path, changes={"stops": (FIXTURES / "stops_search.csv").read_bytes()})
    async with f.http:
        result = await f.service.next_departures(stop_query="kadkoy", limit=1)
    assert result["result_info"]["scope"] == "spelling_suggestions"
    assert result["sources"][0]["matched_total"] == 0
    assert result["result_info"]["truncated"] is True


@pytest.mark.asyncio
async def test_snapshot_tool_is_structured_and_hidden_but_callable_when_disabled():
    default = create_mcp_server(Settings())
    assert "istanbul_gtfs_snapshot_status" not in {tool.name for tool in await default.list_tools()}
    assert "istanbul_gtfs_snapshot_status" in default.callable_tool_names()
    tools = {tool.name: tool for tool in await create_mcp_server(Settings(gtfs_schedule_enabled=True)).list_tools()}
    tool = tools["istanbul_gtfs_snapshot_status"]
    assert tool.output_schema and not tool.input_schema.get("required")


@pytest.mark.parametrize("modern", [False, True])
def test_snapshot_status_text_and_structured_output_match_over_mcp(tmp_path, monkeypatch, modern):
    f = feed(tmp_path)
    monkeypatch.setenv("GTFS_SCHEDULE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_PATH", str(f.service.settings.database_path))
    monkeypatch.setattr("app.mcp.server.GtfsScheduleService", lambda _: f.service)
    monkeypatch.setattr("app.main.begin_warmup", lambda: False)
    params = {"name": "istanbul_gtfs_snapshot_status", "arguments": {}}
    headers = {"accept": "application/json, text/event-stream"}
    if modern:
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        headers.update({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": params["name"]})
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    payload = result["structuredContent"]
    assert payload == json.loads(result["content"][0]["text"])
    assert payload["error"]["code"] == "snapshot_unavailable"
    assert not f.requests
