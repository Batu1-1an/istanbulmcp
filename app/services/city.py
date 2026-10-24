from __future__ import annotations

import asyncio
from dataclasses import dataclass
import hashlib
from typing import Any

from app.connectors.ckan import CkanClient
from app.connectors.city_open_data import CityOpenDataClient, OpenDataLayer, OpenDataLayerError, parse_market_coordinate
from app.connectors.gtfs import (
    GTFS_DATASET_ID, GROUPED_COORDINATE_RE, ISTANBUL_GTFS_BOUNDS,
    GtfsStopsClient, GtfsStopsError, is_gtfs_stops_resource, parse_gtfs_coordinate,
)
from app.connectors.air_quality import AirQualityClient
from app.connectors.ispark import IsparkClient
from app.connectors.metro import MetroClient
from app.connectors.traffic import TrafficClient
from app.core.envelope import Freshness, FreshnessStatus, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_search_url, google_maps_url, parse_wkt_point
from app.core.settings import Settings
from app.core.source_cache import CachedSourceData, SourceLoadResult, cached_source_data, cached_source_data_with_status
from app.core.validation import (
    InputValidationError, resolve_limit, validate_bbox, validate_lat_lon, validate_radius,
    validate_text,
)
from app.services.places import ResolvedPlace, district_from_text, is_district_place, known_place_names, normalize_place, resolve_place
from app.storage.geo import GeoRepository


CITY_SOURCE = Source(
    name="IBB City APIs",
    publisher="Istanbul Metropolitan Municipality",
    url="https://api.ibb.gov.tr",
)

OPEN_DATA_SOURCE = Source(
    name="IBB Open Data Portal",
    publisher="Istanbul Metropolitan Municipality",
    url="https://data.ibb.gov.tr",
)

GTFS_SOURCE_NAME = "IBB Open Data Portal - Public GTFS stops"
OPEN_DATA_LAYER_TYPES = {"ev_charging", "taxi_stand", "market"}
OPEN_DATA_SOURCE_NAMES = {
    "ev_charging": "IBB Open Data Portal - EV charging stations",
    "taxi_stand": "IBB Open Data Portal - Taxi stands",
    "market": "IBB Open Data Portal - Weekly markets",
    "cultural_centre": "IBB Open Data Portal - Cultural centres",
}
ISTANBUL_LAYER_BOUNDS = (40.70, 41.50, 27.80, 30.20)
WIFI_LOCATIONS_RESOURCE_ID = "5d0a0b1e-9e56-4038-b966-7d3e7b46f882"
LIBRARY_LOCATIONS_RESOURCE_ID = "2ee4476c-9984-43de-96de-7aeda4da9aee"
CKAN_POINT_PREFETCH_LIMIT = 100
MOBILITY_COMPONENT_TIMEOUT_SECONDS = 5.0

@dataclass
class _CityRefresh:
    warnings: list[str]
    sources: list[Source]
    types: list[str]
    status: FreshnessStatus = "fresh"
    gtfs: CachedSourceData | None = None


class CityService:
    def __init__(
        self,
        *,
        settings: Settings,
        geo_repository: GeoRepository | None = None,
        ispark_client: IsparkClient | None = None,
        metro_client: MetroClient | None = None,
        air_quality_client: AirQualityClient | None = None,
        traffic_client: TrafficClient | None = None,
        ckan_client: CkanClient | None = None,
        gtfs_client: GtfsStopsClient | None = None,
        open_data_client: CityOpenDataClient | None = None,
    ):
        self.settings = settings
        self.geo = geo_repository or GeoRepository(settings.database_path)
        self.ispark = ispark_client or IsparkClient(timeout=settings.request_timeout_seconds)
        self.metro = metro_client or MetroClient(timeout=settings.request_timeout_seconds)
        self.air_quality = air_quality_client or AirQualityClient(timeout=settings.request_timeout_seconds)
        self.traffic = traffic_client or TrafficClient(timeout=settings.request_timeout_seconds)
        self.ckan = ckan_client or CkanClient(timeout=settings.request_timeout_seconds)
        self.gtfs = gtfs_client or GtfsStopsClient(settings=settings, ckan_client=self.ckan)
        self.open_data = open_data_client or CityOpenDataClient(settings=settings)

    async def parking_nearby(self, *, lat: float, lon: float, radius_m: int = 1000, limit: int | None = None) -> dict:
        try:
            safe_limit = self._validate_geo(lat, lon, radius_m, limit)
            parks = await self._parks()
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("Parking source is unavailable.", exc)
        self.geo.upsert_features([self._ispark_feature(park) for park in parks if park.get("lat") and park.get("lng")])
        data = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=["parking"])
        return success_envelope(
            summary=f"{len(data)} parking lot(s) found within {radius_m} meters.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=300),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}"],
            warnings=[],
        )

    async def parking_by_district(self, *, district: str, limit: int | None = None) -> dict:
        try:
            if not district or not district.strip():
                raise InputValidationError("district is required", field="district")
            district = validate_text(district, field="district", max_length=80)
            safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
            parks = await self._parks()
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("Parking source is unavailable.", exc)

        normalized_district = self._normalize_text(district)
        rows = [
            self._district_parking_row(park)
            for park in parks
            if self._normalize_text(park.get("district")) == normalized_district
        ]
        rows.sort(key=lambda row: (row["name"] or "", row["source_id"]))
        data = rows[:safe_limit]
        display_district = district.strip()
        return success_envelope(
            summary=f"{len(data)} parking lot(s) found in {display_district} district. Distances are not included because no exact location was provided.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ispark_cache_ttl_seconds),
            limits=[f"up to {safe_limit} results", "district-wide parking records", "no distance shown without an exact location"],
            warnings=["This is a district-wide parking list. Give an exact place or coordinates if you need distances."],
            next_queries=["Ask for parking near an exact place, landmark, or coordinates when distance matters."],
        )

    async def metro_stations_nearby(self, *, lat: float, lon: float, radius_m: int = 1000, limit: int | None = None) -> dict:
        try:
            safe_limit = self._validate_geo(lat, lon, radius_m, limit)
            stations = await self._metro_stations()
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("Metro source is unavailable.", exc)
        self.geo.upsert_features([self._metro_feature(station) for station in stations if self._metro_coordinates(station)])
        data = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=["metro_station"])
        return success_envelope(
            summary=f"{len(data)} metro station(s) found within {radius_m} meters.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 24),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}"],
        )

    async def air_quality_nearby(self, *, lat: float, lon: float, radius_m: int = 5000, limit: int | None = None) -> dict:
        try:
            safe_limit = self._validate_geo(lat, lon, radius_m, limit)
            stations = await self._air_quality_stations()
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("Air quality station source is unavailable.", exc)
        self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])
        nearby = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=["air_quality_station"])
        warnings = []
        for station in nearby:
            try:
                readings = await self._air_quality_readings(station["source_id"])
            except Exception as exc:
                readings = []
                warnings.append(f"Air quality readings are unavailable for {station['name']}: {type(exc).__name__}.")
            with_values = [row for row in readings if row.get("AQI") is not None or row.get("Concentration") is not None]
            latest = max(with_values or readings, key=lambda row: str(row.get("ReadTime") or ""), default={})
            station["latest_reading"] = latest
            station["latest_reading_quality"] = {
                "has_reading": bool(latest),
                "has_aqi": latest.get("AQI") is not None,
                "has_concentration": latest.get("Concentration") is not None,
                "read_time": latest.get("ReadTime"),
            }
            if latest.get("AQI") is None:
                warnings.append(f"{station['name']} has no AQI value in the latest source reading.")
        return success_envelope(
            summary=f"{len(nearby)} air quality station(s) found within {radius_m} meters.",
            data=nearby,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="unknown", ttl_seconds=900),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}"],
            warnings=warnings,
        )

    async def traffic_status(self) -> dict:
        try:
            records = await self._traffic_index_history()
        except Exception as exc:
            return self._source_error("Traffic source is unavailable.", exc)
        latest = records[0] if records else {}
        index = latest.get("TrafficIndex")
        try:
            numeric_index = int(index)
        except (TypeError, ValueError):
            numeric_index = None
        label = self._traffic_label(numeric_index)
        data = [
            {
                "traffic_index": numeric_index,
                "label": label,
                "measured_at": latest.get("TrafficIndexDate"),
                "capabilities": {
                    "supports": ["citywide traffic index"],
                    "does_not_support": ["road-level congestion", "incident details", "crash reports"],
                },
            }
        ]
        return success_envelope(
            summary=f"Istanbul traffic index is {numeric_index} ({label})." if numeric_index is not None else "Traffic source returned no index.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", source_updated_at=latest.get("TrafficIndexDate"), ttl_seconds=120),
            limits=["citywide traffic index", "no incident or road-level detail"],
            warnings=["Traffic source does not provide crash or incident details."],
        )

    async def mobility_nearby(
        self,
        *,
        place: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int = 1500,
        limit: int | None = None,
    ) -> dict:
        if place and lat is None and lon is None:
            try:
                place = validate_text(place, field="place", max_length=120)
            except InputValidationError as exc:
                return validation_error_envelope(exc, sources=[CITY_SOURCE, OPEN_DATA_SOURCE])
            resolved_place = resolve_place(place)
            if resolved_place and is_district_place(resolved_place):
                district = district_from_text(place) or resolved_place.district or resolved_place.name
                return await self._district_parking_fallback(district=district, limit=limit)
            if resolved_place is None:
                district = district_from_text(place)
                if district:
                    return await self._district_parking_fallback(district=district, limit=limit)

        try:
            resolved = self._resolve_location(place=place, lat=lat, lon=lon)
            safe_limit = self._validate_geo(resolved.lat, resolved.lon, radius_m, limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE, OPEN_DATA_SOURCE])

        warnings: list[str] = []
        gtfs_source = self._unavailable_gtfs_source()
        gtfs_cached: CachedSourceData | None = None
        air_failed = False
        parking = await self.parking_nearby(lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit)
        metro = await self.metro_stations_nearby(lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit)
        traffic = await self.traffic_status()

        public_stops: list[dict[str, Any]] = []
        air_quality_stations: list[dict[str, Any]] = []
        try:
            public_stops, gtfs_source, gtfs_cached = await self._public_transport_stops_nearby(
                lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit,
            )
            warnings.extend(self._gtfs_warnings(gtfs_cached))
        except asyncio.TimeoutError:
            warnings.append(
                f"Public transport GTFS stops timed out within the {self.settings.gtfs_stops_load_timeout_seconds:g} second load budget."
            )
        except Exception as exc:
            warnings.append(f"Public transport GTFS stops unavailable: {type(exc).__name__}.")
        try:
            air_quality_stations = await asyncio.wait_for(
                self._air_quality_stations_nearby_summary(
                    lat=resolved.lat,
                    lon=resolved.lon,
                    radius_m=min(radius_m, self.settings.max_radius_m),
                    limit=min(safe_limit, 3),
                ),
                timeout=MOBILITY_COMPONENT_TIMEOUT_SECONDS,
            )
            warnings.append("Air quality in mobility summaries includes station locations only; use istanbul_nearby(kind=air_quality) for latest readings.")
        except asyncio.TimeoutError:
            air_failed = True
            warnings.append(
                f"Air quality station source timed out after {MOBILITY_COMPONENT_TIMEOUT_SECONDS:g} seconds."
            )
        except Exception as exc:
            air_failed = True
            warnings.append(f"Air quality station source unavailable: {type(exc).__name__}.")

        for label, envelope in (("parking", parking), ("metro", metro), ("traffic", traffic)):
            warnings.extend(f"{label}: {warning}" for warning in envelope.get("warnings", []))
            if not envelope.get("ok", False):
                warnings.append(f"{label} source unavailable: {envelope.get('summary')}")

        data = [
            {
                "query": self._resolved_payload(resolved),
                "parking": parking.get("data", []) if parking.get("ok") else [],
                "metro_stations": metro.get("data", []) if metro.get("ok") else [],
                "public_transport_stops": public_stops,
                "air_quality_stations": air_quality_stations,
                "traffic": (traffic.get("data") or [{}])[0] if traffic.get("ok") else {},
            }
        ]
        components = (parking, metro, traffic)
        partial = gtfs_cached is None or air_failed or any(
            not component.get("ok") or component.get("freshness", {}).get("status") in {"broken", "unknown"}
            for component in components
        )
        stale = (gtfs_cached is not None and gtfs_cached.is_stale) or any(
            component.get("freshness", {}).get("status") == "stale" for component in components
        )
        return success_envelope(
            summary=f"Mobility options near reference point {resolved.name} within {radius_m} meters.",
            data=data,
            sources=[
                CITY_SOURCE,
                gtfs_source,
            ],
            freshness=Freshness(status="unknown" if partial else "stale" if stale else "fresh", ttl_seconds=300),
            limits=[f"radius_m={radius_m}", f"limit_per_section={safe_limit}", "traffic=citywide", *self._gtfs_limits()],
            warnings=warnings,
            next_queries=[
                "Use istanbul_nearby(kind=parking) for parking-only details.",
                "Use istanbul_nearby(kind=parking, district=...) for district-wide parking without synthetic distances.",
                "Use istanbul_transit_line(action=stops) for ordered IETT line stops.",
            ],
        )

    async def _district_parking_fallback(self, *, district: str, limit: int | None) -> dict:
        parking = await self.parking_by_district(district=district, limit=limit)
        if not parking.get("ok", False):
            return parking
        data = [
            {
                "query": {
                    "district": district,
                    "scope": "district",
                    "distance_included": False,
                },
                "parking": parking.get("data", []),
            }
        ]
        return success_envelope(
            summary=(
                f"{district} için ilçe geneli otopark kayıtlarını döndürüyorum. "
                "Mesafe göstermiyorum; bunun için net bir konum gerekir."
            ),
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.ispark_cache_ttl_seconds),
            limits=parking.get("limits", []),
            warnings=parking.get("warnings", []),
            next_queries=["Mesafe önemliyse net bir yer adı, durak, meydan veya koordinat verin."],
        )

    async def city_services_nearby(
        self,
        *,
        place: str | None = None,
        lat: float | None = None,
        lon: float | None = None,
        radius_m: int = 1500,
        limit: int | None = None,
    ) -> dict:
        try:
            resolved = self._resolve_location(place=place, lat=lat, lon=lon)
            safe_limit = self._validate_geo(resolved.lat, resolved.lon, radius_m, limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[OPEN_DATA_SOURCE])

        warnings: list[str] = []
        wifi: list[dict[str, Any]] = []
        libraries: list[dict[str, Any]] = []
        cultural_centres: list[dict[str, Any]] = []
        cultural_source: Source | None = None
        try:
            wifi = await self._wifi_nearby(lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit)
        except Exception as exc:
            warnings.append(f"WiFi locations unavailable: {type(exc).__name__}.")
        if resolved.district:
            try:
                libraries = await self._libraries_for_district(resolved.district, limit=safe_limit)
                warnings.append("Library results are district-level address records, not radius-precise coordinates.")
            except Exception as exc:
                warnings.append(f"Library locations unavailable: {type(exc).__name__}.")
            try:
                cultural_centres, cultural_source = await self._cultural_centres_for_district(
                    resolved.district, limit=safe_limit,
                )
                warnings.append("Cultural-centre results are address-search records, not verified coordinates.")
            except Exception as exc:
                warnings.append(f"Cultural-centre records unavailable: {type(exc).__name__}.")
        else:
            warnings.append("Libraries and cultural centres require a known place with district metadata; coordinate-only queries return WiFi only.")

        sources = [
            Source(name="IBB Open Data Portal - WiFi locations", resource_id=WIFI_LOCATIONS_RESOURCE_ID, url="https://data.ibb.gov.tr"),
            Source(name="IBB Open Data Portal - Library locations", resource_id=LIBRARY_LOCATIONS_RESOURCE_ID, url="https://data.ibb.gov.tr"),
        ]
        if cultural_source is not None:
            sources.append(cultural_source)
        return success_envelope(
            summary=f"City services near {resolved.name} within {radius_m} meters.",
            data=[
                {
                    "query": self._resolved_payload(resolved),
                    "wifi_locations": wifi,
                    "libraries": libraries,
                    "cultural_centres": cultural_centres,
                }
            ],
            sources=sources,
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 24),
            limits=[f"radius_m={radius_m}", f"limit_per_section={safe_limit}", "libraries=district-level", "cultural_centres=address_search"],
            warnings=warnings,
        )

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        types: list[str] | None = None,
        radius_m: int = 1000,
        limit: int | None = None,
    ) -> dict:
        try:
            safe_limit = self._validate_geo(lat, lon, radius_m, limit)
            refresh = await self._refresh_requested(types)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("City feature sources are unavailable.", exc)
        if not refresh.types:
            return self._city_refresh_error(refresh)
        data = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=refresh.types)
        return success_envelope(
            summary=f"{len(data)} city feature(s) found within {radius_m} meters.",
            data=data,
            sources=[CITY_SOURCE, *refresh.sources],
            freshness=self._city_freshness(refresh),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}", *self._city_gtfs_limits(refresh)],
            warnings=refresh.warnings,
        )

    async def bbox_search(self, *, bbox: list[float], types: list[str] | None = None, limit: int | None = None) -> dict:
        try:
            min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
            safe_limit = resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)
            refresh = await self._refresh_requested(types)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("City feature sources are unavailable.", exc)
        if not refresh.types:
            return self._city_refresh_error(refresh)
        data = self.geo.bbox_search(
            min_lon=min_lon, min_lat=min_lat, max_lon=max_lon, max_lat=max_lat,
            limit=safe_limit, types=refresh.types,
        )
        return success_envelope(
            summary=f"{len(data)} city feature(s) found in bbox.",
            data=data,
            sources=[CITY_SOURCE, *refresh.sources],
            freshness=self._city_freshness(refresh),
            limits=[f"limit={safe_limit}", *self._city_gtfs_limits(refresh)],
            warnings=refresh.warnings,
        )

    def _city_refresh_error(self, refresh: _CityRefresh) -> dict:
        return error_envelope(
            summary="Requested city feature sources are unavailable.",
            warning=" ".join(refresh.warnings),
            sources=[CITY_SOURCE, *refresh.sources],
            data=[{"error_code": "source_unavailable"}],
            limits=["Unavailable source layers are excluded; not a checked-empty result.", *self._city_gtfs_limits(refresh)],
        )

    def _city_gtfs_limits(self, refresh: _CityRefresh) -> list[str]:
        return self._gtfs_limits() if any(source.dataset_id == GTFS_DATASET_ID for source in refresh.sources) else []

    def _city_freshness(self, refresh: _CityRefresh) -> Freshness:
        if refresh.gtfs is not None and refresh.types == ["public_transport_stop"] and refresh.status != "unknown":
            return self._gtfs_freshness(refresh.gtfs)
        ttl_seconds = (
            self.settings.open_data_layers_cache_ttl_seconds
            if refresh.types and all(kind in OPEN_DATA_LAYER_TYPES for kind in refresh.types)
            else 300
        )
        return Freshness(status=refresh.status, ttl_seconds=ttl_seconds)

    def _validate_geo(self, lat: float, lon: float, radius_m: int, limit: int | None) -> int:
        validate_lat_lon(lat, lon)
        validate_radius(radius_m, self.settings.max_radius_m)
        return resolve_limit(limit, self.settings.default_limit, self.settings.max_limit)

    async def _refresh_requested(self, types: list[str] | None) -> _CityRefresh:
        # Query only layers actually refreshed/validated for this request.
        refresh = _CityRefresh([], [], list(dict.fromkeys(types or [
            "parking", "metro_station", "air_quality_station",
        ])))

        def failed(feature_type: str, label: str, exc: Exception) -> None:
            refresh.types.remove(feature_type)
            refresh.status = "unknown"
            refresh.warnings.append(f"{label} source refresh failed: {type(exc).__name__}.")

        if "parking" in refresh.types:
            try:
                parks = await self._parks()
                self.geo.upsert_features([self._ispark_feature(park) for park in parks if park.get("lat") and park.get("lng")])
            except Exception as exc:
                failed("parking", "Parking", exc)
        if "metro_station" in refresh.types:
            try:
                stations = await self._metro_stations()
                self.geo.upsert_features([self._metro_feature(station) for station in stations if self._metro_coordinates(station)])
            except Exception as exc:
                failed("metro_station", "Metro", exc)
        if "air_quality_station" in refresh.types:
            try:
                stations = await self._air_quality_stations()
                self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])
            except Exception as exc:
                failed("air_quality_station", "Air quality station", exc)
        if "public_transport_stop" in refresh.types:
            try:
                cached = await self._gtfs_stops()
                refresh.gtfs = cached
                refresh.sources.append(self._gtfs_source(cached))
                refresh.warnings.extend(self._gtfs_warnings(cached))
                if cached.is_stale and refresh.status == "fresh":
                    refresh.status = "stale"
            except Exception as exc:
                failed("public_transport_stop", "Public transport stop", exc)
                refresh.sources.append(self._unavailable_gtfs_source())
        if "wifi" in refresh.types:
            try:
                wifi_locations = await self._wifi_locations()
                self.geo.upsert_features([feature for row in wifi_locations if (feature := self._wifi_feature(row))])
            except Exception as exc:
                failed("wifi", "WiFi", exc)
        for layer in ("ev_charging", "taxi_stand", "market"):
            if layer not in refresh.types:
                continue
            try:
                payload = await self._open_data_layer(layer)
                features = [
                    feature for index, row in enumerate(payload.rows)
                    if (feature := self._open_data_feature(layer, row, index))
                ]
                if not features:
                    raise OpenDataLayerError(f"{layer} has no usable Istanbul coordinates")
                self.geo.replace_features(
                    source=f"ibb_open_data_{layer}", feature_type=layer, features=features,
                )
                refresh.sources.append(self._open_data_source(payload, accepted=len(features)))
                refresh.warnings.append(
                    f"{OPEN_DATA_SOURCE_NAMES[layer]} is a static published snapshot; not live operating status."
                )
            except Exception as exc:
                failed(layer, OPEN_DATA_SOURCE_NAMES[layer], exc)
        return refresh

    async def _parks(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "ispark.parks",
            ttl_seconds=self.settings.ispark_cache_ttl_seconds,
            loader=self.ispark.parks,
        )

    async def _open_data_layer(self, kind: str) -> OpenDataLayer:
        loader = self.open_data.market if kind == "market" else lambda: self.open_data.layer(kind)
        return await cached_source_data(
            f"ibb_open_data.{kind}.v1",
            ttl_seconds=self.settings.open_data_layers_cache_ttl_seconds,
            loader=loader,
        )

    def _open_data_source(self, payload: OpenDataLayer, *, accepted: int) -> Source:
        return Source(
            name=OPEN_DATA_SOURCE_NAMES[payload.kind],
            dataset_id=payload.dataset_id,
            resource_id=payload.resource_id,
            url=payload.source_url,
            scope="complete_static_snapshot",
            reported_total=payload.reported_total,
            received_total=payload.received_total,
            accepted_total=accepted,
            skipped_total=payload.received_total - accepted,
            last_successful_refresh_at=payload.fetched_at,
        )

    async def _metro_stations(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "metro.stations",
            ttl_seconds=self.settings.metro_cache_ttl_seconds,
            loader=self.metro.stations,
        )

    async def _air_quality_stations(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "air_quality.stations",
            ttl_seconds=self.settings.air_quality_station_cache_ttl_seconds,
            loader=self.air_quality.stations,
        )

    async def _air_quality_readings(self, station_id: str) -> list[dict[str, Any]]:
        return await cached_source_data(
            f"air_quality.readings.{station_id}",
            ttl_seconds=self.settings.air_quality_reading_cache_ttl_seconds,
            loader=lambda: self.air_quality.readings(station_id),
        )

    async def _traffic_index_history(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "traffic.index_history",
            ttl_seconds=self.settings.traffic_cache_ttl_seconds,
            loader=self.traffic.index_history,
        )

    async def _gtfs_stops(self) -> CachedSourceData:
        async def load() -> SourceLoadResult:
            deadline = asyncio.get_running_loop().time() + self.settings.gtfs_stops_load_timeout_seconds
            payload = await self.gtfs.fetch()
            resource = payload.resource
            records = payload.rows
            features = [feature for row in records if (feature := self._gtfs_stop_feature(row))]
            if not features:
                raise GtfsStopsError("GTFS stops has no usable Istanbul coordinates; preserving the previous layer")
            # A cancelled/failed/late load must not replace the committed layer.
            await asyncio.sleep(0)
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("GTFS stops exceeded its load deadline before indexing")
            self.geo.replace_features(
                source="gtfs", feature_type="public_transport_stop", features=features,
            )
            return SourceLoadResult(
                value=records,
                metadata={
                    "dataset_id": GTFS_DATASET_ID, "resource_id": resource["id"],
                    "source_updated_at": resource.get("last_modified")
                    or resource.get("metadata_modified") or resource.get("package_metadata_modified")
                    or resource.get("created"),
                    "source_url": resource.get("url") or "https://data.ibb.gov.tr",
                    "scope": payload.scope, "received_bytes": payload.received_bytes,
                    "reported_total": payload.reported_total, "received_total": len(records),
                    "accepted_total": len(features), "skipped_total": len(records) - len(features),
                    "normalized_total": sum("coordinate_normalization" in feature["properties"] for feature in features),
                },
                max_cache_age_seconds=(
                    self.settings.gtfs_stops_cache_ttl_seconds + self.settings.gtfs_stops_stale_if_error_seconds
                ),
            )

        # Cache success belongs to a specific DB and limit profile. Another app's
        # empty SQLite index must not inherit a metadata-only cache hit.
        profile = (
            str(self.geo.database_path.resolve()), getattr(self.ckan, "base_url", None),
            self.settings.gtfs_stops_max_bytes, self.settings.gtfs_stops_max_rows,
            self.settings.gtfs_stops_load_timeout_seconds, self.settings.gtfs_stops_cache_ttl_seconds,
            self.settings.gtfs_stops_stale_if_error_seconds,
        )
        key = "ckan.public_gtfs.stops.v2." + hashlib.sha256(repr(profile).encode()).hexdigest()
        return await asyncio.wait_for(
            cached_source_data_with_status(
                key, ttl_seconds=self.settings.gtfs_stops_cache_ttl_seconds,
                stale_if_error_seconds=self.settings.gtfs_stops_stale_if_error_seconds,
                loader=load,
            ),
            # Also bound waiting for a concurrent cache loader, not just its I/O.
            timeout=self.settings.gtfs_stops_load_timeout_seconds + 1,
        )

    async def _resolve_gtfs_stops_resource(self) -> dict[str, Any]:
        return await self.gtfs.resolve_stops_resource()

    def _is_gtfs_stops_resource(self, resource: dict[str, Any]) -> bool:
        return is_gtfs_stops_resource(resource)

    def _unavailable_gtfs_source(self) -> Source:
        return Source(
            name=GTFS_SOURCE_NAME, dataset_id=GTFS_DATASET_ID,
            coverage_status="unavailable", url="https://data.ibb.gov.tr",
        )

    def _gtfs_source(self, cached: CachedSourceData) -> Source:
        metadata = cached.metadata or {}
        return Source(
            name=GTFS_SOURCE_NAME,
            dataset_id=metadata.get("dataset_id", GTFS_DATASET_ID),
            resource_id=metadata.get("resource_id"),
            source_updated_at=metadata.get("source_updated_at"),
            last_successful_refresh_at=cached.refreshed_at_iso,
            coverage_status="unavailable" if cached.is_stale else "checked",
            last_checked_at=utc_now_iso() if cached.is_stale else cached.refreshed_at_iso,
            scope=metadata.get("scope"),
            reported_total=metadata.get("reported_total"),
            received_total=metadata.get("received_total"),
            accepted_total=metadata.get("accepted_total"),
            skipped_total=metadata.get("skipped_total"),
            url=metadata.get("source_url", "https://data.ibb.gov.tr"),
        )

    def _gtfs_freshness(self, cached: CachedSourceData) -> Freshness:
        return Freshness(
            status="stale" if cached.is_stale else "fresh",
            retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
            source_updated_at=(cached.metadata or {}).get("source_updated_at"),
            ttl_seconds=self.settings.gtfs_stops_cache_ttl_seconds,
        )

    def _gtfs_limits(self) -> list[str]:
        return [
            "gtfs=static_stop_locations",
            f"gtfs_max_bytes={self.settings.gtfs_stops_max_bytes}",
            f"gtfs_max_rows={self.settings.gtfs_stops_max_rows}",
            f"gtfs_load_timeout_seconds={self.settings.gtfs_stops_load_timeout_seconds:g}",
        ]

    def _gtfs_warnings(self, cached: CachedSourceData) -> list[str]:
        metadata = cached.metadata or {}
        warnings = ["GTFS stop locations are static; not live arrivals, schedules or operating status."]
        if metadata.get("normalized_total"):
            warnings.append(f"Normalized {metadata['normalized_total']} GTFS stop coordinate record(s) using the known IBB digit-grouping format.")
        if metadata.get("skipped_total"):
            warnings.append(f"Skipped {metadata['skipped_total']} GTFS stop record(s) with invalid or outside-Istanbul coordinates.")
        if cached.is_stale:
            warnings.append("GTFS source refresh failed; serving the last successful stop snapshot within its bounded stale window.")
        return warnings

    async def _wifi_locations(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=WIFI_LOCATIONS_RESOURCE_ID, limit=CKAN_POINT_PREFETCH_LIMIT)
            return result.get("records", [])

        return await cached_source_data(
            "ckan.wifi.locations",
            ttl_seconds=60 * 60 * 24,
            loader=load,
        )

    async def _library_locations(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=LIBRARY_LOCATIONS_RESOURCE_ID, limit=200)
            return result.get("records", [])

        return await cached_source_data(
            "ckan.library.locations",
            ttl_seconds=60 * 60 * 24,
            loader=load,
        )

    async def _public_transport_stops_nearby(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int,
        limit: int,
    ) -> tuple[list[dict[str, Any]], Source, CachedSourceData]:
        cached = await self._gtfs_stops()
        nearby = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=limit, types=["public_transport_stop"])
        return nearby, self._gtfs_source(cached), cached

    async def _wifi_nearby(self, *, lat: float, lon: float, radius_m: int, limit: int) -> list[dict[str, Any]]:
        locations = await self._wifi_locations()
        self.geo.upsert_features([feature for row in locations if (feature := self._wifi_feature(row))])
        return self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=limit, types=["wifi"])

    async def _air_quality_stations_nearby_summary(self, *, lat: float, lon: float, radius_m: int, limit: int) -> list[dict[str, Any]]:
        stations = await self._air_quality_stations()
        self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])
        return self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=limit, types=["air_quality_station"])

    async def _libraries_for_district(self, district: str, *, limit: int) -> list[dict[str, Any]]:
        rows = await self._library_locations()
        normalized_district = self._normalize_text(district)
        matches = []
        for row in rows:
            if self._normalize_text(row.get("Ilce Adi")) != normalized_district:
                continue
            item = {
                "name": row.get("Kutuphane Adi"),
                "district": row.get("Ilce Adi"),
                "address": row.get("Adres"),
                "phone": row.get("Telefon"),
                "working_hours": row.get("Calisma Saatleri"),
                "working_days": row.get("Calisma Gunleri"),
            }
            if maps_search_url := google_maps_search_url(item["name"], item["address"], item["district"], "İstanbul"):
                item["maps_search_url"] = maps_search_url
                item["location_precision"] = "address_search"
            matches.append(item)
        return matches[:limit]

    async def _cultural_centres_for_district(
        self, district: str, *, limit: int,
    ) -> tuple[list[dict[str, Any]], Source]:
        payload = await self._open_data_layer("cultural_centre")
        wanted = self._normalize_text(district)
        rows: list[dict[str, Any]] = []
        for row in payload.rows:
            address = self._property(row, ("ADRES", "Adres", "Address", "ADDRESS"))
            row_district = self._property(row, ("ILCE", "Ilce", "İLÇE", "District"))
            if not row_district:
                row_district = district_from_text(str(address or ""))
            if self._normalize_text(row_district) != wanted:
                continue
            name = self._property(row, ("KÜLTÜR MERKEZİ", "Kültür Merkezi", "KÜLTÜR MERKEZİ ADI", "Kültür Merkezi Adı", "AD", "Ad", "NAME", "Name"))
            if not name:
                continue
            item = {
                "name": str(name),
                "district": row_district,
                "address": address,
                "opening_hours": self._property(row, ("AÇILIŞ-KAPANIŞ SAATLERİ", "Açılış-Kapanış Saatleri", "AÇILIŞ_KAPANIŞ SAATİ", "AÇILIŞ KAPANIŞ", "Çalışma Saatleri")),
                "child_unit": self._property(row, ("ÇOCUK BİRİMİ", "Çocuk Birimi", "ÇOCUK BİRİMİ VAR MI")),
                "location_precision": "address_search",
            }
            if maps_search_url := google_maps_search_url(name, address, row_district, "İstanbul"):
                item["maps_search_url"] = maps_search_url
            rows.append(item)
        return rows[:limit], self._open_data_source(payload, accepted=len(rows))

    def _ispark_feature(self, park: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"ispark:{park['parkID']}",
            "source": "ispark",
            "feature_type": "parking",
            "source_id": str(park["parkID"]),
            "name": park.get("parkName") or str(park["parkID"]),
            "lat": float(park["lat"]),
            "lon": float(park["lng"]),
            "district": park.get("district"),
            "properties": {
                "capacity": park.get("capacity"),
                "empty_capacity": park.get("emptyCapacity"),
                "work_hours": park.get("workHours"),
                "park_type": park.get("parkType"),
                "is_open": park.get("isOpen"),
            },
        }

    def _district_parking_row(self, park: dict[str, Any]) -> dict[str, Any]:
        row = {
            "source": "ispark",
            "source_id": str(park.get("parkID")),
            "name": park.get("parkName") or str(park.get("parkID")),
            "district": park.get("district"),
            "lat": self._float_or_none(park.get("lat")),
            "lon": self._float_or_none(park.get("lng")),
            "capacity": park.get("capacity"),
            "empty_capacity": park.get("emptyCapacity"),
            "work_hours": park.get("workHours"),
            "park_type": park.get("parkType"),
            "is_open": park.get("isOpen"),
        }
        if maps_url := google_maps_url(row.get("lat"), row.get("lon")):
            row["maps_url"] = maps_url
        return row

    def _metro_coordinates(self, station: dict[str, Any]) -> tuple[float, float] | None:
        detail = station.get("DetailInfo") or {}
        lat = detail.get("Latitude")
        lon = detail.get("Longitude")
        if lat is None or lon is None:
            return None
        return float(lat), float(lon)

    def _metro_feature(self, station: dict[str, Any]) -> dict[str, Any]:
        lat, lon = self._metro_coordinates(station) or (0.0, 0.0)
        return {
            "id": f"metro:{station['Id']}",
            "source": "metro",
            "feature_type": "metro_station",
            "source_id": str(station["Id"]),
            "name": station.get("Description") or station.get("Name") or str(station["Id"]),
            "lat": lat,
            "lon": lon,
            "properties": {
                "line_id": station.get("LineId"),
                "line_name": station.get("LineName"),
                "order": station.get("Order"),
            },
        }

    def _aq_feature(self, station: dict[str, Any]) -> dict[str, Any]:
        lat, lon = parse_wkt_point(station.get("Location")) or (0.0, 0.0)
        return {
            "id": f"air_quality:{station['Id']}",
            "source": "air_quality",
            "feature_type": "air_quality_station",
            "source_id": station["Id"],
            "name": station.get("Name") or station["Id"],
            "lat": lat,
            "lon": lon,
            "properties": {
                "address": station.get("Adress"),
            },
        }

    def _gtfs_stop_feature(self, stop: dict[str, Any]) -> dict[str, Any] | None:
        lat = parse_gtfs_coordinate(stop.get("stop_lat"), axis="lat")
        lon = parse_gtfs_coordinate(stop.get("stop_lon"), axis="lon")
        raw_id = stop.get("stop_id")
        stop_id = "" if raw_id is None else str(raw_id).strip()
        if lat is None or lon is None or not stop_id:
            return None
        properties = {
            "stop_code": stop.get("stop_code"), "stop_desc": stop.get("stop_desc"),
            "zone_id": stop.get("zone_id"), "wheelchair_boarding": stop.get("wheelchair_boarding"),
        }
        if any(GROUPED_COORDINATE_RE.fullmatch(str(stop.get(key) or "").strip()) for key in ("stop_lat", "stop_lon")):
            properties["coordinate_normalization"] = "ibb_grouped_decimal"
        return {
            "id": f"gtfs_stop:{stop_id}", "source": "gtfs", "feature_type": "public_transport_stop",
            "source_id": stop_id, "name": stop.get("stop_name") or stop_id,
            "lat": lat, "lon": lon, "properties": properties,
        }

    @staticmethod
    def _property(props: dict[str, Any], names: tuple[str, ...]) -> Any:
        folded = {str(key).casefold(): value for key, value in props.items()}
        for name in names:
            value = props.get(name, folded.get(name.casefold()))
            if value is not None and str(value).strip() != "":
                return value
        return None

    @staticmethod
    def _layer_coordinate(lat: Any, lon: Any) -> tuple[float, float] | None:
        try:
            latitude, longitude = float(lat), float(lon)
        except (TypeError, ValueError):
            return None
        if not (ISTANBUL_LAYER_BOUNDS[0] <= latitude <= ISTANBUL_LAYER_BOUNDS[1]
                and ISTANBUL_LAYER_BOUNDS[2] <= longitude <= ISTANBUL_LAYER_BOUNDS[3]):
            return None
        return latitude, longitude

    @classmethod
    def _geojson_point(cls, feature: dict[str, Any]) -> tuple[float, float] | None:
        props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
        lat = cls._property(props, ("LATITUDE", "Latitude", "lat", "ENLEM", "Enlem"))
        lon = cls._property(props, ("LONGITUDE", "Longitude", "lon", "LNG", "BOYLAM", "Boylam"))
        if lat is not None and lon is not None:
            point = cls._layer_coordinate(lat, lon)
            if point is not None:
                return point
        geometry = feature.get("geometry") if isinstance(feature.get("geometry"), dict) else {}
        coordinates = geometry.get("coordinates")
        if geometry.get("type") == "Point" and isinstance(coordinates, list) and len(coordinates) >= 2:
            return cls._layer_coordinate(coordinates[1], coordinates[0])
        return None

    def _open_data_feature(self, kind: str, row: dict[str, Any], index: int) -> dict[str, Any] | None:
        if kind == "market":
            return self._market_feature(row, index)
        point = self._geojson_point(row)
        if point is None:
            return None
        props = row.get("properties") if isinstance(row.get("properties"), dict) else {}
        if kind == "ev_charging":
            name = self._property(props, ("AD", "Ad", "NAME", "Name", "İSTASYON_ADI", "Istasyon Adi"))
            source_id = self._property(props, ("ID", "Id", "ISTASYON_NO", "İstasyon No", "Istasyon No")) or str(index)
            details = {
                "address": self._property(props, ("ADRES", "Adres", "ADDRESS", "Address")),
                "operator": self._property(props, ("İŞLETİCİ", "Isletmeci", "OPERATOR", "Operator", "SARJ_ISLETMECISI", "Şarj İşletmecisi")),
                "license": self._property(props, ("LISANS", "Lisans", "LICENSE", "License")),
                "station_type": self._property(props, ("TIP", "Tip", "TYPE", "Type")),
            }
            feature_type = "ev_charging"
        elif kind == "taxi_stand":
            name = self._property(props, ("DURAK_ADI", "Durak Adi", "AD", "Ad", "NAME", "Name"))
            source_id = self._property(props, ("ID", "Id", "DURAK_NO", "Durak No", "DURAK_ID", "Durak Id")) or str(index)
            details = {
                "address": self._property(props, ("ADRES", "Adres", "ADDRESS", "Address")),
                "district": self._property(props, ("ILCE", "Ilce", "İLÇE", "District")),
            }
            feature_type = "taxi_stand"
        else:
            return None
        lat, lon = point
        return {
            "id": f"{feature_type}:{source_id}",
            "source": f"ibb_open_data_{feature_type}",
            "feature_type": feature_type,
            "source_id": str(source_id),
            "name": str(name or f"{feature_type} {source_id}"),
            "lat": lat,
            "lon": lon,
            "district": details.get("district"),
            "properties": {key: value for key, value in details.items() if value not in (None, "")},
        }

    def _market_feature(self, row: dict[str, Any], index: int) -> dict[str, Any] | None:
        point = parse_market_coordinate(row.get("Koordinat"))
        if point is None:
            return None
        name = str(row.get("Pazar Adi") or "").strip()
        if not name:
            return None
        lat, lon = point
        source_id = str(row.get("_id") or index)
        address = ", ".join(str(value).strip() for value in (row.get("Cadde"), row.get("Sokak")) if value)
        return {
            "id": f"market:{source_id}",
            "source": "ibb_open_data_market",
            "feature_type": "market",
            "source_id": source_id,
            "name": name,
            "lat": lat,
            "lon": lon,
            "district": row.get("Ilce"),
            "neighborhood": row.get("Mahalle"),
            "properties": {
                "day": row.get("Gun"),
                "market_type": row.get("Pazar Tipi"),
                "address": address or None,
            },
        }

    def _wifi_feature(self, row: dict[str, Any]) -> dict[str, Any] | None:
        lat = self._float_or_none(row.get("latitude"))
        lon = self._float_or_none(row.get("longitude"))
        code = row.get("location_code") or row.get("_id")
        if lat is None or lon is None or lat == 0.0 or lon == 0.0 or not code:
            return None
        return {
            "id": f"wifi:{code}",
            "source": "ibb_wifi",
            "feature_type": "wifi",
            "source_id": str(code),
            "name": row.get("location") or str(code),
            "lat": lat,
            "lon": lon,
            "properties": {
                "location_group": row.get("location_group"),
                "location_type": row.get("location_type"),
                "location_code": row.get("location_code"),
            },
        }

    def _traffic_label(self, index: int | None) -> str:
        if index is None:
            return "unknown"
        if index < 30:
            return "low"
        if index < 60:
            return "moderate"
        return "high"

    def _resolve_location(self, *, place: str | None, lat: float | None, lon: float | None) -> ResolvedPlace:
        if place and (lat is not None or lon is not None):
            raise InputValidationError("Provide either place or lat/lon, not both.", field="place")
        if place:
            place = validate_text(place, field="place", max_length=120)
            resolved = resolve_place(place)
            if resolved is None:
                raise InputValidationError(
                    f"Unknown place. Known examples: {', '.join(known_place_names()[:8])}",
                    field="place",
                )
            validate_lat_lon(resolved.lat, resolved.lon)
            return resolved
        if lat is None or lon is None:
            raise InputValidationError("Provide place or both lat and lon.", field="place")
        validate_lat_lon(lat, lon)
        return ResolvedPlace("coordinates", "coordinates", float(lat), float(lon), confidence="coordinate")

    def _resolved_payload(self, resolved: ResolvedPlace) -> dict[str, Any]:
        return {
            "name": resolved.name,
            "lat": resolved.lat,
            "lon": resolved.lon,
            "district": resolved.district,
            "neighborhood": resolved.neighborhood,
            "confidence": resolved.confidence,
        }

    def _float_or_none(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _normalize_text(self, value: Any) -> str:
        return normalize_place(str(value or ""))

    def _source_error(self, summary: str, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary=summary,
            warning=f"IBB source request failed: {type(exc).__name__}",
            sources=[CITY_SOURCE],
            exception=exc,
        )
