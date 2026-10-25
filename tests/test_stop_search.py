"""Stop discovery uses synthetic published GTFS fixtures, never live endpoints."""
import json
from types import SimpleNamespace

import pytest
from starlette.testclient import TestClient

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache
from app.main import create_app
from app.mcp.registry import create_mcp_server
from app.storage.db import connect
from tests.test_gtfs_schedule import AT, FIXTURES, feed


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def search_feed(tmp_path):
    return feed(tmp_path, changes={"stops": (FIXTURES / "stops_search.csv").read_bytes()})


@pytest.mark.parametrize("query", ["Kadıköy", "kadikoy", "KADIKÖY", "  kadıköy  ", "KADI\u0307KO\u0308Y"])
@pytest.mark.asyncio
async def test_turkish_ascii_and_unicode_names_return_separate_ranked_candidates(tmp_path, query):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query=query)
    assert result["ok"], result
    assert [row["stop_id"] for row in result["data"]] == ["S1", "S2", "S3", "S4"]
    assert [row["match_kind"] for row in result["data"]] == ["exact", "exact", "prefix", "contains"]
    assert all(row["result_kind"] == "stop_candidate" and row["maps_url"] for row in result["data"])
    assert all("scheduled_departure" not in row and "direction_id" not in row and "district" not in row for row in result["data"])
    assert result["sources"][0]["matched_total"] == 4
    assert result["sources"][0]["returned_total"] == 4
    assert result["sources"][0]["resource_id"] == "id-stops"
    assert result["sources"][0]["accepted_total"] == 10
    assert len(result["sources"]) == 1
    assert result["freshness"]["source_updated_at"] == "2026-03-17T08:25:48"
    assert "mode=stop_search" in result["limits"]
    assert any("automatically" in warning for warning in result["warnings"])


@pytest.mark.parametrize("query,stop", [("uskudar", "S5"), ("SISLI", "S6"), ("isik universitesi", "S7"),
                                        ("cengelkoy", "S8"), ("100 YIL MERKEZ", "S10"),
                                        ("rıhtım kadıköy", "S3"), ("kadik", "S1")])
@pytest.mark.asyncio
async def test_diacritics_punctuation_partial_and_reordered_tokens(tmp_path, query, stop):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query=query)
    assert result["ok"] and result["data"][0]["stop_id"] == stop, result


@pytest.mark.asyncio
async def test_limit_truncation_keeps_total_and_explicit_warning(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query="kadikoy", limit=1)
    assert len(result["data"]) == 1
    assert result["pagination"] == {"limit": 1, "offset": 0, "total_estimate": 4}
    assert result["sources"][0]["matched_total"] == 4
    assert any("truncated" in warning for warning in result["warnings"])
    assert any("select" in warning.lower() for warning in result["warnings"])


@pytest.mark.asyncio
async def test_typo_suggestions_are_not_claimed_as_matches_or_departures(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query="kadkoy")
    assert result["ok"] and result["data"], result
    assert all(row["match_kind"] == "suggestion" for row in result["data"])
    assert result["sources"][0]["matched_total"] == 0
    assert "No matching" in result["summary"]
    assert any("not verified matches" in warning for warning in result["warnings"])


@pytest.mark.parametrize("query", ["zz", "zzzzzzzzzzzzzzzzzz", "%_", "'; DROP TABLE gtfs_schedule_stops; --"])
@pytest.mark.asyncio
async def test_unmatched_literal_queries_do_not_become_wildcards_or_sql(tmp_path, query):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query=query)
    if query == "%_":
        assert not result["ok"] and not f.requests
        return
    assert result["ok"] and result["data"] == [], result
    assert "No matching" in result["summary"]
    assert result["sources"][0]["coverage_status"] == "checked"
    with connect(f.service.settings.database_path) as conn:
        assert conn.execute("SELECT COUNT(*) FROM gtfs_schedule_stops").fetchone()[0] == 10


@pytest.mark.parametrize("args,field", [
    ({"stop_query": ""}, "stop_query"), ({"stop_query": "x"}, "stop_query"),
    ({"stop_query": "  "}, "stop_query"), ({"stop_query": "a" * 201}, "stop_query"),
    ({"stop_query": "kadikoy", "stop_id": "S1"}, "stop_query"),
    ({"stop_query": "kadikoy", "lat": 41}, "stop_query"),
    ({"stop_query": "kadikoy", "lon": 29}, "stop_query"),
    ({"stop_query": "kadikoy", "line": "500T"}, "stop_query"),
    ({"stop_query": "kadikoy", "at": AT}, "stop_query"),
    ({"stop_query": "kadikoy", "radius_m": 1000}, "stop_query"),
    ({"stop_query": "kadikoy", "limit": 0}, "limit"),
    ({"stop_query": "kadikoy", "limit": 101}, "limit"),
])
@pytest.mark.asyncio
async def test_invalid_or_mixed_name_search_is_rejected_before_loading(tmp_path, args, field):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(**args)
    assert not result["ok"] and result["data"][0]["field"] == field
    f.client.ckan.package_show_bounded.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_does_not_require_valid_calendar_and_selected_id_is_usable(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query="kadikoy")
        chosen_id = result["data"][1]["stop_id"]
        selected = await f.service.next_departures(stop_id=chosen_id, at=AT, limit=1)
        expired = await f.service.next_departures(stop_id=chosen_id, at="2029-01-01T00:00:00+03:00")
        still_searchable = await f.service.next_departures(stop_query="kadikoy")
    assert selected["ok"] and selected["data"][0]["stop_id"] == chosen_id
    assert not expired["ok"] and expired["data"][0]["error_code"] == "outside_calendar"
    assert still_searchable["ok"] and still_searchable["data"] == result["data"]
    assert len(f.requests) == 7  # Reuses the complete schedule; no new geocoder/feed.


@pytest.mark.asyncio
async def test_missing_coordinates_stay_null_without_a_fabricated_map(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        result = await f.service.next_departures(stop_query="konumsuz")
    assert result["ok"] and len(result["data"]) == 1
    assert result["data"][0]["lat"] is None and result["data"][0]["lon"] is None
    assert result["data"][0]["maps_url"] is None
    assert any("no usable coordinates" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_failed_refresh_preserves_stale_search_and_expiry(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        original = await f.service.next_departures(stop_query="kadikoy")
        entry = source_cache._entries[f.service.cache_key]
        entry.expires_at_monotonic = 0
        f.client.ckan.package_show_bounded.side_effect = TimeoutError("private URL secret")
        stale = await f.service.next_departures(stop_query="kadikoy")
        entry.max_age_at_monotonic = 0
        unavailable = await f.service.next_departures(stop_query="kadikoy")
    assert stale["ok"] and stale["freshness"]["status"] == "stale"
    assert stale["data"] == original["data"]
    assert stale["freshness"]["retrieved_at"] == original["freshness"]["retrieved_at"]
    assert stale["sources"][0]["coverage_status"] == "unavailable"
    assert not unavailable["ok"] and "unavailable" in unavailable["summary"]
    assert "private URL secret" not in json.dumps([stale, unavailable])


@pytest.mark.asyncio
async def test_search_fails_closed_if_snapshot_is_replaced(tmp_path):
    f = search_feed(tmp_path)
    async with f.http:
        assert (await f.service.next_departures(stop_query="kadikoy"))["ok"]
        with connect(f.service.settings.database_path) as conn:
            conn.execute("UPDATE gtfs_schedule_meta SET snapshot_id='replaced'")
        result = await f.service.next_departures(stop_query="kadikoy")
    assert not result["ok"] and result["data"] == []


@pytest.mark.asyncio
async def test_search_honors_feature_gate_and_nonblocking_warmup(tmp_path, monkeypatch):
    f = feed(tmp_path, settings=Settings(database_path=tmp_path / "disabled.sqlite3"))
    async with f.http:
        result = await f.service.next_departures(stop_query="kadikoy")
    assert not result["ok"] and not f.requests
    f = search_feed(tmp_path)
    monkeypatch.setattr("app.services.gtfs_schedule._warmup_active", True)
    async with f.http:
        result = await f.service.next_departures(stop_query="kadikoy")
    assert not result["ok"] and result["data"][0]["error_code"] == "warming_up"
    assert not f.requests


@pytest.mark.asyncio
async def test_search_timeout_is_unavailable_not_a_partial_or_empty_success(tmp_path, monkeypatch):
    f = search_feed(tmp_path)
    async with f.http:
        await f.service.next_departures(stop_query="kadikoy")
        # Model budget expiry during the row scan, without a slow/flaky sleep.
        with monkeypatch.context() as patch:
            clock = iter([0, 2])
            patch.setattr("app.services.stop_search.time", SimpleNamespace(monotonic=lambda: next(clock)))
            result = await f.service.next_departures(stop_query="kadikoy")
    assert not result["ok"] and result["data"] == []
    assert any("TimeoutError" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_stop_query_is_optional_and_discoverable_without_a_new_tool():
    server = create_mcp_server(Settings(gtfs_schedule_enabled=True))
    tools = {tool.name: tool for tool in await server.list_tools()}
    tool = tools["istanbul_next_departures"]
    assert len(tools) == 18
    assert "stop_query" in tool.input_schema["properties"]
    assert "stop_query" not in tool.input_schema.get("required", [])
    assert "NOT departures" in tool.description


@pytest.mark.parametrize("modern", [False, True])
def test_real_mcp_name_search_returns_matching_structured_and_text(tmp_path, monkeypatch, modern):
    f = search_feed(tmp_path)
    monkeypatch.setenv("GTFS_SCHEDULE_ENABLED", "true")
    monkeypatch.setenv("DATABASE_PATH", str(f.service.settings.database_path))
    monkeypatch.setattr("app.mcp.server.GtfsScheduleService", lambda _: f.service)
    monkeypatch.setattr("app.main.begin_warmup", lambda: False)
    params = {"name": "istanbul_next_departures", "arguments": {"stop_query": "kadikoy", "limit": 2}}
    headers = {"accept": "application/json, text/event-stream"}
    if modern:
        params["_meta"] = {"io.modelcontextprotocol/protocolVersion": "2026-07-28", "io.modelcontextprotocol/clientCapabilities": {}}
        headers.update({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call", "mcp-name": "istanbul_next_departures"})
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post("/mcp/", headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert not result.get("isError")
    payload = result["structuredContent"]
    assert payload["ok"] and [row["stop_id"] for row in payload["data"]] == ["S1", "S2"], payload
    assert payload == json.loads(result["content"][0]["text"])
