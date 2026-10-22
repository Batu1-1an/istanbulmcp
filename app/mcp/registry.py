"""Build the compact surface without deleting legacy Python entry points."""
from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import ToolAnnotations

from app.core.settings import Settings
from app.mcp.instructions import SERVER_INSTRUCTIONS
from app.mcp.prompts import register_prompts
from app.mcp.resources import register_resources
from app.mcp.structured import STRUCTURED_LEGACY_TOOL_NAMES, STRUCTURED_TOOL_NAMES, with_envelope_output

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=True,
)

DEFAULT_TOOL_NAMES = (
    "istanbul_health", "istanbul_search_datasets", "istanbul_get_dataset",
    "istanbul_get_resource_schema", "istanbul_query_resource", "istanbul_nearby",
    "istanbul_traffic_status", "istanbul_water_status", "istanbul_mobility_nearby",
    "istanbul_city_services_nearby", "istanbul_neighborhood_profile",
    "istanbul_transit_line", "istanbul_transport_disruptions",
    "istanbul_metro_accessibility_status", "istanbul_datastore_query",
)

LEGACY_TOOL_NAMES = (
    "istanbul_bbox_search", "istanbul_parking_nearby", "istanbul_parking_by_district",
    "istanbul_nobetci_eczane_nearby", "istanbul_nobetci_eczane_by_district",
    "istanbul_istanbulkart_centers_nearby", "istanbul_sosyal_tesis_nearby",
    "istanbul_metro_stations_nearby", "istanbul_air_quality_nearby",
    "istanbul_iski_active_faults", "istanbul_iski_fault_by_number",
    "istanbul_iski_nearby_faults", "istanbul_iski_dam_occupancy",
    "istanbul_transit_line_info", "istanbul_stops_for_line",
    "istanbul_transit_disruptions", "istanbul_planned_departures",
)


def create_mcp_server(settings: Settings) -> MCPServer:
    # Lazy import avoids a cycle: the module's compatibility singleton is built
    # only after its functions have been defined.
    from app.mcp import server as handlers

    server = MCPServer("istanbul-mcp", version="0.1.0", instructions=SERVER_INSTRUCTIONS)
    names = DEFAULT_TOOL_NAMES
    if settings.mcp_legacy_tools_enabled:
        names += LEGACY_TOOL_NAMES
    for name in names:
        handler = getattr(handlers, name)
        structured = name in STRUCTURED_TOOL_NAMES | STRUCTURED_LEGACY_TOOL_NAMES
        if structured:
            handler = with_envelope_output(handler)
        server.add_tool(handler, annotations=READ_ONLY, structured_output=True if structured else None)
    handlers.register_ferry_schedule_tool(server, settings.ferry_schedules_enabled)
    register_resources(server, settings)
    register_prompts(server)
    return server
