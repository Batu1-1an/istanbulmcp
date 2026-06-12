from __future__ import annotations

from importlib import metadata
from typing import Any

from app.core.settings import Settings
from app.core.source_cache import source_cache_snapshot
from app.mcp.server import mcp
from app.storage.db import readiness

TOOL_SOURCES = {
    "istanbul_health": "runtime",
    "istanbul_search_datasets": "ckan",
    "istanbul_get_dataset": "ckan",
    "istanbul_get_resource_schema": "ckan",
    "istanbul_query_resource": "ckan",
    "istanbul_nearby": "sqlite",
    "istanbul_bbox_search": "sqlite",
    "istanbul_parking_nearby": "ispark",
    "istanbul_metro_stations_nearby": "metro",
    "istanbul_air_quality_nearby": "air_quality",
    "istanbul_traffic_status": "traffic",
    "istanbul_mobility_nearby": "mixed_city_open_data",
    "istanbul_city_services_nearby": "ckan",
    "istanbul_transit_line_info": "iett",
    "istanbul_stops_for_line": "iett",
}


def build_status(settings: Settings) -> dict[str, Any]:
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
            },
        },
        "database": readiness(settings.database_path),
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
