from __future__ import annotations

from typing import Any

from app.connectors.ckan import CkanClient
from app.connectors.air_quality import AirQualityClient
from app.connectors.ispark import IsparkClient
from app.connectors.metro import MetroClient
from app.connectors.traffic import TrafficClient
from app.core.envelope import Freshness, Source, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_search_url, google_maps_url, parse_wkt_point
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, validate_bbox, validate_lat_lon, validate_limit, validate_radius, validate_text
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

GTFS_STOPS_RESOURCE_ID = "d1f7c258-bbc1-406f-9ab2-7a7c1797c673"
WIFI_LOCATIONS_RESOURCE_ID = "5d0a0b1e-9e56-4038-b966-7d3e7b46f882"
LIBRARY_LOCATIONS_RESOURCE_ID = "2ee4476c-9984-43de-96de-7aeda4da9aee"
CKAN_POINT_PREFETCH_LIMIT = 100


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
    ):
        self.settings = settings
        self.geo = geo_repository or GeoRepository(settings.database_path)
        self.ispark = ispark_client or IsparkClient(timeout=settings.request_timeout_seconds)
        self.metro = metro_client or MetroClient(timeout=settings.request_timeout_seconds)
        self.air_quality = air_quality_client or AirQualityClient(timeout=settings.request_timeout_seconds)
        self.traffic = traffic_client or TrafficClient(timeout=settings.request_timeout_seconds)
        self.ckan = ckan_client or CkanClient(timeout=settings.request_timeout_seconds)

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
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
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
            latest = readings[0] if readings else {}
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
        parking = await self.parking_nearby(lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit)
        metro = await self.metro_stations_nearby(lat=resolved.lat, lon=resolved.lon, radius_m=radius_m, limit=safe_limit)
        traffic = await self.traffic_status()

        public_stops: list[dict[str, Any]] = []
        air_quality_stations: list[dict[str, Any]] = []
        try:
            public_stops = await self._public_transport_stops_nearby(
                lat=resolved.lat,
                lon=resolved.lon,
                radius_m=radius_m,
                limit=safe_limit,
            )
        except Exception as exc:
            warnings.append(f"Public transport GTFS stops unavailable: {type(exc).__name__}.")
        try:
            air_quality_stations = await self._air_quality_stations_nearby_summary(
                lat=resolved.lat,
                lon=resolved.lon,
                radius_m=min(radius_m, self.settings.max_radius_m),
                limit=min(safe_limit, 3),
            )
            warnings.append("Air quality in mobility summaries includes station locations only; use istanbul_air_quality_nearby for latest readings.")
        except Exception as exc:
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
        return success_envelope(
            summary=f"Mobility options near reference point {resolved.name} within {radius_m} meters.",
            data=data,
            sources=[
                CITY_SOURCE,
                Source(name="IBB Open Data Portal - Public GTFS stops", resource_id=GTFS_STOPS_RESOURCE_ID, url="https://data.ibb.gov.tr"),
            ],
            freshness=Freshness(status="fresh", ttl_seconds=300),
            limits=[f"radius_m={radius_m}", f"limit_per_section={safe_limit}", "traffic=citywide"],
            warnings=warnings,
            next_queries=[
                "Use istanbul_parking_nearby for parking-only details.",
                "Use istanbul_parking_by_district for district-wide parking without synthetic distances.",
                "Use istanbul_stops_for_line for ordered IETT line stops.",
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
        else:
            warnings.append("Libraries require a known place with district metadata; coordinate-only queries return WiFi only.")

        return success_envelope(
            summary=f"City services near {resolved.name} within {radius_m} meters.",
            data=[
                {
                    "query": self._resolved_payload(resolved),
                    "wifi_locations": wifi,
                    "libraries": libraries,
                }
            ],
            sources=[
                Source(name="IBB Open Data Portal - WiFi locations", resource_id=WIFI_LOCATIONS_RESOURCE_ID, url="https://data.ibb.gov.tr"),
                Source(name="IBB Open Data Portal - Library locations", resource_id=LIBRARY_LOCATIONS_RESOURCE_ID, url="https://data.ibb.gov.tr"),
            ],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 24),
            limits=[f"radius_m={radius_m}", f"limit_per_section={safe_limit}", "libraries=district-level"],
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
            warnings = await self._refresh_requested(types)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("City feature sources are unavailable.", exc)
        data = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=types)
        return success_envelope(
            summary=f"{len(data)} city feature(s) found within {radius_m} meters.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=300),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}"],
            warnings=warnings,
        )

    async def bbox_search(self, *, bbox: list[float], types: list[str] | None = None, limit: int | None = None) -> dict:
        try:
            min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
            warnings = await self._refresh_requested(types)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[CITY_SOURCE])
        except Exception as exc:
            return self._source_error("City feature sources are unavailable.", exc)
        data = self.geo.bbox_search(
            min_lon=min_lon,
            min_lat=min_lat,
            max_lon=max_lon,
            max_lat=max_lat,
            limit=safe_limit,
            types=types,
        )
        return success_envelope(
            summary=f"{len(data)} city feature(s) found in bbox.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=300),
            limits=[f"limit={safe_limit}"],
            warnings=warnings,
        )

    def _validate_geo(self, lat: float, lon: float, radius_m: int, limit: int | None) -> int:
        validate_lat_lon(lat, lon)
        validate_radius(radius_m, self.settings.max_radius_m)
        return validate_limit(limit or self.settings.default_limit, self.settings.max_limit)

    async def _refresh_requested(self, types: list[str] | None) -> list[str]:
        requested = set(types or ["parking", "metro_station", "air_quality_station"])
        warnings: list[str] = []
        if "parking" in requested:
            try:
                parks = await self._parks()
                self.geo.upsert_features([self._ispark_feature(park) for park in parks if park.get("lat") and park.get("lng")])
            except Exception as exc:
                warnings.append(f"Parking source refresh failed: {type(exc).__name__}.")
        if "metro_station" in requested:
            try:
                stations = await self._metro_stations()
                self.geo.upsert_features([self._metro_feature(station) for station in stations if self._metro_coordinates(station)])
            except Exception as exc:
                warnings.append(f"Metro source refresh failed: {type(exc).__name__}.")
        if "air_quality_station" in requested:
            try:
                stations = await self._air_quality_stations()
                self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])
            except Exception as exc:
                warnings.append(f"Air quality station source refresh failed: {type(exc).__name__}.")
        if "public_transport_stop" in requested:
            try:
                stops = await self._gtfs_stops()
                self.geo.upsert_features([feature for row in stops if (feature := self._gtfs_stop_feature(row))])
            except Exception as exc:
                warnings.append(f"Public transport stop source refresh failed: {type(exc).__name__}.")
        if "wifi" in requested:
            try:
                wifi_locations = await self._wifi_locations()
                self.geo.upsert_features([feature for row in wifi_locations if (feature := self._wifi_feature(row))])
            except Exception as exc:
                warnings.append(f"WiFi source refresh failed: {type(exc).__name__}.")
        return warnings

    async def _parks(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "ispark.parks",
            ttl_seconds=self.settings.ispark_cache_ttl_seconds,
            loader=self.ispark.parks,
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

    async def _gtfs_stops(self) -> list[dict[str, Any]]:
        async def load() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=GTFS_STOPS_RESOURCE_ID, limit=CKAN_POINT_PREFETCH_LIMIT)
            return result.get("records", [])

        return await cached_source_data(
            "ckan.public_gtfs.stops",
            ttl_seconds=60 * 60 * 24,
            loader=load,
        )

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

    async def _public_transport_stops_nearby(self, *, lat: float, lon: float, radius_m: int, limit: int) -> list[dict[str, Any]]:
        stops = await self._gtfs_stops()
        self.geo.upsert_features([feature for row in stops if (feature := self._gtfs_stop_feature(row))])
        return self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=limit, types=["public_transport_stop"])

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
        lat = self._float_or_none(stop.get("stop_lat"))
        lon = self._float_or_none(stop.get("stop_lon"))
        stop_id = stop.get("stop_id")
        if lat is None or lon is None or not stop_id:
            return None
        return {
            "id": f"gtfs_stop:{stop_id}",
            "source": "gtfs",
            "feature_type": "public_transport_stop",
            "source_id": str(stop_id),
            "name": stop.get("stop_name") or str(stop_id),
            "lat": lat,
            "lon": lon,
            "properties": {
                "stop_code": stop.get("stop_code"),
                "stop_desc": stop.get("stop_desc"),
                "zone_id": stop.get("zone_id"),
                "wheelchair_boarding": stop.get("wheelchair_boarding"),
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
