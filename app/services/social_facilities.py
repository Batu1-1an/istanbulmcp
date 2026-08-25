from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from app.connectors.social_facilities import (
    FORBIDDEN_FIELDS,
    ISTANBUL_BOUNDS,
    SocialFacilitiesClient,
    SocialFacilitiesPayload,
    canonical_identity,
)
from app.core.envelope import Freshness, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url, haversine_m
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings, get_settings
from app.core.source_cache import CachedSourceData, SourceLoadResult, cached_source_data_with_status
from app.core.validation import InputValidationError, validate_lat_lon, validate_limit, validate_radius


SOCIAL_FACILITIES_CACHE_KEY = "social_facilities.locations"
SOCIAL_FACILITIES_SOURCE = Source(
    name="İBB Sosyal Tesisler resmi canlı kataloğu",
    publisher="Istanbul Metropolitan Municipality",
    scope="social facility locations in Istanbul",
    url="https://tesislerimiz.ibb.istanbul/tesisler",
)
SOCIAL_FACILITIES_FALLBACK_SOURCE = Source(
    name="İBB Open Data - Sosyal Tesis Konumları",
    publisher="Istanbul Metropolitan Municipality",
    scope="social facility location fallback",
    dataset_id="sosyal-tesis-konumlari",
    url="https://data.ibb.gov.tr/dataset/6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d",
)
LOCATION_ONLY_WARNING = "Official location data only; visit the linked source for current facility details."


@dataclass(frozen=True)
class SocialFacilityRecord:
    name: str
    latitude: float
    longitude: float
    distance_m: float = 0.0
    source_id: str | None = None
    district: str | None = None
    address: str | None = None
    detail_url: str | None = None
    reservation_url: str | None = None

    def as_dict(self) -> dict[str, Any]:
        # This explicit allow-list is a response-field guard.  Source payloads
        # can carry provenance internally, but operational fields never cross
        # the MCP boundary.
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "distance_m": self.distance_m,
            "maps_url": google_maps_url(self.latitude, self.longitude),
            "source_id": self.source_id,
            "district": self.district,
            "address": self.address,
            "detail_url": self.detail_url,
            "reservation_url": self.reservation_url,
        }


@dataclass(frozen=True)
class SocialFacilitySnapshot:
    rows: tuple[dict[str, Any], ...]
    metadata: dict[str, Any]


class SocialFacilitiesService:
    def __init__(
        self,
        *,
        settings: Settings | None = None,
        client: SocialFacilitiesClient | Any | None = None,
        social_facilities_client: SocialFacilitiesClient | Any | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        if client is not None and social_facilities_client is not None:
            raise ValueError("Pass only one social-facility client override")
        self.client = client or social_facilities_client or SocialFacilitiesClient(settings=self.settings)

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
            safe_radius = validate_radius(radius_m, min(self.settings.max_radius_m, 5000))
            safe_limit = validate_limit(
                min(self.settings.default_limit, self.settings.max_limit, 100) if limit is None else limit,
                min(self.settings.max_limit, 100),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=self._sources())

        try:
            cached = await self._snapshot()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited(exc)
        except Exception as exc:
            return self._source_error(exc)

        ranked: list[tuple[float, str, dict[str, Any]]] = []
        for row in cached.value.rows:
            distance = haversine_m(safe_lat, safe_lon, row["latitude"], row["longitude"])
            if distance <= safe_radius:
                item = self._public_row(row)
                item["distance_m"] = round(distance, 1)
                ranked.append((distance, self._sort_key(row), item))
        ranked.sort(key=lambda item: (item[0], item[1]))
        data = [item for _, _, item in ranked[:safe_limit]]
        return success_envelope(
            summary=f"{len(data)} İstanbul sosyal tesisi {safe_radius} metre içinde bulundu.",
            data=data,
            sources=self._sources(cached),
            freshness=self._freshness(cached),
            limits=[
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                "distance=straight-line Haversine",
                "scope=Istanbul social facility locations",
            ],
            warnings=self._warnings(cached),
        )

    async def _snapshot(self) -> CachedSourceData:
        return await cached_source_data_with_status(
            SOCIAL_FACILITIES_CACHE_KEY,
            ttl_seconds=self.settings.social_facilities_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.social_facilities_stale_if_error_seconds,
            loader=self._load_snapshot,
        )

    async def _load_snapshot(self) -> SourceLoadResult:
        payload: SocialFacilitiesPayload = await self.client.fetch()
        accepted: list[dict[str, Any]] = []
        identities: set[str] = set()
        invalid_total = 0
        out_of_scope_total = 0
        duplicate_total = int(payload.duplicate_total or 0)
        identity_conflict_total = 0
        missing_optional_total = 0
        identity_rows: dict[str, dict[str, Any]] = {}
        for raw in payload.rows:
            normalized, reason = self._normalize_row(raw)
            if normalized is None:
                invalid_total += 1
                if reason == "out_of_scope":
                    out_of_scope_total += 1
                continue
            identity = canonical_identity(normalized)
            if identity in identities:
                previous = identity_rows[identity]
                if self._identity_conflict(previous, normalized):
                    identity_conflict_total += 1
                    # Same nominal identity but different valid location data is
                    # ambiguous; preserve both rather than silently merging.
                    normalized["identity_conflict"] = True
                    accepted.append(normalized)
                    continue
                duplicate_total += 1
                continue
            identities.add(identity)
            identity_rows[identity] = normalized
            if any(normalized.get(field) is None for field in ("district", "address", "detail_url", "reservation_url")):
                missing_optional_total += 1
            accepted.append(normalized)
        reported_total = int(payload.reported_total) if payload.reported_total is not None else len(payload.rows)
        skipped_total = max(int(payload.skipped_total or 0), reported_total - len(accepted) - duplicate_total)
        # A fallback can add valid rows beyond the live catalogue's count.  Keep
        # the public accounting invariant explicit instead of exposing a negative
        # or internally inconsistent source total.
        if reported_total < len(accepted) + skipped_total + duplicate_total:
            reported_total = len(accepted) + skipped_total + duplicate_total
        metadata = {
            "reported_total": reported_total,
            "received_total": int(payload.received_total or len(payload.rows)),
            "accepted_total": len(accepted),
            "skipped_total": skipped_total,
            "duplicate_total": duplicate_total,
            "invalid_total": invalid_total,
            "out_of_scope_total": out_of_scope_total,
            "identity_conflict_total": identity_conflict_total,
            "missing_optional_total": missing_optional_total,
            "source_updated_at": payload.source_updated_at,
            "fallback_source_updated_at": payload.fallback_source_updated_at,
            "primary_source_url": payload.primary_source_url or SOCIAL_FACILITIES_SOURCE.url,
            "fallback_source_url": payload.fallback_source_url,
            "fallback_resource_id": payload.fallback_resource_id,
            "fallback_only": payload.fallback_only,
            "partial_source": payload.partial_source,
            "warnings": list(payload.warnings),
        }
        return SourceLoadResult(
            value=SocialFacilitySnapshot(rows=tuple(accepted), metadata=metadata),
            metadata=metadata,
            max_cache_age_seconds=(
                self.settings.social_facilities_cache_ttl_seconds
                + min(self.settings.social_facilities_stale_if_error_seconds, 604800)
            ),
        )

    def _normalize_row(self, raw: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        if not isinstance(raw, dict):
            return None, "invalid"
        name = self._text(raw.get("name"))
        latitude = self._coordinate(raw.get("latitude"), -90, 90)
        longitude = self._coordinate(raw.get("longitude"), -180, 180)
        if not name or latitude is None or longitude is None:
            return None, "invalid"
        if not self._in_istanbul(latitude, longitude):
            return None, "out_of_scope"
        return (
            {
                "name": name,
                "latitude": latitude,
                "longitude": longitude,
                "source_id": self._text(raw.get("source_id")),
                "district": self._text(raw.get("district")),
                "address": self._text(raw.get("address")),
                "detail_url": self._url(raw.get("detail_url")),
                "reservation_url": self._url(raw.get("reservation_url")),
            },
            None,
        )

    def _public_row(self, row: dict[str, Any]) -> dict[str, Any]:
        data = {
            "name": row["name"],
            "latitude": row["latitude"],
            "longitude": row["longitude"],
            "distance_m": 0.0,
            "maps_url": google_maps_url(row["latitude"], row["longitude"]),
            "source_id": row.get("source_id"),
            "district": row.get("district"),
            "address": row.get("address"),
            "detail_url": row.get("detail_url"),
            "reservation_url": row.get("reservation_url"),
        }
        return {key: value for key, value in data.items() if key not in FORBIDDEN_FIELDS}

    def _sources(self, cached: CachedSourceData | None = None) -> list[Source]:
        if cached is None:
            return [SOCIAL_FACILITIES_SOURCE]
        metadata = cached.metadata or {}
        primary = SOCIAL_FACILITIES_SOURCE.model_copy(
            update={
                "url": metadata.get("primary_source_url", SOCIAL_FACILITIES_SOURCE.url),
                "source_updated_at": metadata.get("source_updated_at"),
                "last_successful_refresh_at": cached.refreshed_at_iso,
                "reported_total": metadata.get("reported_total"),
                "received_total": metadata.get("received_total"),
                "accepted_total": metadata.get("accepted_total"),
                "skipped_total": metadata.get("skipped_total"),
            }
        )
        sources = [primary]
        if metadata.get("fallback_source_url") or metadata.get("fallback_only"):
            sources.append(
                SOCIAL_FACILITIES_FALLBACK_SOURCE.model_copy(
                    update={
                        "url": metadata.get("fallback_source_url", SOCIAL_FACILITIES_FALLBACK_SOURCE.url),
                        "resource_id": metadata.get("fallback_resource_id"),
                        "source_updated_at": metadata.get("fallback_source_updated_at"),
                        "last_successful_refresh_at": cached.refreshed_at_iso,
                    }
                )
            )
        return sources

    def _freshness(self, cached: CachedSourceData) -> Freshness:
        metadata = cached.metadata or {}
        source_updated_at = metadata.get("fallback_source_updated_at") if metadata.get("fallback_only") else metadata.get("source_updated_at")
        return Freshness(
            status="stale" if cached.is_stale else "fresh",
            retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
            source_updated_at=source_updated_at,
            ttl_seconds=self.settings.social_facilities_cache_ttl_seconds,
        )

    def _warnings(self, cached: CachedSourceData) -> list[str]:
        metadata = cached.metadata or {}
        source_warnings = [
            warning
            for warning in metadata.get("warnings", [])
            if not any(term in str(warning).casefold() for term in FORBIDDEN_FIELDS)
        ]
        warnings = [LOCATION_ONLY_WARNING, *source_warnings]
        if cached.is_stale:
            error_type = type(cached.error).__name__ if cached.error else "UnknownError"
            warnings.insert(0, f"Social-facility source refresh failed ({error_type}); last successful snapshot is stale.")
        if metadata.get("fallback_only") and "fallback_only" not in " ".join(warnings):
            warnings.append("fallback_only: official fallback locations are being used.")
        if metadata.get("partial_source") and not any("partially" in item for item in warnings):
            warnings.append("Live social-facility source was partial; skipped records are counted in source metadata.")
        if metadata.get("duplicate_total"):
            warnings.append(f"{metadata['duplicate_total']} duplicate source row(s) excluded.")
        if metadata.get("invalid_total"):
            warnings.append(f"{metadata['invalid_total']} source row(s) excluded due to invalid fields.")
        if metadata.get("out_of_scope_total"):
            warnings.append(f"{metadata['out_of_scope_total']} source row(s) excluded because they are outside Istanbul.")
        if metadata.get("identity_conflict_total"):
            warnings.append(
                f"{metadata['identity_conflict_total']} source identity conflict(s) preserved as separate rows."
            )
        if metadata.get("missing_optional_total"):
            warnings.append(
                f"{metadata['missing_optional_total']} accepted row(s) have one or more optional fields unavailable; nulls were preserved."
            )
        return warnings

    def _rate_limited(self, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        return error_envelope(
            summary="İstanbul sosyal tesis kaynağı hız sınırına ulaştı.",
            warning=f"Social-facility source rate limit exceeded; retry_after_seconds={exc.retry_after_seconds:.1f}",
            sources=self._sources(),
            limits=["source=social_facilities", f"retry_after_seconds={exc.retry_after_seconds:.1f}"],
        )

    def _source_error(self, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary="İstanbul sosyal tesis kaynağı kullanılamıyor.",
            warning=f"Social-facility source request failed: {type(exc).__name__}",
            sources=self._sources(),
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

    @staticmethod
    def _in_istanbul(lat: float, lon: float) -> bool:
        return ISTANBUL_BOUNDS[0] <= lat <= ISTANBUL_BOUNDS[1] and ISTANBUL_BOUNDS[2] <= lon <= ISTANBUL_BOUNDS[3]

    @staticmethod
    def _sort_key(row: dict[str, Any]) -> str:
        return str(row.get("source_id") or row.get("detail_url") or row.get("name") or "").casefold()

    @staticmethod
    def _identity_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
        try:
            coordinate_differs = (
                abs(float(left["latitude"]) - float(right["latitude"])) > 1e-5
                or abs(float(left["longitude"]) - float(right["longitude"])) > 1e-5
            )
        except (KeyError, TypeError, ValueError):
            coordinate_differs = False
        return coordinate_differs or bool(left.get("address") and right.get("address") and left["address"].casefold() != right["address"].casefold())

    @staticmethod
    def _text(value: Any) -> str | None:
        text = str(value or "").strip()
        return text or None

    @staticmethod
    def _url(value: Any) -> str | None:
        text = str(value or "").strip()
        return text if text.startswith(("http://", "https://")) else None

    @staticmethod
    def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return None
        return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None
