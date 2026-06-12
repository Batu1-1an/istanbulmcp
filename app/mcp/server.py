from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import get_settings
from app.services.city import CityService
from app.services.catalog import CatalogService
from app.services.transit import TransitService
from app.storage.db import readiness

settings = get_settings()

mcp = FastMCP(
    "istanbul-mcp",
    host=settings.host,
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def istanbul_health() -> dict:
    """Return Istanbul MCP service readiness."""
    db_status = readiness(settings.database_path)
    return success_envelope(
        summary="Istanbul MCP is ready.",
        data=[db_status],
        sources=[
            Source(
                name="Istanbul MCP local runtime",
                publisher="Istanbul MCP",
                license=None,
                url=None,
            )
        ],
        freshness=Freshness(status="fresh", ttl_seconds=30),
        limits=[
            f"default_limit={settings.default_limit}",
            f"max_limit={settings.max_limit}",
            f"max_radius_m={settings.max_radius_m}",
        ],
    )


@mcp.tool()
async def istanbul_search_datasets(
    query: str,
    formats: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Search the IBB open data catalog."""
    return await CatalogService(settings=get_settings()).search_datasets(
        query=query,
        formats=formats,
        limit=limit,
    )


@mcp.tool()
async def istanbul_get_dataset(dataset_id: str) -> dict:
    """Return metadata and resources for one IBB dataset."""
    return await CatalogService(settings=get_settings()).get_dataset(dataset_id)


@mcp.tool()
async def istanbul_get_resource_schema(resource_id: str) -> dict:
    """Return DataStore field schema for a resource."""
    return await CatalogService(settings=get_settings()).get_resource_schema(resource_id)


@mcp.tool()
async def istanbul_query_resource(
    resource_id: str,
    filters: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Query a CKAN DataStore resource with guarded filters and limits."""
    return await CatalogService(settings=get_settings()).query_resource(
        resource_id=resource_id,
        filters=filters,
        limit=limit,
    )


@mcp.tool()
async def istanbul_nearby(
    lat: float,
    lon: float,
    types: list[str] | None = None,
    radius_m: int = 1000,
    limit: int | None = None,
) -> dict:
    """Find nearby Istanbul city features by coordinate."""
    return await CityService(settings=get_settings()).nearby(
        lat=lat,
        lon=lon,
        types=types,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_bbox_search(
    bbox: list[float],
    types: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Find Istanbul city features inside a bbox."""
    return await CityService(settings=get_settings()).bbox_search(
        bbox=bbox,
        types=types,
        limit=limit,
    )


@mcp.tool()
async def istanbul_parking_nearby(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int | None = None,
) -> dict:
    """Find nearby ISPark parking lots."""
    return await CityService(settings=get_settings()).parking_nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_metro_stations_nearby(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int | None = None,
) -> dict:
    """Find nearby Metro Istanbul stations."""
    return await CityService(settings=get_settings()).metro_stations_nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_air_quality_nearby(
    lat: float,
    lon: float,
    radius_m: int = 5000,
    limit: int | None = None,
) -> dict:
    """Find nearby air quality stations and latest readings."""
    return await CityService(settings=get_settings()).air_quality_nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_traffic_status() -> dict:
    """Return Istanbul citywide traffic index."""
    return await CityService(settings=get_settings()).traffic_status()


@mcp.tool()
async def istanbul_transit_line_info(line_code: str) -> dict:
    """Return basic IETT line information."""
    return await TransitService(settings=get_settings()).line_info(line_code)


@mcp.tool()
async def istanbul_stops_for_line(line_code: str) -> dict:
    """Return ordered IETT stops for a line."""
    return await TransitService(settings=get_settings()).stops_for_line(line_code)
