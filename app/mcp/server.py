from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import get_settings
from app.services.city import CityService
from app.services.catalog import CatalogService
from app.services.iski import IskiService
from app.services.neighborhood import NeighborhoodService
from app.services.transit import TransitService
from app.storage.db import public_readiness, readiness

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
    db_status = public_readiness(readiness(settings.database_path))
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
async def istanbul_parking_by_district(
    district: str,
    limit: int | None = None,
) -> dict:
    """List ISPark parking lots by source district without synthetic distance calculations."""
    return await CityService(settings=get_settings()).parking_by_district(
        district=district,
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
async def istanbul_iski_active_faults(
    district: str | None = None,
    limit: int | None = None,
) -> dict:
    """List active ISKI water faults, optionally filtered by district."""
    return await IskiService(settings=get_settings()).active_faults(
        district=district,
        limit=limit,
    )


@mcp.tool()
async def istanbul_iski_fault_by_number(fault_number: str) -> dict:
    """Return one active ISKI water fault by fault number."""
    return await IskiService(settings=get_settings()).fault_by_number(fault_number)


@mcp.tool()
async def istanbul_iski_nearby_faults(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int | None = None,
) -> dict:
    """Find active ISKI water faults near a coordinate."""
    return await IskiService(settings=get_settings()).nearby_faults(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_iski_dam_occupancy(
    dam_name: str | None = None,
    min_occupancy: float | None = None,
    limit: int | None = None,
) -> dict:
    """Return live ISKI dam occupancy records."""
    return await IskiService(settings=get_settings()).dam_occupancy(
        dam_name=dam_name,
        min_occupancy=min_occupancy,
        limit=limit,
    )


@mcp.tool()
async def istanbul_mobility_nearby(
    place: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 1500,
    limit: int | None = None,
) -> dict:
    """Summarize nearby mobility options for a known Istanbul place or coordinate."""
    return await CityService(settings=get_settings()).mobility_nearby(
        place=place,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_city_services_nearby(
    place: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    radius_m: int = 1500,
    limit: int | None = None,
) -> dict:
    """Summarize nearby WiFi and district-level library services."""
    return await CityService(settings=get_settings()).city_services_nearby(
        place=place,
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


@mcp.tool()
async def istanbul_neighborhood_profile(
    district: str,
    neighborhood: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return a joined neighborhood profile from social, building, and earthquake scenario records."""
    return await NeighborhoodService(settings=get_settings()).profile(
        district=district,
        neighborhood=neighborhood,
        limit=limit,
    )


@mcp.tool()
async def istanbul_transit_line_info(line_code: str) -> dict:
    """Return basic IETT line information."""
    return await TransitService(settings=get_settings()).line_info(line_code)


@mcp.tool()
async def istanbul_stops_for_line(line_code: str) -> dict:
    """Return ordered IETT stops for a line."""
    return await TransitService(settings=get_settings()).stops_for_line(line_code)


@mcp.tool()
async def istanbul_transit_disruptions(line_code: str | None = None, limit: int | None = None) -> dict:
    """Return current IETT disruptions, optionally filtered by line."""
    return await TransitService(settings=get_settings()).disruptions(line_code=line_code, limit=limit)


@mcp.tool()
async def istanbul_planned_departures(line_code: str, limit: int | None = None) -> dict:
    """Return planned main-terminal IETT departures, not intermediate-stop ETA."""
    return await TransitService(settings=get_settings()).planned_departures(line_code=line_code, limit=limit)
