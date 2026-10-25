"""Build the compact surface without deleting legacy Python entry points."""
from __future__ import annotations

from importlib import metadata
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import Tool as MCPTool, ToolAnnotations

from app.core.settings import Settings
from app.core.tool_telemetry import ToolTelemetry
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
    "istanbul_market_schedule",
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
    "istanbul_market_schedule": "İstanbul pazar takvimi",
    "istanbul_traffic_status": "İstanbul trafik yoğunluğu",
    "istanbul_water_status": "İSKİ su ve baraj durumu",
    "istanbul_mobility_nearby": "Yakındaki ulaşım seçenekleri",
    "istanbul_city_services_nearby": "Yakındaki WiFi ve kütüphaneler",
    "istanbul_neighborhood_profile": "İstanbul mahalle profili",
    "istanbul_transit_line": "İETT hat bilgileri ve tarifesi",
    "istanbul_transport_disruptions": "Ulaşım aksaklıkları ve duyurular",
    "istanbul_metro_accessibility_status": "Metro ekipman ve arıza durumu",
    "istanbul_next_departures": "Planlı GTFS durak kalkışları",
    "istanbul_gtfs_snapshot_status": "GTFS tarife anlık görüntü durumu",
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


def package_version() -> str:
    try:
        return metadata.version("istanbul-mcp")
    except metadata.PackageNotFoundError:
        return "0.0.0-local"


class IstanbulMCPServer(MCPServer):
    hidden_tools: frozenset[str] = frozenset()
    telemetry: ToolTelemetry | None = None

    async def list_tools(self) -> list[MCPTool]:
        return [tool for tool in await super().list_tools() if tool.name not in self.hidden_tools]

    def callable_tool_names(self) -> set[str]:
        return {tool.name for tool in self._tool_manager.list_tools()}

    async def call_tool(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        if self.telemetry is None:
            return await self._call_tool_compatible(name, arguments, context)
        with self.telemetry.track(name) as observation:
            result = await self._call_tool_compatible(name, arguments, context)
            observation.result(result)
            return result

    async def _call_tool_compatible(self, name: str, arguments: dict[str, Any], context: Any = None) -> Any:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as exc:
            if str(exc) != f"Unknown tool: {name}":
                raise
            listed = ", ".join(tool.name for tool in await self.list_tools())
            raise ToolError(
                f"Unknown tool: {name}. The tool list may be outdated; call tools/list again. Available tools: {listed}"
            ) from None


def create_mcp_server(settings: Settings) -> MCPServer:
    # Lazy import avoids a cycle: the module's compatibility singleton is built
    # only after its functions have been defined.
    from app.mcp import server as handlers

    server = IstanbulMCPServer("istanbul-mcp", title="Istanbul MCP", version=package_version(), instructions=SERVER_INSTRUCTIONS)
    names = DEFAULT_TOOL_NAMES + LEGACY_TOOL_NAMES
    hidden = set() if settings.mcp_legacy_tools_enabled else set(LEGACY_TOOL_NAMES)
    if not settings.ferry_schedules_enabled:
        hidden.add("istanbul_ferry_schedules")
    names += ("istanbul_next_departures", "istanbul_gtfs_snapshot_status")
    if not settings.gtfs_schedule_enabled:
        hidden.update({"istanbul_next_departures", "istanbul_gtfs_snapshot_status"})
    for name in names:
        handler = getattr(handlers, name)
        structured = name in STRUCTURED_TOOL_NAMES | STRUCTURED_LEGACY_TOOL_NAMES or name in {
            "istanbul_next_departures", "istanbul_gtfs_snapshot_status", "istanbul_market_schedule",
        }
        if structured:
            handler = with_envelope_output(handler)
        server.add_tool(handler, title=TOOL_TITLES[name], annotations=READ_ONLY,
                        structured_output=True if structured else None)
    handlers.register_ferry_schedule_tool(server, True)
    server.telemetry = ToolTelemetry(server.callable_tool_names())
    server.hidden_tools = frozenset(hidden)
    register_resources(server, settings)
    register_prompts(server)
    return server
