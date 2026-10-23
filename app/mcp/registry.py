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


TOOL_TITLES = {
    "istanbul_health": "İstanbul servis durumu",
    "istanbul_search_datasets": "İBB veri seti arama",
    "istanbul_get_dataset": "İBB veri seti bilgileri",
    "istanbul_get_resource_schema": "İBB kaynak kolonları",
    "istanbul_query_resource": "İBB kaynak kayıtları",
    "istanbul_datastore_query": "Sınırlı açık veri SQL sorgusu",
    "istanbul_nearby": "Yakındaki İstanbul hizmetleri",
    "istanbul_traffic_status": "İstanbul trafik yoğunluğu",
    "istanbul_water_status": "İSKİ su ve baraj durumu",
    "istanbul_mobility_nearby": "Yakındaki ulaşım seçenekleri",
    "istanbul_city_services_nearby": "Yakındaki WiFi ve kütüphaneler",
    "istanbul_neighborhood_profile": "İstanbul mahalle profili",
    "istanbul_transit_line": "İETT hat bilgileri ve tarifesi",
    "istanbul_transport_disruptions": "Ulaşım aksaklıkları ve duyurular",
    "istanbul_metro_accessibility_status": "Metro ekipman ve arıza durumu",
    "istanbul_next_departures": "Planlı GTFS durak kalkışları",
    "istanbul_ferry_schedules": "Şehir Hatları yayımlanmış tarifesi",
    "istanbul_bbox_search": "Harita alanındaki şehir noktaları",
    "istanbul_parking_nearby": "Yakındaki İSPARK otoparkları",
    "istanbul_parking_by_district": "İlçedeki İSPARK otoparkları",
    "istanbul_nobetci_eczane_nearby": "Yakındaki nöbetçi eczaneler",
    "istanbul_nobetci_eczane_by_district": "İlçedeki nöbetçi eczaneler",
    "istanbul_istanbulkart_centers_nearby": "Yakındaki İstanbulkart dolum merkezleri",
    "istanbul_sosyal_tesis_nearby": "Yakındaki İBB sosyal tesisleri",
    "istanbul_metro_stations_nearby": "Yakındaki metro istasyonları",
    "istanbul_air_quality_nearby": "Yakındaki hava kalitesi ölçümleri",
    "istanbul_iski_active_faults": "Aktif İSKİ arızaları",
    "istanbul_iski_fault_by_number": "Numarayla İSKİ arıza bilgisi",
    "istanbul_iski_nearby_faults": "Yakındaki İSKİ arızaları",
    "istanbul_iski_dam_occupancy": "İSKİ baraj dolulukları",
    "istanbul_transit_line_info": "İETT hat bilgileri",
    "istanbul_stops_for_line": "İETT hattının sıralı durakları",
    "istanbul_transit_disruptions": "İETT hat aksaklıkları",
    "istanbul_planned_departures": "İETT ana durak planlı kalkışları",
}


def create_mcp_server(settings: Settings) -> MCPServer:
    # Lazy import avoids a cycle: the module's compatibility singleton is built
    # only after its functions have been defined.
    from app.mcp import server as handlers

    server = MCPServer("istanbul-mcp", title="Istanbul MCP", version="0.1.0", instructions=SERVER_INSTRUCTIONS)
    names = DEFAULT_TOOL_NAMES
    if settings.mcp_legacy_tools_enabled:
        names += LEGACY_TOOL_NAMES
    if settings.gtfs_schedule_enabled:
        names += ("istanbul_next_departures",)
    for name in names:
        handler = getattr(handlers, name)
        structured = name in STRUCTURED_TOOL_NAMES | STRUCTURED_LEGACY_TOOL_NAMES or name == "istanbul_next_departures"
        if structured:
            handler = with_envelope_output(handler)
        server.add_tool(handler, title=TOOL_TITLES[name], annotations=READ_ONLY,
                        structured_output=True if structured else None)
    handlers.register_ferry_schedule_tool(server, settings.ferry_schedules_enabled)
    register_resources(server, settings)
    register_prompts(server)
    return server
