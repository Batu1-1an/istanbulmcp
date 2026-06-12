from __future__ import annotations

from typing import Any

from app.connectors.air_quality import AirQualityClient
from app.connectors.ispark import IsparkClient
from app.connectors.metro import MetroClient
from app.connectors.traffic import TrafficClient
from app.core.envelope import Freshness, Source, success_envelope
from app.core.geo import parse_wkt_point
from app.core.settings import Settings
from app.core.validation import validate_bbox, validate_lat_lon, validate_limit, validate_radius
from app.storage.geo import GeoRepository


CITY_SOURCE = Source(
    name="IBB City APIs",
    publisher="Istanbul Metropolitan Municipality",
    url="https://api.ibb.gov.tr",
)


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
    ):
        self.settings = settings
        self.geo = geo_repository or GeoRepository(settings.database_path)
        self.ispark = ispark_client or IsparkClient(timeout=settings.request_timeout_seconds)
        self.metro = metro_client or MetroClient(timeout=settings.request_timeout_seconds)
        self.air_quality = air_quality_client or AirQualityClient(timeout=settings.request_timeout_seconds)
        self.traffic = traffic_client or TrafficClient(timeout=settings.request_timeout_seconds)

    async def parking_nearby(self, *, lat: float, lon: float, radius_m: int = 1000, limit: int | None = None) -> dict:
        safe_limit = self._validate_geo(lat, lon, radius_m, limit)
        parks = await self.ispark.parks()
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

    async def metro_stations_nearby(self, *, lat: float, lon: float, radius_m: int = 1000, limit: int | None = None) -> dict:
        safe_limit = self._validate_geo(lat, lon, radius_m, limit)
        stations = await self.metro.stations()
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
        safe_limit = self._validate_geo(lat, lon, radius_m, limit)
        stations = await self.air_quality.stations()
        self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])
        nearby = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=["air_quality_station"])
        warnings = []
        for station in nearby:
            readings = await self.air_quality.readings(station["source_id"])
            latest = readings[0] if readings else {}
            station["latest_reading"] = latest
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
        records = await self.traffic.index_history()
        latest = records[0] if records else {}
        index = latest.get("TrafficIndex")
        try:
            numeric_index = int(index)
        except (TypeError, ValueError):
            numeric_index = None
        label = self._traffic_label(numeric_index)
        data = [{"traffic_index": numeric_index, "label": label, "measured_at": latest.get("TrafficIndexDate")}]
        return success_envelope(
            summary=f"Istanbul traffic index is {numeric_index} ({label})." if numeric_index is not None else "Traffic source returned no index.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", source_updated_at=latest.get("TrafficIndexDate"), ttl_seconds=120),
            limits=["citywide traffic index", "no incident or road-level detail"],
            warnings=["Traffic source does not provide crash or incident details."],
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
        safe_limit = self._validate_geo(lat, lon, radius_m, limit)
        await self._refresh_requested(types)
        data = self.geo.nearby(lat=lat, lon=lon, radius_m=radius_m, limit=safe_limit, types=types)
        return success_envelope(
            summary=f"{len(data)} city feature(s) found within {radius_m} meters.",
            data=data,
            sources=[CITY_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=300),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}"],
        )

    async def bbox_search(self, *, bbox: list[float], types: list[str] | None = None, limit: int | None = None) -> dict:
        min_lon, min_lat, max_lon, max_lat = validate_bbox(bbox)
        safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
        await self._refresh_requested(types)
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
        )

    def _validate_geo(self, lat: float, lon: float, radius_m: int, limit: int | None) -> int:
        validate_lat_lon(lat, lon)
        validate_radius(radius_m, self.settings.max_radius_m)
        return validate_limit(limit or self.settings.default_limit, self.settings.max_limit)

    async def _refresh_requested(self, types: list[str] | None) -> None:
        requested = set(types or ["parking", "metro_station", "air_quality_station"])
        if "parking" in requested:
            parks = await self.ispark.parks()
            self.geo.upsert_features([self._ispark_feature(park) for park in parks if park.get("lat") and park.get("lng")])
        if "metro_station" in requested:
            stations = await self.metro.stations()
            self.geo.upsert_features([self._metro_feature(station) for station in stations if self._metro_coordinates(station)])
        if "air_quality_station" in requested:
            stations = await self.air_quality.stations()
            self.geo.upsert_features([self._aq_feature(station) for station in stations if parse_wkt_point(station.get("Location"))])

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

    def _traffic_label(self, index: int | None) -> str:
        if index is None:
            return "unknown"
        if index < 30:
            return "low"
        if index < 60:
            return "moderate"
        return "high"
