from __future__ import annotations

from typing import Literal

from mcp.server import MCPServer

from app.mcp.registry import READ_ONLY, TOOL_TITLES, create_mcp_server
from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import get_settings
from app.core.error_responses import validation_error_envelope
from app.core.validation import InputValidationError, validate_lat_lon, validate_limit, validate_radius
from app.services.city import CityService
from app.services.catalog import CatalogService
from app.services.datastore_sql import DatastoreSqlService
from app.services.iski import IskiService
from app.services.neighborhood import NeighborhoodService
from app.services.pharmacy import PharmacyService
from app.services.istanbulkart import IstanbulkartService
from app.services.social_facilities import SocialFacilitiesService
from app.services.disruptions import TransportDisruptionService
from app.services.ferry import FerryScheduleService
from app.services.transit import TransitService
from app.services.gtfs_schedule import GtfsScheduleService
from app.services.metro_accessibility import MetroAccessibilityService
from app.storage.db import public_readiness, readiness

settings = get_settings()


def istanbul_health() -> dict:
    """Return Istanbul MCP service readiness."""
    settings = get_settings()
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


async def istanbul_get_dataset(dataset_id: str) -> dict:
    """Return metadata and resources for one IBB dataset."""
    return await CatalogService(settings=get_settings()).get_dataset(dataset_id)


async def istanbul_get_resource_schema(resource_id: str) -> dict:
    """Return DataStore field schema for a resource."""
    return await CatalogService(settings=get_settings()).get_resource_schema(resource_id)


async def istanbul_query_resource(
    resource_id: str,
    filters: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Query IBB CKAN DataStore records with guarded filters and limits.

    API reference: https://docs.ckan.org/en/latest/maintaining/datastore.html
    Uses datastore_search, not SQL; field names come from the resource schema.
    """
    return await CatalogService(settings=get_settings()).query_resource(
        resource_id=resource_id,
        filters=filters,
        limit=limit,
    )


async def istanbul_nearby(
    lat: float | None = None,
    lon: float | None = None,
    types: list[str] | None = None,
    radius_m: int | None = None,
    limit: int | None = None,
    kind: Literal["city_feature", "parking", "pharmacy", "istanbulkart",
                  "social_facility", "metro_station", "air_quality", "water_fault"] = "city_feature",
    district: str | None = None,
    bbox: list[float] | None = None,
) -> dict:
    """Find city services by kind and coordinates, or parking/pharmacy by district.

    bbox and types apply only to city_feature (parking, metro_station,
    air_quality_station, public_transport_stop, wifi). air_quality includes latest
    readings; city_feature has station locations only. District lists have no
    distances. Pharmacy records include name, district, address, phone, map links,
    provenance and freshness; maps_search_url is address search, not a verified pin.
    Pharmacy duty-end times are not guaranteed. Card/social locations are static,
    not live operating status.
    """
    settings = get_settings()
    try:
        if kind not in {"city_feature", "parking", "pharmacy", "istanbulkart",
                        "social_facility", "metro_station", "air_quality", "water_fault"}:
            raise InputValidationError("Unsupported nearby kind", field="kind")
        if limit is not None:
            validate_limit(limit, settings.max_limit)
        if types is not None:
            if kind != "city_feature" or not types or len(types) > 5 or any(
                value not in {"parking", "metro_station", "air_quality_station",
                              "public_transport_stop", "wifi"} for value in types
            ):
                raise InputValidationError("types is only for supported city_feature types", field="types")
        if district is not None:
            if kind not in {"parking", "pharmacy"}:
                raise InputValidationError("district supports parking or pharmacy only", field="district")
            if lat is not None or lon is not None or bbox is not None or radius_m is not None or types is not None:
                raise InputValidationError("district cannot be mixed with coordinates, bbox, radius_m or types", field="district")
            if kind == "parking":
                return await istanbul_parking_by_district(district=district, limit=limit)
            return await istanbul_nobetci_eczane_by_district(district=district, limit=limit)
        if bbox is not None:
            if kind != "city_feature" or lat is not None or lon is not None or radius_m is not None:
                raise InputValidationError("bbox requires city_feature without coordinates or radius_m", field="bbox")
            return await istanbul_bbox_search(bbox=bbox, types=types, limit=limit)
        if lat is None or lon is None:
            raise InputValidationError("Provide both lat and lon, or supported district/bbox", field="lat")
        validate_lat_lon(lat, lon)
        radius = radius_m if radius_m is not None else {
            "istanbulkart": 2000, "social_facility": 2000, "air_quality": 5000,
        }.get(kind, 1000)
        validate_radius(radius, settings.max_radius_m)
    except InputValidationError as exc:
        return validation_error_envelope(exc)

    handlers = {
        "parking": istanbul_parking_nearby,
        "pharmacy": istanbul_nobetci_eczane_nearby,
        "istanbulkart": istanbul_istanbulkart_centers_nearby,
        "social_facility": istanbul_sosyal_tesis_nearby,
        "metro_station": istanbul_metro_stations_nearby,
        "air_quality": istanbul_air_quality_nearby,
        "water_fault": istanbul_iski_nearby_faults,
    }
    if kind in handlers:
        return await handlers[kind](lat=lat, lon=lon, radius_m=radius, limit=limit)
    return await CityService(settings=settings).nearby(
        lat=lat, lon=lon, types=types, radius_m=radius, limit=limit,
    )


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


async def istanbul_parking_by_district(
    district: str,
    limit: int | None = None,
) -> dict:
    """List ISPark parking lots by source district without synthetic distance calculations."""
    return await CityService(settings=get_settings()).parking_by_district(
        district=district,
        limit=limit,
    )


async def istanbul_nobetci_eczane_nearby(
    lat: float,
    lon: float,
    radius_m: int = 1000,
    limit: int | None = None,
) -> dict:
    """Find current on-duty pharmacies from the İBB roster near coordinates.

    Returns name, district, address, phone, map links, provenance and freshness.
    maps_search_url is address search, not a verified pin. Duty-end times are
    not guaranteed; this is not a general pharmacy directory or opening-hours API.
    """
    return await PharmacyService(settings=get_settings()).nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


async def istanbul_nobetci_eczane_by_district(
    district: str,
    limit: int | None = None,
) -> dict:
    """List current on-duty pharmacies in a district from the İBB roster.

    Returns name, district, address, phone, map links, provenance and freshness.
    No proximity ordering or duty-end guarantee. maps_search_url is an address
    search, not a verified pin. This is not a general pharmacy catalog.
    """
    return await PharmacyService(settings=get_settings()).by_district(
        district=district,
        limit=limit,
    )


async def istanbul_istanbulkart_centers_nearby(
    lat: float,
    lon: float,
    radius_m: int = 2000,
    limit: int | None = None,
) -> dict:
    """Find official İstanbulkart filling centers; annual/static locations, not live terminal status."""
    return await IstanbulkartService(settings=get_settings()).nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


async def istanbul_sosyal_tesis_nearby(
    lat: float,
    lon: float,
    radius_m: int = 2000,
    limit: int | None = None,
) -> dict:
    """Find official İstanbul social-facility locations; read-only location links, not live operating status."""
    return await SocialFacilitiesService(settings=get_settings()).nearby(
        lat=lat,
        lon=lon,
        radius_m=radius_m,
        limit=limit,
    )


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


async def istanbul_traffic_status() -> dict:
    """Return Istanbul citywide traffic index."""
    return await CityService(settings=get_settings()).traffic_status()


async def istanbul_iski_active_faults(
    district: str | None = None,
    limit: int | None = None,
) -> dict:
    """List active ISKI water faults, optionally filtered by district."""
    return await IskiService(settings=get_settings()).active_faults(
        district=district,
        limit=limit,
    )


async def istanbul_iski_fault_by_number(fault_number: str) -> dict:
    """Return one active ISKI water fault by fault number."""
    return await IskiService(settings=get_settings()).fault_by_number(fault_number)


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


async def istanbul_transit_line_info(line_code: str) -> dict:
    """Return basic IETT line information."""
    return await TransitService(settings=get_settings()).line_info(line_code)


async def istanbul_stops_for_line(line_code: str) -> dict:
    """Return ordered IETT stops for a line."""
    return await TransitService(settings=get_settings()).stops_for_line(line_code)


async def istanbul_transit_disruptions(line_code: str | None = None, limit: int | None = None) -> dict:
    """Return current IETT disruptions, optionally filtered by line."""
    return await TransitService(settings=get_settings()).disruptions(line_code=line_code, limit=limit)


async def istanbul_transport_disruptions(
    mode: str | None = None,
    operator: str | None = None,
    line: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return current official disruptions and service announcements across supported transport operators."""
    return await TransportDisruptionService(settings=get_settings()).disruptions(
        mode=mode,
        operator=operator,
        line=line,
        limit=limit,
    )


async def istanbul_ferry_schedules(route: str, limit: int | None = None) -> dict:
    """Return published Şehir Hatları ferry timetable rows, not live departure or ETA."""
    return await FerryScheduleService(settings=get_settings()).schedules(route=route, limit=limit)


def register_ferry_schedule_tool(server: MCPServer, enabled: bool) -> None:
    """Opt in only after verifying timetable access from the deployment.

    Direct requests in the 2026-10-19 check received HTTP 403 challenges.
    A relay configured for cancellation notices does not serve timetables.
    """
    if enabled:
        server.add_tool(istanbul_ferry_schedules, title=TOOL_TITLES["istanbul_ferry_schedules"], annotations=READ_ONLY)


async def istanbul_next_departures(
    stop_id: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    line: str | None = None,
    at: str | None = None,
    radius_m: int = 500,
    limit: int | None = None,
) -> dict:
    """Return published GTFS departures for a stop or up to five nearby stops.

    at is an ISO datetime with a UTC offset; omitted means now in Europe/Istanbul.
    The search covers 24 hours. stop_id and coordinates are mutually exclusive.
    line matches the published route short name. Times are scheduled, never live
    ETA, delays or proof of service. Outside-calendar queries are unavailable.
    """
    return await GtfsScheduleService(get_settings()).next_departures(
        stop_id=stop_id, lat=lat, lon=lon, line=line, at=at,
        radius_m=radius_m, limit=limit,
    )


async def istanbul_planned_departures(line_code: str, limit: int | None = None) -> dict:
    """Return planned main-terminal IETT departures, not intermediate-stop ETA."""
    return await TransitService(settings=get_settings()).planned_departures(line_code=line_code, limit=limit)


async def istanbul_metro_accessibility_status(
    line: str | None = None,
    station: str | None = None,
    equipment_type: str | None = None,
    limit: int | None = None,
) -> dict:
    """Return official Metro İstanbul equipment/total counts and current equipment fault details, optionally filtered by line, station, or equipment type. This is not an end-to-end accessibility guarantee."""
    return await MetroAccessibilityService(settings=get_settings()).status(
        line=line,
        station=station,
        equipment_type=equipment_type,
        limit=limit,
    )


async def istanbul_water_status(
    kind: Literal["faults", "dams"] = "faults",
    district: str | None = None,
    fault_number: str | None = None,
    dam_name: str | None = None,
    min_occupancy: float | None = None,
    limit: int | None = None,
) -> dict:
    """Get ISKI active faults (district or fault_number) or dam occupancy.

    Dam filters apply only to dams; fault_number is exclusive with district.
    Nearby faults are provided by istanbul_nearby(kind="water_fault"). Results
    carry fallback freshness and approximate fault locations; no restoration guarantee.
    """
    try:
        if kind == "faults":
            if dam_name is not None or min_occupancy is not None:
                raise InputValidationError("Dam filters require kind=dams", field="kind")
            if fault_number is not None:
                if district is not None or limit is not None:
                    raise InputValidationError("fault_number cannot be mixed with district or limit", field="fault_number")
                return await istanbul_iski_fault_by_number(fault_number)
            return await istanbul_iski_active_faults(district=district, limit=limit)
        if kind == "dams":
            if district is not None or fault_number is not None:
                raise InputValidationError("Fault filters require kind=faults", field="kind")
            return await istanbul_iski_dam_occupancy(
                dam_name=dam_name, min_occupancy=min_occupancy, limit=limit,
            )
        raise InputValidationError("kind must be faults or dams", field="kind")
    except InputValidationError as exc:
        return validation_error_envelope(exc)


async def istanbul_transit_line(
    line_code: str,
    action: Literal["info", "stops", "departures"] = "info",
    limit: int | None = None,
) -> dict:
    """Get IETT line info, ordered stops or planned main-terminal departures.

    limit applies only to departures. This is not live intermediate-stop ETA.
    Cross-operator service notices are provided by istanbul_transport_disruptions.
    """
    try:
        if action != "departures" and limit is not None:
            raise InputValidationError("limit is only supported for departures", field="limit")
        if action == "info":
            return await istanbul_transit_line_info(line_code)
        if action == "stops":
            return await istanbul_stops_for_line(line_code)
        if action == "departures":
            return await istanbul_planned_departures(line_code=line_code, limit=limit)
        raise InputValidationError("Unsupported transit action", field="action")
    except InputValidationError as exc:
        return validation_error_envelope(exc)


async def istanbul_datastore_query(
    resource_id: str, sql: str, limit: int | None = None,
) -> dict:
    """Run a bounded SELECT over records from one allowlisted CKAN resource.

    SQLite dialect: use table records and published column names. GROUP BY and
    aggregates are supported; no writes, arbitrary functions or application DB.
    A complete bounded capture is required, never partial counts. The server
    enforces an outer result limit (default 20, max 100) even if SQL omits LIMIT.
    Only resources configured in CKAN_SQL_ALLOWED_RESOURCE_IDS are available.
    Local query syntax and bounds: https://github.com/Batu1-1an/istanbulmcp/blob/main/docs/datastore-sql.md
    Source API: https://docs.ckan.org/en/latest/maintaining/datastore.html
    """
    return await DatastoreSqlService(settings=get_settings()).query(
        resource_id=resource_id, sql=sql, limit=limit,
    )


# Compatibility singleton for local callers. Each HTTP app gets its own server
# and single-use StreamableHTTPSessionManager in create_app().
mcp = create_mcp_server(settings)
