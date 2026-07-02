from __future__ import annotations

from typing import Any

from app.connectors.iski import IskiClient
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url, haversine_m
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, validate_lat_lon, validate_limit, validate_radius, validate_text
from app.services.places import normalize_place


ISKI_FAULTS_URL = "https://harita.iski.gov.tr/data/mahallelerKesinti.geojson"
ISKI_DAMS_URL = "https://harita.iski.gov.tr/data/baraj.json"

ISKI_FAULTS_SOURCE = Source(
    name="ISKI active water faults GeoJSON",
    publisher="Istanbul Water and Sewerage Administration",
    license=None,
    url=ISKI_FAULTS_URL,
)

ISKI_DAMS_SOURCE = Source(
    name="ISKI dam occupancy JSON",
    publisher="Istanbul Water and Sewerage Administration",
    license=None,
    url=ISKI_DAMS_URL,
)


class IskiService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: IskiClient | None = None,
    ):
        self.settings = settings
        self.client = client or IskiClient(timeout=settings.request_timeout_seconds)

    async def active_faults(
        self,
        *,
        district: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
            safe_district = validate_text(district, field="district", max_length=80) if district else None
            rows = [self._fault_row(feature) for feature in (await self._active_fault_geojson()).get("features", [])]
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[ISKI_FAULTS_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error("ISKI active water faults source is unavailable.", exc, sources=[ISKI_FAULTS_SOURCE])

        if safe_district:
            wanted = normalize_place(safe_district)
            rows = [row for row in rows if normalize_place(row.get("district", "")) == wanted]
        rows.sort(key=lambda row: (row.get("started_at") or "", row.get("fault_number") or ""))
        data = rows[:safe_limit]
        suffix = f" in {safe_district}" if safe_district else ""
        return success_envelope(
            summary=f"{len(data)} active ISKI water fault(s) returned{suffix}.",
            data=data,
            sources=[ISKI_FAULTS_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.iski_faults_cache_ttl_seconds),
            limits=[f"limit={safe_limit}", "source=live ISKI GeoJSON"],
            warnings=["ISKI active faults source does not publish an explicit source_updated_at timestamp."],
            next_queries=["Use istanbul_iski_nearby_faults with coordinates when distance matters."],
        )

    async def fault_by_number(self, fault_number: str) -> dict[str, Any]:
        try:
            safe_fault_number = validate_text(fault_number, field="fault_number", max_length=40)
            rows = [self._fault_row(feature) for feature in (await self._active_fault_geojson()).get("features", [])]
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[ISKI_FAULTS_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error("ISKI active water faults source is unavailable.", exc, sources=[ISKI_FAULTS_SOURCE])

        matches = [row for row in rows if str(row.get("fault_number")) == safe_fault_number]
        return success_envelope(
            summary=(
                f"ISKI fault {safe_fault_number} found."
                if matches
                else f"No active ISKI fault found for number {safe_fault_number}."
            ),
            data=matches[:1],
            sources=[ISKI_FAULTS_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.iski_faults_cache_ttl_seconds),
            limits=["source=live ISKI GeoJSON", "exact active fault number match"],
            warnings=["Only currently active faults from the live map source are searchable."],
        )

    async def nearby_faults(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int = 1000,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            validate_lat_lon(lat, lon)
            validate_radius(radius_m, self.settings.max_radius_m)
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
            rows = [self._fault_row(feature) for feature in (await self._active_fault_geojson()).get("features", [])]
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[ISKI_FAULTS_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error("ISKI active water faults source is unavailable.", exc, sources=[ISKI_FAULTS_SOURCE])

        nearby = []
        for row in rows:
            center = row.get("center")
            if not center:
                continue
            distance_m = haversine_m(lat, lon, center["lat"], center["lon"])
            if distance_m <= radius_m:
                item = dict(row)
                item["distance_m"] = round(distance_m, 1)
                nearby.append(item)
        nearby.sort(key=lambda row: row["distance_m"])
        data = nearby[:safe_limit]
        return success_envelope(
            summary=f"{len(data)} active ISKI water fault(s) found within {radius_m} meters.",
            data=data,
            sources=[ISKI_FAULTS_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.iski_faults_cache_ttl_seconds),
            limits=[f"radius_m={radius_m}", f"limit={safe_limit}", "distance uses feature center"],
            warnings=["Distances use the fault area's approximate geometry center, not an address-level point."],
        )

    async def dam_occupancy(
        self,
        *,
        dam_name: str | None = None,
        min_occupancy: float | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_limit = validate_limit(limit or self.settings.max_limit, self.settings.max_limit)
            safe_dam_name = validate_text(dam_name, field="dam_name", max_length=80) if dam_name else None
            safe_min = self._validate_min_occupancy(min_occupancy)
            rows = [self._dam_row(row) for row in await self._dams()]
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[ISKI_DAMS_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error("ISKI dam occupancy source is unavailable.", exc, sources=[ISKI_DAMS_SOURCE])

        if safe_dam_name:
            wanted = normalize_place(safe_dam_name)
            rows = [
                row
                for row in rows
                if wanted in normalize_place(row.get("name", ""))
                or wanted in normalize_place(row.get("display_name", ""))
            ]
        if safe_min is not None:
            rows = [row for row in rows if row.get("occupancy_rate") is not None and row["occupancy_rate"] >= safe_min]
        rows.sort(key=lambda row: row.get("occupancy_rate") or -1, reverse=True)
        data = rows[:safe_limit]
        return success_envelope(
            summary=f"{len(data)} ISKI dam occupancy record(s) returned.",
            data=data,
            sources=[ISKI_DAMS_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=self.settings.iski_dams_cache_ttl_seconds),
            limits=[f"limit={safe_limit}", "source=live ISKI dam JSON"],
            warnings=["ISKI dam source does not publish an explicit source_updated_at timestamp."],
        )

    async def _active_fault_geojson(self) -> dict[str, Any]:
        return await cached_source_data(
            "iski.active_faults",
            ttl_seconds=self.settings.iski_faults_cache_ttl_seconds,
            loader=self.client.active_faults,
        )

    async def _dams(self) -> list[dict[str, Any]]:
        return await cached_source_data(
            "iski.dams",
            ttl_seconds=self.settings.iski_dams_cache_ttl_seconds,
            loader=self.client.dams,
        )

    def _fault_row(self, feature: dict[str, Any]) -> dict[str, Any]:
        props = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        center = self._geometry_center(geometry)
        row = {
            "fault_number": str(props.get("ARIZA_NO") or ""),
            "district": props.get("ILCE_ADI"),
            "district_code": props.get("ILCE_KODU"),
            "neighborhood": props.get("MAHALLE_ADI"),
            "neighborhood_code": props.get("MAHALLE_KODU"),
            "description": props.get("ARIZA_NEVI_ACIKLAMASI"),
            "started_at": props.get("BASLAMA_TARIHI"),
            "estimated_end_at": props.get("TAHMINI_BITIS_TARIHI"),
            "geometry_type": geometry.get("type"),
            "center": center,
            "location_precision": "geometry_center" if center else "unknown",
        }
        if center and (maps_url := google_maps_url(center["lat"], center["lon"])):
            row["maps_url"] = maps_url
        return row

    def _dam_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": row.get("kaynakAdi"),
            "display_name": row.get("baslikAdi") or row.get("kaynakAdi"),
            "yield": self._float_or_none(row.get("verim")),
            "capacity": self._float_or_none(row.get("biriktirmeHacmi")),
            "current_volume": self._float_or_none(row.get("mevcutSuHacmi")),
            "occupancy_rate": self._float_or_none(row.get("dolulukOrani")),
            "max_water_level": self._float_or_none(row.get("azamiSuSeviyesi")),
        }

    def _geometry_center(self, geometry: dict[str, Any]) -> dict[str, float] | None:
        points = list(self._iter_lon_lat(geometry.get("coordinates")))
        if not points:
            return None
        lon = sum(point[0] for point in points) / len(points)
        lat = sum(point[1] for point in points) / len(points)
        return {"lat": round(lat, 6), "lon": round(lon, 6)}

    def _iter_lon_lat(self, value: Any):
        if not isinstance(value, list):
            return
        if len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield float(value[0]), float(value[1])
            return
        for item in value:
            yield from self._iter_lon_lat(item)

    def _float_or_none(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            return None

    def _validate_min_occupancy(self, value: float | None) -> float | None:
        if value is None:
            return None
        safe_value = float(value)
        if safe_value < 0 or safe_value > 100:
            raise InputValidationError("min_occupancy must be between 0 and 100", field="min_occupancy", allowed_min=0, allowed_max=100)
        return safe_value

    def _rate_limited(self, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        retry_after = round(exc.retry_after_seconds, 3)
        return error_envelope(
            summary="ISKI source is temporarily rate limited.",
            warning=f"Local back-pressure is active for {exc.source}; retry after {retry_after} seconds.",
            sources=[ISKI_FAULTS_SOURCE, ISKI_DAMS_SOURCE],
            freshness_status="stale",
            data=[{"source": exc.source, "retry_after_seconds": retry_after}],
            limits=[f"rate_limited_source={exc.source}", f"retry_after_seconds={retry_after}"],
        )

    def _source_error(self, summary: str, exc: Exception, *, sources: list[Source]) -> dict[str, Any]:
        return source_error_envelope(
            summary=summary,
            warning=f"ISKI source request failed: {type(exc).__name__}",
            sources=sources,
            exception=exc,
        )
