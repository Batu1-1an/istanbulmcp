"""Published schemas and structuredContent must match the existing JSON envelope."""
import asyncio
import inspect
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

from jsonschema import Draft202012Validator
from mcp import Client
from mcp.server import MCPServer
import pytest

from app.core.envelope import Freshness, Pagination, ResponseEnvelope, Source, error_envelope, success_envelope
from app.core.settings import Settings
from app.mcp.registry import create_mcp_server
from app.mcp.structured import STRUCTURED_LEGACY_TOOL_NAMES, STRUCTURED_TOOL_NAMES, with_envelope_output
import app.mcp.server as handlers

CASES = [
    ("istanbul_nearby", {"lat": 41, "lon": 29}, "CityService", "nearby"),
    ("istanbul_traffic_status", {}, "CityService", "traffic_status"),
    ("istanbul_water_status", {}, "IskiService", "active_faults"),
    ("istanbul_transit_line", {"line_code": "500T"}, "TransitService", "line_info"),
    ("istanbul_transport_disruptions", {}, "TransportDisruptionService", "disruptions"),
    ("istanbul_market_schedule", {"district": "Kadıköy"}, "MarketService", "schedule"),
    ("istanbul_nobetci_eczane_nearby", {"lat": 41, "lon": 29}, "PharmacyService", "nearby"),
    ("istanbul_nobetci_eczane_by_district", {"district": "Kadıköy"}, "PharmacyService", "by_district"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_only_selected_tools_publish_the_canonical_envelope_schema(legacy):
    server = create_mcp_server(Settings(mcp_legacy_tools_enabled=legacy))
    tools = await server.list_tools()
    expected = STRUCTURED_TOOL_NAMES | (STRUCTURED_LEGACY_TOOL_NAMES if legacy else set())
    structured = {tool.name for tool in tools if tool.output_schema is not None}
    assert len(STRUCTURED_TOOL_NAMES) == 6
    assert structured == expected
    for tool in tools:
        if tool.name in expected:
            assert tool.output_schema == ResponseEnvelope.model_json_schema()
            Draft202012Validator.check_schema(tool.output_schema)


@pytest.mark.parametrize("name", sorted(STRUCTURED_TOOL_NAMES | STRUCTURED_LEGACY_TOOL_NAMES))
def test_adapter_preserves_input_schema_docstring_and_bare_dict_handler(name):
    handler = getattr(handlers, name)
    adapted = with_envelope_output(handler)
    original = inspect.signature(handler, eval_str=True)
    signature = inspect.signature(adapted)
    assert signature.parameters == original.parameters
    assert original.return_annotation is dict
    assert signature.return_annotation is ResponseEnvelope
    assert adapted.__name__ == handler.__name__
    assert adapted.__doc__ == handler.__doc__
    assert inspect.iscoroutinefunction(adapted)

    reference = MCPServer("unadapted")
    reference.add_tool(handler, structured_output=False)
    configured = create_mcp_server(Settings(mcp_legacy_tools_enabled=True))
    original_tool = asyncio.run(reference.list_tools())[0]
    actual_tool = next(tool for tool in asyncio.run(configured.list_tools()) if tool.name == name)
    assert actual_tool.input_schema == original_tool.input_schema
    assert actual_tool.description == original_tool.description


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
@pytest.mark.parametrize("state", ["fresh", "stale", "broken"])
@pytest.mark.parametrize("name,arguments,service_name,method_name", CASES, ids=[case[0] for case in CASES])
async def test_structured_and_text_outputs_preserve_success_stale_and_failure_envelopes(
    name, arguments, service_name, method_name, mode, state, monkeypatch,
):
    payload = success_envelope(
        summary="Türkçe fixture sonucu",
        data=[{"name": "Kadıköy", "nullable_field": None, "domain_extra": {"value": 2}}],
        sources=[Source(
            name="Fixture source", publisher="Fixture", license=None,
            operator="fixture", coverage_status="unavailable" if state == "broken" else "checked",
            source_updated_at="2026-10-19T12:00:00Z", accepted_total=1, reported_total=2,
        )],
        freshness=Freshness(status=state, ttl_seconds=60),
        pagination=Pagination(limit=2, total_estimate=2),
        limits=["limit=2", "not a live availability guarantee"],
        warnings=["Preserve source uncertainty."],
        next_queries=["Check the selected resource schema."],
        geojson={"type": "FeatureCollection", "features": []},
    )
    payload["ok"] = state != "broken"
    service_method = AsyncMock(return_value=payload)
    monkeypatch.setattr(handlers, service_name,
                        lambda **_kw: SimpleNamespace(**{method_name: service_method}))
    server = create_mcp_server(Settings(mcp_legacy_tools_enabled=True))
    async with Client(server, mode=mode) as client:
        result = await client.call_tool(name, arguments)
        assert not result.is_error
        assert result.structured_content == payload
        assert len(result.content) == 1
        assert json.loads(result.content[0].text) == payload
        listed = await client.list_tools()
        schema = next(tool.output_schema for tool in listed.tools if tool.name == name)
        Draft202012Validator(schema).validate(result.structured_content)

    # MCP adaptation must not replace the direct Python entry point or its dict result.
    direct = await getattr(handlers, name)(**arguments)
    assert type(direct) is dict and direct == payload
    assert service_method.await_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_expected_validation_failure_is_structured_not_an_mcp_execution_error(mode):
    async with Client(create_mcp_server(Settings()), mode=mode) as client:
        result = await client.call_tool("istanbul_nearby", {})
    assert result.is_error is False
    assert result.structured_content["ok"] is False
    assert result.structured_content["data"][0]["error_code"] == "validation_error"
    assert json.loads(result.content[0].text) == result.structured_content


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_malformed_source_output_fails_closed_without_leaking_validation_values(mode, monkeypatch):
    secret = "fixture-private-validation-value"
    method = AsyncMock(return_value={"summary": "invalid fixture", "freshness": {"status": secret}})
    monkeypatch.setattr(handlers, "CityService", lambda **_kw: SimpleNamespace(traffic_status=method))
    async with Client(create_mcp_server(Settings()), mode=mode) as client:
        result = await client.call_tool("istanbul_traffic_status", {})
    assert result.is_error is True
    assert result.structured_content is None
    assert secret not in json.dumps(result.model_dump(mode="json"))
    assert "Error executing tool istanbul_traffic_status" in result.content[0].text


@pytest.mark.asyncio
async def test_adapter_retains_standard_source_error_envelope(monkeypatch):
    payload = error_envelope(summary="Source unavailable", warning="Call again later", limits=["fixture"])
    method = AsyncMock(return_value=payload)
    monkeypatch.setattr(handlers, "CityService", lambda **_kw: SimpleNamespace(traffic_status=method))
    async with Client(create_mcp_server(Settings())) as client:
        result = await client.call_tool("istanbul_traffic_status", {})
    assert result.is_error is False
    assert result.structured_content == payload
    assert result.structured_content["freshness"]["status"] == "broken"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
async def test_live_test_fixes_survive_real_service_and_mcp_serialization(mode, monkeypatch, tmp_path):
    from app.connectors.city_open_data import OpenDataLayer
    from app.core.source_cache import clear_source_cache
    from app.services.city import CityService
    from app.services.neighborhood import BUILDING_STOCK_RESOURCE_ID, NeighborhoodService

    clear_source_cache()
    settings = Settings(database_path=tmp_path / "live-test-fixes.sqlite3")
    city = CityService(
        settings=settings,
        traffic_client=SimpleNamespace(index_history=AsyncMock(return_value=[{
            "TrafficIndex": 33, "TrafficIndexDate": "2026-10-24T23:30:00",
        }])),
        ckan_client=SimpleNamespace(datastore_search=AsyncMock(return_value={"records": []})),
        open_data_client=SimpleNamespace(layer=AsyncMock(return_value=OpenDataLayer(
            kind="cultural_centre", rows=[{"Kültür Merkezi": "Beşiktaş Kültür", "İlçe": "Beşiktaş"}],
            dataset_id="fixture", resource_id="fixture", source_url="https://example.test/culture",
            reported_total=1, received_bytes=100, received_total=1,
        ))),
    )

    async def neighborhood_rows(*, resource_id, **_kwargs):
        rows = [{"ilce_adi": "KADIKÖY", "mahalle_adi": "CAFERAÐA"}] if resource_id == BUILDING_STOCK_RESOURCE_ID else []
        return {"records": rows, "total": len(rows)}

    neighborhood = NeighborhoodService(
        settings=settings, ckan_client=SimpleNamespace(datastore_search=neighborhood_rows),
    )
    monkeypatch.setattr(handlers, "CityService", lambda **_kwargs: city)
    monkeypatch.setattr(handlers, "NeighborhoodService", lambda **_kwargs: neighborhood)
    async with Client(create_mcp_server(settings), mode=mode) as client:
        traffic = await client.call_tool("istanbul_traffic_status", {})
        assert not traffic.is_error
        assert traffic.structured_content["data"][0]["measured_at"] == "2026-10-24T23:30:00+03:00"
        assert json.loads(traffic.content[0].text) == traffic.structured_content
        assert traffic.structured_content["sources"][0]["publisher"] == "Istanbul Metropolitan Municipality"
        assert traffic.structured_content["sources"][0]["url"] is None
        assert "api.ibb.gov.tr" not in traffic.content[0].text

        services = await client.call_tool("istanbul_city_services_nearby", {"place": "Kadıköy"})
        assert not services.is_error
        payload = json.loads(services.content[0].text)
        source = next(s for s in payload["sources"] if s["resource_id"] == "fixture")
        assert source["accepted_total"] == 1
        assert source["skipped_total"] == source["matched_total"] == source["returned_total"] == 0
        assert any("No cultural centre matched" in w for w in payload["warnings"])

        profile = await client.call_tool("istanbul_neighborhood_profile", {"district": "Kadıköy", "neighborhood": "Caferağa"})
        assert not profile.is_error
        row = json.loads(profile.content[0].text)["data"][0]
        assert row["neighborhood"] == row["source_names"]["building_stock"] == "CAFERAĞA"
        assert row["raw_source_names"]["building_stock"] == "CAFERAÐA"
