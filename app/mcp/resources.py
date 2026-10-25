"""Local, credential-free discovery resources; reading never probes an upstream."""
from __future__ import annotations

import json
from typing import Any

from mcp.server import MCPServer

from app.core.envelope import Freshness, ResponseEnvelope, Source, success_envelope
from app.core.settings import Settings

# Canonical public references only. Deployment overrides can contain credentials
# or private relay addresses and must never be copied into discovery metadata.
SOURCE_CATALOG = (
    ("runtime", "Istanbul MCP runtime", "Istanbul MCP", None, "local_metadata"),
    ("ckan", "İBB Açık Veri", "İBB", "https://data.ibb.gov.tr", "catalog_and_static_records"),
    ("ibb_open_data_layers", "İBB açık veri nokta katmanları", "İBB", "https://data.ibb.gov.tr", "static_point_layers"),
    ("ibb_open_data_market", "İBB pazar yerleri", "İBB", "https://data.ibb.gov.tr", "weekly_market_schedule"),
    ("wikidata_places", "Wikidata place references (CC0)", "Wikidata contributors", "https://www.wikidata.org/wiki/Wikidata:Licensing", "static_place_reference"),
    ("ispark", "İSPARK", "İBB / İSPARK", "https://api.ibb.gov.tr/ispark", "parking_snapshot"),
    ("metro", "Metro İstanbul", "Metro İstanbul", "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2", "stations_and_service_status"),
    ("air_quality", "İBB Hava Kalitesi", "İBB", "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler", "station_readings"),
    ("traffic", "İBB Trafik", "İBB", "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1", "citywide_index"),
    ("ibb_pharmacy", "İBB Nöbetçi Eczaneler", "İBB", "https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=all", "on_duty_roster"),
    ("iski", "İSKİ", "İSKİ", "https://harita.iski.gov.tr", "faults_and_dam_snapshots"),
    ("gtfs_schedule", "İETT GTFS tarife", "İETT", "https://data.ibb.gov.tr/dataset/iett-gtfs-verisi", "published_timetable"),
    ("iett", "İETT", "İETT", "https://api.ibb.gov.tr/iett", "lines_stops_planned_departures_and_notices"),
    ("metro_istanbul", "Metro İstanbul Erişilebilirlik", "Metro İstanbul", "https://www.metro.istanbul/MetroIstanbulBuzPateni2024/SeferDurumlari/Ariza", "equipment_counts_and_faults"),
    ("istanbulkart", "İstanbulkart Dolum Merkezleri", "İBB", "https://data.ibb.gov.tr/dataset/istanbulkart-dolum-merkezi-bilgileri", "static_locations"),
    ("social_facilities", "İBB Sosyal Tesisler", "İBB", "https://tesislerimiz.ibb.istanbul/tesisler", "static_locations_and_links"),
    ("sehir_hatlari", "Şehir Hatları", "Şehir Hatları", "https://sehirhatlari.istanbul/tr/iptal-seferler", "official_notices"),
    ("marmaray", "Marmaray", "TCDD Taşımacılık", "https://www.tcddtasimacilik.gov.tr/marmaray/tr/son_dakika", "official_notices"),
)


def _document(summary: str, data: list[dict[str, Any]], *, limits: list[str] | None = None) -> str:
    payload = success_envelope(
        summary=summary,
        data=data,
        sources=[Source(name="Istanbul MCP capability definitions and configuration",
                        publisher="Istanbul MCP", license=None)],
        freshness=Freshness(status="fresh", ttl_seconds=60),
        limits=["Local metadata only; no upstream health checks or live readings.", *(limits or [])],
        warnings=["Metadata freshness does not establish source availability; inspect tool-result freshness and warnings."],
    )
    return json.dumps(payload, ensure_ascii=False)


def _coverage(settings: Settings, actual_tools: set[str]) -> list[dict[str, Any]]:
    # Configured/enabled is deliberately not called healthy or available.
    entries = [
        ("runtime", ["istanbul_health"], ["runtime"], "local_readiness",
         "SQLite/runtime readiness only; does not check upstream data sources."),
        ("catalog", ["istanbul_search_datasets", "istanbul_get_dataset", "istanbul_get_resource_schema", "istanbul_query_resource"], ["ckan"], "catalog_and_records",
         "Inspect the selected resource schema; catalog metadata is not proof of DataStore access."),
        ("nearby", ["istanbul_nearby"], ["ispark", "metro", "air_quality", "ckan", "iski", "istanbulkart", "social_facilities", "ibb_open_data_layers"], "mixed_snapshots_and_static_locations",
         "Coordinates, supported district search, or bbox; static locations do not establish live operating status."),
        ("market_schedule", ["istanbul_market_schedule"], ["ibb_open_data_market"], "weekly_static_schedule",
         "Published weekly markets; holidays, relocations and closures may differ. Not live opening status."),
        ("pharmacy", ["istanbul_nearby"], ["ibb_pharmacy"], "on_duty_roster",
         'Use kind="pharmacy"; no duty-end guarantee. Call first; address-search links are not verified pins.'),
        ("traffic", ["istanbul_traffic_status"], ["traffic"], "citywide_snapshot",
         "Citywide index only, not road-level incidents."),
        ("water", ["istanbul_water_status"], ["iski"], "faults_and_dam_snapshots",
         "Fallbacks can be stale; fault positions are approximate and restoration times are not guaranteed."),
        ("mobility", ["istanbul_mobility_nearby"], ["ispark", "metro", "air_quality", "traffic", "ckan", "wikidata_places"], "mixed_snapshots_and_static_locations",
         "All 39 districts: parking only, without distances. Named areas use static reference points, not address geocoding. GTFS stops are static; no live arrivals or A-to-B routing."),
        ("city_services", ["istanbul_city_services_nearby"], ["ckan", "ibb_open_data_layers", "wikidata_places"], "static_locations",
         "All 39 districts: library/cultural address lists, without WiFi or invented distances. Point mode adds WiFi. Acıbadem requires Kadıköy or Üsküdar. Not full address geocoding or live availability."),
        ("neighborhood", ["istanbul_neighborhood_profile"], ["ckan"], "historical_scenario",
         "2023 social/building/earthquake scenario records; not an individual-building safety assessment."),
        ("gtfs_schedule", ["istanbul_next_departures"], ["gtfs_schedule"], "published_timetable",
         "Opt-in. stop_query with limit searches names only and returns separate stop_id candidates, not departures; confirm by name/map. Turkish/ASCII supported; suggestions are not matches. No district/direction inference. Selected-stop departures enforce calendar validity; not live ETA."),
        ("transit", ["istanbul_transit_line"], ["iett"], "published_plan",
         "Line info, ordered stops and planned main-terminal departures; not intermediate-stop ETA."),
        ("transport_disruptions", ["istanbul_transport_disruptions"], ["iett", "metro", "sehir_hatlari", "marmaray"], "official_status_and_notices",
         "Partial/unavailable coverage is not proof of normal service; unsupported operators remain explicit limits."),
        ("metro_accessibility", ["istanbul_metro_accessibility_status"], ["metro_istanbul"], "equipment_counts_and_faults",
         "Equipment status is not an end-to-end accessibility guarantee."),
        ("bounded_sql", ["istanbul_datastore_query"], ["ckan"], "bounded_local_capture",
         "Only allowlisted resources; complete bounded capture required. No writes or application DB access."),
        ("ferry_timetables", ["istanbul_ferry_schedules"], ["sehir_hatlari"], "published_timetable",
         "Opt-in after deployment-source verification; cancellation-notice relay does not serve timetables. Not live ETA."),
    ]
    data = []
    for capability, names, sources, kind, warning in entries:
        enabled = any(name in actual_tools for name in names)
        if capability == "bounded_sql":
            enabled = enabled and bool(settings.ckan_sql_allowed_resource_ids)
        data.append({
            "capability": capability,
            "tools": [name for name in names if name in actual_tools],
            "source_ids": sources,
            "data_kind": kind,
            "configuration_status": "enabled" if enabled else "disabled",
            "upstream_health": "not_checked",
            "warning": warning,
        })
    return data


def register_resources(server: MCPServer, settings: Settings) -> None:
    @server.resource(
        "istanbul://coverage", name="istanbul_coverage", title="İstanbul veri kapsamı",
        description="Supported capabilities and configuration gates, not live source health.",
        mime_type="application/json",
    )
    async def coverage() -> str:
        actual_tools = {tool.name for tool in await server.list_tools()}
        return _document(
            "Istanbul MCP configured coverage; upstream health not checked.",
            _coverage(settings, actual_tools),
            limits=[f"tool_count={len(actual_tools)}", f"max_radius_m={settings.max_radius_m}"],
        )

    @server.resource(
        "istanbul://sources", name="istanbul_sources", title="İstanbul veri kaynakları",
        description="Canonical publishers and public source references; no secrets or deployment URLs.",
        mime_type="application/json",
    )
    def sources() -> str:
        return _document("Istanbul MCP source directory, not a health report.", [
            {
                "source_id": source_id,
                "name": name,
                "publisher": publisher,
                "url": url,
                "data_kind": kind,
                "license": None,
                "license_note": "Inspect dataset/source terms; public read access is not a license grant.",
                "freshness_note": "Actual timestamps, TTL and fallback status are supplied by each tool result.",
                "upstream_health": "not_checked",
            }
            for source_id, name, publisher, url, kind in SOURCE_CATALOG
        ])

    @server.resource(
        "istanbul://schema/catalog", name="istanbul_catalog_schema", title="Katalog keşif şeması",
        description="Catalog tool inputs, envelope schema and query bounds, not a live DataStore field schema.",
        mime_type="application/json",
    )
    async def catalog_schema() -> str:
        catalog_tools = {
            "istanbul_search_datasets", "istanbul_get_dataset", "istanbul_get_resource_schema",
            "istanbul_query_resource", "istanbul_datastore_query",
        }
        return _document("Catalog discovery workflow and response contract.", [{
            "workflow": [
                "istanbul_search_datasets", "istanbul_get_dataset",
                "istanbul_get_resource_schema", "istanbul_query_resource",
            ],
            "tools": [
                {"name": tool.name, "input_schema": tool.input_schema}
                for tool in await server.list_tools() if tool.name in catalog_tools
            ],
            "envelope_schema": ResponseEnvelope.model_json_schema(),
            "resource_fields_are_dynamic": True,
            "field_schema_instruction": "Call istanbul_get_resource_schema for the selected resource_id before querying.",
            "query_bounds": {
                "default_limit": settings.default_limit, "max_limit": settings.max_limit,
                "sql_enabled": bool(settings.ckan_sql_allowed_resource_ids),
                "sql_max_rows": settings.ckan_sql_max_rows, "sql_max_bytes": settings.ckan_sql_max_bytes,
            },
        }])
