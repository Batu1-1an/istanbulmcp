from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.connectors.istanbulkart import IstanbulkartClient, IstanbulkartPayload
from app.core.envelope import Freshness, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url, haversine_m
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import CachedSourceData, SourceLoadResult, cached_source_data_with_status
from app.core.validation import InputValidationError, validate_lat_lon, validate_limit, validate_radius


ISTANBULKART_CACHE_KEY = "istanbulkart.filling_centers"
ISTANBULKART_DATASET_ID = "istanbulkart-dolum-merkezi-bilgileri"
ISTANBULKART_SOURCE = Source(
    name="İBB Open Data Portal - Istanbulkart Filling Center Information",
    publisher="Istanbul Metropolitan Municipality",
    scope="Istanbulkart filling-center locations",
    url="https://data.ibb.gov.tr/en/dataset/istanbulkart-dolum-merkezi-bilgileri",
)
ISTANBUL_BOUNDS = (40.70, 41.50, 27.80, 30.20)
STATIC_WARNING = (
    "Annual/static location data; no live open/closed, load-success, balance, queue, or stock guarantee."
)


@dataclass(frozen=True)
class IstanbulkartCenter:
    source_id: str
    terminal_type: str | None
    district: str | None
    latitude: float
    longitude: float
    source_inserted_at: str | None
    maps_url: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "terminal_type": self.terminal_type,
            "district": self.district,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "source_inserted_at": self.source_inserted_at,
            "maps_url": self.maps_url,
        }


@dataclass(frozen=True)
class IstanbulkartSourceSnapshot:
    rows: tuple[IstanbulkartCenter, ...]
    metadata: dict[str, Any]


class IstanbulkartService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: IstanbulkartClient | Any | None = None,
        istanbulkart_client: IstanbulkartClient | Any | None = None,
    ) -> None:
        self.settings = settings
        if client is not None and istanbulkart_client is not None:
            raise ValueError("Pass only one İstanbulkart client override")
        self.client = client or istanbulkart_client or IstanbulkartClient(
            dataset_id=settings.istanbulkart_dataset_id,
            resource_id=settings.istanbulkart_resource_id,
            page_size=settings.istanbulkart_datastore_page_size,
        )

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int = 2000,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_lat, safe_lon = self._validate_coordinates(lat, lon)
            if isinstance(radius_m, bool) or not isinstance(radius_m, int):
                raise InputValidationError("radius_m must be an integer", field="radius_m")
            if limit is not None and (isinstance(limit, bool) or not isinstance(limit, int)):
                raise InputValidationError("limit must be an integer", field="limit")
            safe_radius = validate_radius(
                radius_m,
                min(self.settings.max_radius_m, 5000),
            )
            safe_limit = validate_limit(
                min(self.settings.default_limit, self.settings.max_limit, 100)
                if limit is None
                else limit,
                min(self.settings.max_limit, 100),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[ISTANBULKART_SOURCE])

        try:
            cached = await self._snapshot()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error(exc)

        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for center in cached.value.rows:
            distance = haversine_m(safe_lat, safe_lon, center.latitude, center.longitude)
            if distance <= safe_radius:
                item = center.as_dict()
                item["distance_m"] = round(distance, 1)
                ranked.append((distance, center.source_id, item))
        ranked.sort(key=lambda item: (item[0], item[1]))
        data = [item for _, _, item in ranked[:safe_limit]]

        return success_envelope(
            summary=f"{len(data)} İstanbulkart dolum merkezi {safe_radius} metre içinde bulundu.",
            data=data,
            sources=[self._source(cached)],
            freshness=self._freshness(cached),
            limits=[
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                "distance=straight-line Haversine",
                "scope=Istanbulkart filling-center locations",
            ],
            warnings=self._warnings(cached),
        )

    async def _snapshot(self) -> CachedSourceData:
        return await cached_source_data_with_status(
            ISTANBULKART_CACHE_KEY,
            ttl_seconds=self.settings.istanbulkart_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.istanbulkart_stale_if_error_seconds,
            loader=self._load_snapshot,
        )

    async def _load_snapshot(self) -> SourceLoadResult:
        payload: IstanbulkartPayload = await self.client.fetch()
        accepted: list[IstanbulkartCenter] = []
        seen_ids: set[str] = set()
        duplicate_total = 0
        invalid_total = 0
        out_of_scope_total = 0
        unknown_type_total = 0

        for raw in payload.rows:
            center, reason = self._normalize_row(raw)
            if center is None:
                invalid_total += 1
                if reason == "out_of_scope":
                    out_of_scope_total += 1
                continue
            if center.source_id in seen_ids:
                duplicate_total += 1
                continue
            seen_ids.add(center.source_id)
            if center.terminal_type is None:
                unknown_type_total += 1
            accepted.append(center)

        skipped_total = payload.reported_total - len(accepted)
        metadata = {
            "dataset_id": payload.dataset_id,
            "resource_id": payload.resource_id,
            "resource_year": payload.resource_year,
            "source_updated_at": payload.source_updated_at,
            "package_updated_at": payload.package_updated_at,
            "schema_fields": list(payload.schema_fields),
            "reported_total": payload.reported_total,
            "received_total": len(payload.rows),
            "accepted_total": len(accepted),
            "skipped_total": max(0, skipped_total),
            "duplicate_total": duplicate_total,
            "invalid_total": invalid_total,
            "out_of_scope_total": out_of_scope_total,
            "unknown_type_total": unknown_type_total,
        }
        return SourceLoadResult(
            value=IstanbulkartSourceSnapshot(rows=tuple(accepted), metadata=metadata),
            metadata=metadata,
            max_cache_age_seconds=(
                self.settings.istanbulkart_cache_ttl_seconds
                + self.settings.istanbulkart_stale_if_error_seconds
            ),
        )

    def _normalize_row(self, raw: dict[str, Any]) -> tuple[IstanbulkartCenter | None, str | None]:
        if not isinstance(raw, dict):
            return None, "invalid"
        source_id = self._text(raw.get("terminal_id"))
        if not source_id:
            return None, "missing_id"
        latitude = self._coordinate(raw.get("latitude"), -90, 90)
        longitude = self._coordinate(raw.get("longitude"), -180, 180)
        if latitude is None or longitude is None:
            return None, "invalid_coordinate"
        if not (
            ISTANBUL_BOUNDS[0] <= latitude <= ISTANBUL_BOUNDS[1]
            and ISTANBUL_BOUNDS[2] <= longitude <= ISTANBUL_BOUNDS[3]
        ):
            return None, "out_of_scope"
        terminal_type = self._text(raw.get("terminal_subtype_definition_desc_cd"))
        district = self._text(raw.get("town_id"))
        return (
            IstanbulkartCenter(
                source_id=source_id,
                terminal_type=terminal_type,
                district=district,
                latitude=latitude,
                longitude=longitude,
                source_inserted_at=self._text(raw.get("insert_dt")),
                maps_url=google_maps_url(latitude, longitude) or "",
            ),
            None,
        )

    def _source(self, cached: CachedSourceData) -> Source:
        metadata = cached.metadata or {}
        return ISTANBULKART_SOURCE.model_copy(
            update={
                "dataset_id": metadata.get("dataset_id", self.settings.istanbulkart_dataset_id),
                "resource_id": metadata.get("resource_id"),
                "source_updated_at": metadata.get("source_updated_at"),
                "last_successful_refresh_at": cached.refreshed_at_iso,
                "reported_total": metadata.get("reported_total"),
                "received_total": metadata.get("received_total"),
                "accepted_total": metadata.get("accepted_total"),
                "skipped_total": metadata.get("skipped_total"),
            }
        )

    def _freshness(self, cached: CachedSourceData) -> Freshness:
        metadata = cached.metadata or {}
        return Freshness(
            status="stale" if cached.is_stale else "fresh",
            retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
            source_updated_at=metadata.get("source_updated_at"),
            ttl_seconds=self.settings.istanbulkart_cache_ttl_seconds,
        )

    def _warnings(self, cached: CachedSourceData) -> list[str]:
        metadata = cached.metadata or {}
        warnings = [STATIC_WARNING]
        if cached.is_stale:
            error_type = type(cached.error).__name__ if cached.error else "UnknownError"
            warnings.insert(
                0,
                f"İstanbulkart kaynağı yenilenemedi ({error_type}); son başarılı snapshot stale olarak gösteriliyor.",
            )
        if metadata.get("duplicate_total", 0):
            warnings.append(f"{metadata['duplicate_total']} duplicate source row excluded.")
        if metadata.get("invalid_total", 0):
            warnings.append(
                f"{metadata['invalid_total']} source row excluded due to invalid identity, coordinates, or scope."
            )
        if metadata.get("out_of_scope_total", 0):
            warnings.append(
                f"{metadata['out_of_scope_total']} source row excluded because it was outside the Istanbul scope."
            )
        if metadata.get("unknown_type_total", 0):
            warnings.append(
                f"{metadata['unknown_type_total']} accepted center row has no terminal type; type was not inferred."
            )
        return warnings

    def _rate_limited(self, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        return error_envelope(
            summary="İstanbulkart kaynağı hız sınırına ulaştı.",
            warning=f"Istanbulkart source rate limit exceeded; retry_after_seconds={exc.retry_after_seconds:.1f}",
            sources=[ISTANBULKART_SOURCE],
            limits=["source=ckan", f"retry_after_seconds={exc.retry_after_seconds:.1f}"],
        )

    def _source_error(self, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary="İstanbulkart kaynağı kullanılamıyor.",
            warning=f"Istanbulkart source request failed: {type(exc).__name__}",
            sources=[ISTANBULKART_SOURCE],
            exception=exc,
        )

    def _validate_coordinates(self, lat: Any, lon: Any) -> tuple[float, float]:
        try:
            safe_lat = float(lat)
            safe_lon = float(lon)
        except (TypeError, ValueError) as exc:
            raise InputValidationError("lat and lon must be finite numbers", field="coordinates") from exc
        if not math.isfinite(safe_lat) or not math.isfinite(safe_lon):
            raise InputValidationError("lat and lon must be finite numbers", field="coordinates")
        return validate_lat_lon(safe_lat, safe_lon)

    def _coordinate(self, value: Any, minimum: float, maximum: float) -> float | None:
        if value is None or value == "":
            return None
        try:
            parsed = float(str(value).strip().replace(",", "."))
        except (TypeError, ValueError):
            return None
        if not math.isfinite(parsed) or not minimum <= parsed <= maximum:
            return None
        return parsed

    def _text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
