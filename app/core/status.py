from __future__ import annotations

from importlib import metadata
from typing import Any

from app.core.settings import Settings
from app.core.source_cache import source_cache_snapshot
from app.mcp.server import mcp
from app.storage.db import public_readiness, readiness

TOOL_SOURCES = {
    "istanbul_health": "runtime",
    "istanbul_search_datasets": "ckan",
    "istanbul_get_dataset": "ckan",
    "istanbul_get_resource_schema": "ckan",
    "istanbul_query_resource": "ckan",
    "istanbul_nearby": "sqlite",
    "istanbul_bbox_search": "sqlite",
    "istanbul_parking_nearby": "ispark",
    "istanbul_parking_by_district": "ispark",
    "istanbul_nobetci_eczane_nearby": "ieo",
    "istanbul_nobetci_eczane_by_district": "ieo",
    "istanbul_istanbulkart_centers_nearby": "istanbulkart",
    "istanbul_sosyal_tesis_nearby": "social_facilities",
    "istanbul_metro_stations_nearby": "metro",
    "istanbul_air_quality_nearby": "air_quality",
    "istanbul_traffic_status": "traffic",
    "istanbul_iski_active_faults": "iski",
    "istanbul_iski_fault_by_number": "iski",
    "istanbul_iski_nearby_faults": "iski",
    "istanbul_iski_dam_occupancy": "iski",
    "istanbul_mobility_nearby": "mixed_city_open_data",
    "istanbul_city_services_nearby": "ckan",
    "istanbul_neighborhood_profile": "ckan",
    "istanbul_transit_line_info": "iett",
    "istanbul_stops_for_line": "iett",
    "istanbul_transit_disruptions": "iett",
    "istanbul_transport_disruptions": "mixed_transport_official",
    "istanbul_planned_departures": "iett",
    "istanbul_ferry_schedules": "sehir_hatlari",
}


def build_status(settings: Settings, *, abuse_guard: dict[str, Any] | None = None) -> dict[str, Any]:
    tools = _tool_inventory()
    return {
        "ok": True,
        "service": settings.app_name,
        "version": _package_version(),
        "transport": {
            "streamable_http": "/mcp/",
            "canonical_redirect": "/mcp -> /mcp/",
        },
        "limits": {
            "default_limit": settings.default_limit,
            "max_limit": settings.max_limit,
            "max_radius_m": settings.max_radius_m,
            "request_timeout_seconds": settings.request_timeout_seconds,
            "iski_request_timeout_seconds": settings.iski_request_timeout_seconds,
            "iski_request_attempts": settings.iski_request_attempts,
            "iski_api_fallback_enabled": bool(settings.iski_api_bearer_token),
            "iski_relay_enabled": bool(settings.iski_relay_base_url and settings.iski_relay_token),
            "iski_relay_timeout_seconds": settings.iski_relay_timeout_seconds,
            "marmaray_api_fallback_enabled": bool(settings.marmaray_api_basic_token),
            "sehir_hatlari_relay_enabled": bool(
                settings.sehir_hatlari_relay_url and settings.sehir_hatlari_relay_token
            ),
            "iski_snapshot_fallback_enabled": {
                "faults": bool(settings.iski_faults_snapshot_json),
                "dams": bool(settings.iski_dams_snapshot_json),
            },
            "iski_snapshot_max_age_seconds": {
                "faults": settings.iski_faults_snapshot_max_age_seconds,
                "dams": settings.iski_dams_snapshot_max_age_seconds,
            },
            "cache_ttl_seconds": {
                "ckan_catalog": settings.ckan_catalog_cache_ttl_seconds,
                "ckan_resource": settings.ckan_resource_cache_ttl_seconds,
                "iett_line": settings.iett_line_cache_ttl_seconds,
                "iett_stops": settings.iett_stops_cache_ttl_seconds,
                "transport_disruptions": settings.transport_disruptions_cache_ttl_seconds,
                "ferry_schedules": settings.ferry_schedule_cache_ttl_seconds,
                "ispark": settings.ispark_cache_ttl_seconds,
                "metro": settings.metro_cache_ttl_seconds,
                "air_quality_station": settings.air_quality_station_cache_ttl_seconds,
                "air_quality_reading": settings.air_quality_reading_cache_ttl_seconds,
                "traffic": settings.traffic_cache_ttl_seconds,
                "ieo": settings.ieo_cache_ttl_seconds,
                "istanbulkart": settings.istanbulkart_cache_ttl_seconds,
                "social_facilities": settings.social_facilities_cache_ttl_seconds,
                "iski_faults": settings.iski_faults_cache_ttl_seconds,
                "iski_dams": settings.iski_dams_cache_ttl_seconds,
            },
            "stale_if_error_seconds": {
                "iski_faults": settings.iski_faults_stale_if_error_seconds,
                "iski_dams": settings.iski_dams_stale_if_error_seconds,
                "ieo": settings.ieo_stale_if_error_seconds,
                "istanbulkart": settings.istanbulkart_stale_if_error_seconds,
                "social_facilities": settings.social_facilities_stale_if_error_seconds,
            },
            "istanbulkart": {
                "dataset_id": settings.istanbulkart_dataset_id,
                "resource_override_configured": bool(settings.istanbulkart_resource_id),
                "datastore_page_size": settings.istanbulkart_datastore_page_size,
                "total_cache_age_cap_seconds": (
                    settings.istanbulkart_cache_ttl_seconds
                    + settings.istanbulkart_stale_if_error_seconds
                ),
            },
            "social_facilities": {
                "catalog_url": settings.social_facilities_catalog_url,
                "reservation_url": settings.social_facilities_reservation_url,
                "fallback_configured": bool(settings.social_facilities_ckan_download_url),
                "max_catalog_pages": settings.social_facilities_max_catalog_pages,
                "max_detail_pages": settings.social_facilities_max_detail_pages,
                "total_cache_age_cap_seconds": (
                    settings.social_facilities_cache_ttl_seconds
                    + min(settings.social_facilities_stale_if_error_seconds, 604800)
                ),
            },
            "source_cache_max_entries": settings.source_cache_max_entries,
            "source_rate_limits": {
                "ckan": {
                    "capacity": settings.ckan_rate_capacity,
                    "refill_per_second": settings.ckan_rate_refill_per_second,
                    "max_wait_seconds": settings.ckan_rate_max_wait_seconds,
                },
                "iett": {
                    "capacity": settings.iett_rate_capacity,
                    "refill_per_second": settings.iett_rate_refill_per_second,
                    "max_wait_seconds": settings.iett_rate_max_wait_seconds,
                },
                "air_quality": {
                    "capacity": settings.air_quality_rate_capacity,
                    "refill_per_second": settings.air_quality_rate_refill_per_second,
                    "max_wait_seconds": settings.air_quality_rate_max_wait_seconds,
                },
                "iski": {
                    "capacity": settings.iski_rate_capacity,
                    "refill_per_second": settings.iski_rate_refill_per_second,
                    "max_wait_seconds": settings.iski_rate_max_wait_seconds,
                },
                "transport_notice": {
                    "capacity": settings.transport_notice_rate_capacity,
                    "refill_per_second": settings.transport_notice_rate_refill_per_second,
                    "max_wait_seconds": settings.transport_notice_rate_max_wait_seconds,
                },
                "ieo": {
                    "capacity": settings.ieo_rate_capacity,
                    "refill_per_second": settings.ieo_rate_refill_per_second,
                    "max_wait_seconds": settings.ieo_rate_max_wait_seconds,
                },
                "social_facilities": {
                    "capacity": settings.social_facilities_rate_capacity,
                    "refill_per_second": settings.social_facilities_rate_refill_per_second,
                    "max_wait_seconds": settings.social_facilities_rate_max_wait_seconds,
                },
            },
            "mcp_request_guard": {
                "max_body_bytes": settings.mcp_max_body_bytes,
                "rate_limit_capacity": settings.mcp_rate_limit_capacity,
                "rate_limit_refill_per_second": settings.mcp_rate_limit_refill_per_second,
                "rate_limit_max_clients": settings.mcp_rate_limit_max_clients,
                "max_concurrent_requests": settings.mcp_max_concurrent_requests,
            },
        },
        "abuse_guard": abuse_guard or {},
        "database": public_readiness(readiness(settings.database_path)),
        "source_cache": source_cache_snapshot(),
        "tool_count": len(tools),
        "tools": tools,
    }


def _tool_inventory() -> list[dict[str, Any]]:
    manager = getattr(mcp, "_tool_manager", None)
    registered = getattr(manager, "_tools", {}) if manager is not None else {}
    return [
        {
            "name": name,
            "source": TOOL_SOURCES.get(name, "unknown"),
            "description": getattr(tool, "description", None),
            "async": bool(getattr(tool, "is_async", False)),
        }
        for name, tool in sorted(registered.items())
    ]


def _package_version() -> str:
    try:
        return metadata.version("istanbul-mcp")
    except metadata.PackageNotFoundError:
        return "0.0.0-local"
