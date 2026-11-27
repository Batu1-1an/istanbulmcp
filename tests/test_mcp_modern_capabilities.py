"""Tests for 2026-era MCP capabilities, pooled HTTP transport, UI apps, and observability."""
from __future__ import annotations

import json
import struct

import httpx
from mcp import Client
from mcp.types import PromptReference, ResourceTemplateReference
import pytest
from starlette.testclient import TestClient

from app.connectors.ibb_relay import _BorrowedAsyncClient, ibb_http_client, shared_http_pool
from app.core.envelope import ResponseEnvelope
from app.core.otel import current_trace_fields, inject_trace_headers
from app.core.settings import Settings
from app.main import create_app
from app.mcp.apps import EVENTS_PLAN_URI, NEARBY_MAP_URI, WATER_DASHBOARD_URI
from app.mcp.registry import create_mcp_server


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "modern.sqlite3"))


def _modern(client: TestClient, method: str, params: dict | None = None):
    payload_params = dict(params or {})
    payload_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {"extensions": {"io.modelcontextprotocol/ui": {}}},
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2026-07-28",
        "mcp-method": method,
    }
    if "name" in payload_params or "uri" in payload_params:
        headers["mcp-name"] = payload_params.get("name", payload_params.get("uri"))
    return client.post(
        "/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": payload_params},
    )


def test_brand_icons_and_server_card_endpoints_are_served():
    with TestClient(create_app(), base_url="http://localhost") as client:
        icon = client.get("/icon.png")
        assert icon.status_code == 200
        assert icon.headers["content-type"] == "image/png"
        assert icon.content[:8] == b"\x89PNG\r\n\x1a\n"
        width, height = struct.unpack(">II", icon.content[16:24])
        assert (width, height) == (512, 512)
        assert len(icon.content) < 10_240
        assert "max-age=" in icon.headers["cache-control"]

        favicon = client.get("/favicon.ico")
        assert favicon.status_code == 200
        assert favicon.headers["content-type"] == "image/x-icon"
        assert len(favicon.content) > 22

        catalog = client.get("/.well-known/ai-catalog.json")
        assert catalog.status_code == 200
        assert catalog.headers["content-type"].startswith("application/ai-catalog+json")
        assert catalog.headers["access-control-allow-origin"] == "*"
        entries = catalog.json()["entries"]
        assert len(entries) == 1
        assert entries[0]["type"] == "application/mcp-server-card+json"
        assert entries[0]["url"].endswith("/mcp/server-card")

        for path in ("/mcp/server-card", "/server-card", "/.well-known/mcp/server-card.json"):
            card = client.get(path)
            assert card.status_code == 200
            assert card.headers["content-type"].startswith("application/mcp-server-card+json")
            assert card.headers["access-control-allow-origin"] == "*"
            preflight = client.options(path)
            assert preflight.status_code == 204
            assert preflight.headers["access-control-allow-origin"] == "*"
            body = card.json()
            assert body["name"] == "io.github.Batu1-1an/istanbul-mcp"
            assert "2026-07-28" in body["protocolVersions"]
            assert body["authentication"]["required"] is False
            assert body["icons"][0]["src"].endswith("/icon.png")
            assert "io.modelcontextprotocol/ui" in body["capabilities"]["extensions"]


def test_server_card_reflects_auth_mode_without_leaking_keys(monkeypatch):
    secret = "fixture-key-that-must-never-leak-1234567890"
    monkeypatch.setenv("MCP_API_KEYS", secret)
    with TestClient(create_app(), base_url="http://localhost") as client:
        for path in ("/mcp/server-card", "/.well-known/mcp/server-card.json"):
            response = client.get(path)
            assert response.status_code == 200
            assert secret not in response.text
            assert response.json()["authentication"] == {"required": True, "schemes": ["bearer"]}


def test_modern_protocol_exposes_cache_hints_honest_capabilities_and_apps_extension():
    with TestClient(create_app(), base_url="http://localhost") as client:
        discovered = _modern(client, "server/discover").json()["result"]
        assert discovered["ttlMs"] == 300_000
        assert discovered["cacheScope"] == "public"
        caps = discovered["capabilities"]
        assert caps["tools"]["listChanged"] is False
        assert caps["resources"]["listChanged"] is False
        assert caps["resources"]["subscribe"] is False
        assert caps["prompts"]["listChanged"] is False
        assert "completions" in caps
        assert "io.modelcontextprotocol/ui" in caps["extensions"]

        for method in ("tools/list", "resources/list", "resources/templates/list", "prompts/list"):
            res = _modern(client, method).json()["result"]
            assert res["ttlMs"] == 300_000
            assert res["cacheScope"] == "public"

        read_res = _modern(client, "resources/read", {"uri": "istanbul://coverage"}).json()["result"]
        assert read_res["ttlMs"] == 60_000
        assert read_res["cacheScope"] == "public"


def test_keyed_mode_marks_cache_hints_private(monkeypatch):
    key = "fixture-private-cache-scope-key-1234567890"
    monkeypatch.setenv("MCP_API_KEYS", key)
    with TestClient(create_app(), base_url="http://localhost") as client:
        client.headers["authorization"] = f"Bearer {key}"
        discovered = _modern(client, "server/discover").json()["result"]
        assert discovered["cacheScope"] == "private"
        listed = _modern(client, "tools/list").json()["result"]
        assert listed["cacheScope"] == "private"


@pytest.mark.asyncio
async def test_all_published_tools_have_parameter_descriptions_and_compact_output_schema():
    server = create_mcp_server(Settings(events_enabled=True, gtfs_schedule_enabled=True))
    tools = await server.list_tools()
    assert len(tools) == 21
    envelope_schema = ResponseEnvelope.model_json_schema()
    assert len(json.dumps(envelope_schema, separators=(",", ":")).encode()) < 4000
    for tool in tools:
        assert tool.output_schema == envelope_schema
        for param_name, prop in tool.input_schema.get("properties", {}).items():
            assert prop.get("description"), f"{tool.name}.{param_name} missing description"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_mcp_apps_resources_and_tool_bindings(mode):
    server = create_mcp_server(Settings(events_enabled=True))
    async with Client(server, mode=mode) as client:
        listed = await client.list_tools()
        by_name = {tool.name: tool for tool in listed.tools}
        assert by_name["istanbul_nearby"].meta["ui"]["resourceUri"] == NEARBY_MAP_URI
        assert by_name["istanbul_water_status"].meta["ui"]["resourceUri"] == WATER_DASHBOARD_URI
        assert by_name["istanbul_events_plan"].meta["ui"]["resourceUri"] == EVENTS_PLAN_URI

        for uri in (NEARBY_MAP_URI, WATER_DASHBOARD_URI, EVENTS_PLAN_URI):
            result = await client.read_resource(uri)
            content = result.contents[0]
            assert content.mime_type == "text/html;profile=mcp-app"
            assert "<!doctype html>" in content.text.lower()
            for token in (
                "ui/initialize",
                "ui/notifications/initialized",
                "ui/notifications/tool-result",
                "ui/notifications/size-changed",
                "ui/notifications/host-context-changed",
                "ui/open-link",
                "ui/resource-teardown",
            ):
                assert token in content.text
        plan_ui = (await client.read_resource(EVENTS_PLAN_URI)).contents[0].text
        assert "opt.performances" in plan_ui
        water_ui = (await client.read_resource(WATER_DASHBOARD_URI)).contents[0].text
        assert "occupancy_rate" in water_ui and "display_name" in water_ui
        nearby_ui = (await client.read_resource(NEARBY_MAP_URI)).contents[0].text
        assert "r.latitude" in nearby_ui and "r.longitude" in nearby_ui


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_resource_templates_and_completions_are_local_and_turkish_aware(mode):
    server = create_mcp_server(Settings(events_enabled=True))
    async with Client(server, mode=mode) as client:
        templates = await client.list_resource_templates()
        uris = {tpl.uri_template for tpl in templates.resource_templates}
        assert {"istanbul://guides/{topic}", "istanbul://districts/{district}"} <= uris

        guide_res = await client.read_resource("istanbul://guides/events")
        guide_payload = json.loads(guide_res.contents[0].text)
        assert guide_payload["ok"] is True
        assert guide_payload["data"][0]["topic"] == "events"
        assert "pricing" in guide_payload["data"][0]

        district_res = await client.read_resource("istanbul://districts/kadikoy")
        district_payload = json.loads(district_res.contents[0].text)
        assert district_payload["ok"] is True
        assert district_payload["data"][0]["district"] == "Kadıköy"
        assert district_payload["data"][0]["static_place_anchors"]

        comp_district = await client.complete(
            PromptReference(name="gunun_ozeti"),
            {"name": "district", "value": "kadik"},
        )
        assert "Kadıköy" in comp_district.completion.values

        comp_topic = await client.complete(
            ResourceTemplateReference(uri="istanbul://guides/{topic}"),
            {"name": "topic", "value": "ev"},
        )
        assert comp_topic.completion.values == ["events"]

        comp_interest = await client.complete(
            PromptReference(name="etkinlik_plani"),
            {"name": "interests", "value": "con"},
        )
        assert "concert" in comp_interest.completion.values

        comp_side = await client.complete(
            PromptReference(name="etkinlik_plani"),
            {"name": "side", "value": "avr"},
        )
        assert "Avrupa Yakası" in comp_side.completion.values


@pytest.mark.asyncio
async def test_shared_http_pool_reuses_client_and_closes_on_exit(monkeypatch):
    monkeypatch.delenv("IBB_RELAY_BASE_URL", raising=False)
    monkeypatch.delenv("IBB_RELAY_TOKEN", raising=False)
    from app.core.settings import get_settings

    get_settings.cache_clear()
    async with shared_http_pool(get_settings()) as pool:
        async with ibb_http_client(timeout=5.0) as first:
            assert isinstance(first, _BorrowedAsyncClient)
            assert first._pool is pool
        assert not pool.is_closed
        async with ibb_http_client(timeout=10.0) as second:
            assert isinstance(second, _BorrowedAsyncClient)
            assert second._pool is pool
            assert second.timeout.read == 10.0
    assert pool.is_closed


def test_otel_helpers_are_safe_noop_without_active_span():
    assert current_trace_fields() == {}
    headers = {"Accept": "application/json"}
    assert inject_trace_headers(headers) == headers


@pytest.mark.asyncio
async def test_validation_hardening_turkish_lines_market_district_equipment_and_disruptions(tmp_path):
    from app.core.validation import InputValidationError, validate_line_code
    from app.services.disruptions import TransportDisruptionService
    from app.services.markets import MarketService
    from app.services.metro_accessibility import validate_query

    assert validate_line_code("15kç") == "15KÇ"
    assert validate_line_code("14ŞB") == "14ŞB"
    with pytest.raises(InputValidationError):
        validate_line_code("bad line!")

    assert validate_query(line="M2", station=None, equipment_type="asansör", limit=5).equipment_type == "asansör"
    with pytest.raises(InputValidationError) as eq_err:
        validate_query(line=None, station=None, equipment_type="invalid", limit=5)
    assert eq_err.value.field == "equipment_type"

    s = Settings(database_path=tmp_path / "val.sqlite3")
    mkt = await MarketService(s).schedule(district="Ankara", day="today")
    assert mkt["ok"] is False and mkt["error"]["field"] == "district"

    dis = await TransportDisruptionService(settings=s).disruptions(line="bad line!")
    assert dis["ok"] is False and dis["error"]["field"] == "line"

    from app.services.city import CityService
    from app.services.pharmacy import PharmacyService

    ph_bad = await PharmacyService(settings=s).by_district(district="İzmir")
    assert ph_bad["ok"] is False and ph_bad["error"]["field"] == "district"

    pk_bad = await CityService(settings=s).parking_by_district(district="İzmir")
    assert pk_bad["ok"] is False and pk_bad["error"]["field"] == "district"

    from app.services.iski import IskiService
    from app.services.neighborhood import DISTRICTS_BY_NORMALIZED, normalize_neighborhood_text
    from app.services.places import resolve_district

    iski_bad = await IskiService(settings=s).active_faults(district="Ankara")
    assert iski_bad["ok"] is False and iski_bad["error"]["field"] == "district"
    assert DISTRICTS_BY_NORMALIZED[normalize_neighborhood_text(resolve_district("Eyüp"))] == "EYÜPSULTAN"

    from app.services.neighborhood import COLLOQUIAL_NEIGHBORHOOD_HINTS

    assert COLLOQUIAL_NEIGHBORHOOD_HINTS[("kadikoy", "moda")] == "Caferağa"
    assert "Teşvikiye" in COLLOQUIAL_NEIGHBORHOOD_HINTS[("sisli", "nisantasi")]
