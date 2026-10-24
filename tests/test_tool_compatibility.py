import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app.core.settings import Settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, create_mcp_server

# Every tool name that production has ever listed. Clients cache tools/list, so
# a name may leave the listing but must stay callable; never delete entries here.
PUBLISHED_TOOL_NAMES = frozenset({
    "istanbul_air_quality_nearby", "istanbul_bbox_search", "istanbul_city_services_nearby",
    "istanbul_datastore_query", "istanbul_ferry_schedules", "istanbul_get_dataset",
    "istanbul_get_resource_schema", "istanbul_health", "istanbul_iski_active_faults",
    "istanbul_iski_dam_occupancy", "istanbul_iski_fault_by_number", "istanbul_iski_nearby_faults",
    "istanbul_istanbulkart_centers_nearby", "istanbul_market_schedule",
    "istanbul_metro_accessibility_status", "istanbul_metro_stations_nearby",
    "istanbul_mobility_nearby", "istanbul_nearby", "istanbul_neighborhood_profile",
    "istanbul_nobetci_eczane_by_district", "istanbul_nobetci_eczane_nearby",
    "istanbul_parking_by_district", "istanbul_parking_nearby", "istanbul_planned_departures",
    "istanbul_query_resource", "istanbul_search_datasets", "istanbul_sosyal_tesis_nearby",
    "istanbul_stops_for_line", "istanbul_traffic_status", "istanbul_transit_disruptions",
    "istanbul_transit_line", "istanbul_transit_line_info", "istanbul_transport_disruptions",
    "istanbul_water_status",
})


def listed(server) -> set[str]:
    return {tool.name for tool in asyncio.run(server.list_tools())}


@pytest.mark.parametrize("settings", [Settings(), Settings(mcp_legacy_tools_enabled=True, ferry_schedules_enabled=True)])
def test_every_published_tool_name_stays_callable(settings):
    server = create_mcp_server(settings)
    assert PUBLISHED_TOOL_NAMES <= server.callable_tool_names()


def test_retired_names_are_callable_but_not_listed_by_default():
    server = create_mcp_server(Settings())
    assert listed(server) == set(DEFAULT_TOOL_NAMES)
    assert {"istanbul_parking_nearby", "istanbul_ferry_schedules"} <= server.callable_tool_names() - listed(server)


def test_hidden_alias_runs_through_the_mcp_call_path(monkeypatch):
    from app.mcp import server as handlers

    async def istanbul_parking_nearby(lat: float, lon: float, radius_m: int = 1000, limit: int | None = None) -> dict:
        return {"ok": True, "summary": "parking alias", "data": [{"lat": lat, "lon": lon}], "freshness": {"status": "fresh"}}

    monkeypatch.setattr(handlers, "istanbul_parking_nearby", istanbul_parking_nearby)
    server = create_mcp_server(Settings())
    result = asyncio.run(server.call_tool("istanbul_parking_nearby", {"lat": 41.0, "lon": 29.0}))

    assert "parking alias" in str(result)


def test_unknown_tool_error_tells_clients_to_refresh_the_list():
    server = create_mcp_server(Settings())
    with pytest.raises(ToolError) as error:
        asyncio.run(server.call_tool("istanbul_not_a_tool", {}))

    assert "tools/list" in str(error.value)
    assert "istanbul_nearby" in str(error.value)
