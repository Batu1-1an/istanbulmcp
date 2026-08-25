from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

from app.connectors.ieo import IeoClient
from app.core.envelope import Freshness, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url, haversine_m
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import CachedSourceData, SourceLoadResult, cached_source_data_with_status
from app.core.validation import InputValidationError, validate_lat_lon, validate_limit, validate_radius, validate_text
from app.services.places import normalize_place


IEO_CACHE_KEY = "ieo.on_duty_pharmacies"
IEO_SOURCE_NAME = "İstanbul Eczacı Odası - Nöbetçi Eczane"
IEO_MAX_RADIUS_M = 5_000
IEO_MAX_LIMIT = 100
IEO_SOURCE = Source(
    name=IEO_SOURCE_NAME,
    publisher="İstanbul Eczacı Odası",
    scope="İstanbul on-duty roster",
    url="https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php",
)


@dataclass(frozen=True)
class PharmacyRoster:
    rows: tuple[dict[str, Any], ...]


class PharmacyService:
    def __init__(self, *, settings: Settings, ieo_client: IeoClient | None = None) -> None:
        self.settings = settings
        self.ieo = ieo_client or IeoClient(
            base_url=settings.ieo_base_url,
            timeout=settings.ieo_request_timeout_seconds,
            attempts=settings.ieo_request_attempts,
        )

    async def nearby(
        self,
        *,
        lat: float,
        lon: float,
        radius_m: int = 1000,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            validate_lat_lon(lat, lon)
            safe_radius = validate_radius(
                radius_m,
                min(self.settings.max_radius_m, IEO_MAX_RADIUS_M),
            )
            safe_limit = validate_limit(
                min(self.settings.default_limit, IEO_MAX_LIMIT)
                if limit is None
                else limit,
                min(self.settings.max_limit, IEO_MAX_LIMIT),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IEO_SOURCE])

        try:
            cached = await self._roster()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("IEO nöbetçi eczane", exc)
        except Exception as exc:
            return self._source_error("İEO nöbetçi eczane kaynağı kullanılamıyor.", exc)

        data = []
        for row in cached.value.rows:
            if row["lat"] is None or row["lon"] is None:
                continue
            distance = haversine_m(lat, lon, row["lat"], row["lon"])
            if distance <= safe_radius:
                item = dict(row)
                item["distance_m"] = round(distance, 1)
                data.append(item)
        data.sort(key=lambda row: (row["distance_m"], normalize_place(row["name"]), row["source_id"]))
        data = data[:safe_limit]
        warnings = self._warnings(cached)
        return success_envelope(
            summary=f"{len(data)} nöbetçi eczane {safe_radius} metre içinde bulundu.",
            data=data,
            sources=[self._source(cached)],
            freshness=self._freshness(cached),
            limits=[
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                "scope=İstanbul on-duty roster",
            ],
            warnings=warnings,
        )

    async def by_district(self, *, district: str, limit: int | None = None) -> dict[str, Any]:
        try:
            safe_district = validate_text(district, field="district", max_length=80)
            safe_limit = validate_limit(
                min(self.settings.default_limit, IEO_MAX_LIMIT)
                if limit is None
                else limit,
                min(self.settings.max_limit, IEO_MAX_LIMIT),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IEO_SOURCE])

        try:
            cached = await self._roster()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("IEO nöbetçi eczane", exc)
        except Exception as exc:
            return self._source_error("İEO nöbetçi eczane kaynağı kullanılamıyor.", exc)

        normalized = self._normalize_district(safe_district)
        data = [
            dict(row)
            for row in cached.value.rows
            if self._normalize_district(row["district"]) == normalized
        ]
        data.sort(key=lambda row: (normalize_place(row["name"]), row["source_id"]))
        data = data[:safe_limit]
        warnings = self._warnings(cached)
        warnings.append("Bu ilçe geneli nöbetçi eczane listesidir; mesafe hesaplanmadı.")
        return success_envelope(
            summary=f"{len(data)} nöbetçi eczane {safe_district} ilçesinde bulundu.",
            data=data,
            sources=[self._source(cached)],
            freshness=self._freshness(cached),
            limits=[
                f"limit={safe_limit}",
                "scope=İstanbul on-duty roster",
                "district-wide list; no distance claim",
            ],
            warnings=warnings,
        )

    async def _roster(self) -> CachedSourceData:
        return await cached_source_data_with_status(
            IEO_CACHE_KEY,
            ttl_seconds=self.settings.ieo_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.ieo_stale_if_error_seconds,
            loader=self._load_roster,
        )

    async def _load_roster(self) -> SourceLoadResult:
        raw_rows = await self.ieo.markers()
        reported_total = len(raw_rows)
        accepted: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for raw in raw_rows:
            normalized = self._normalize_row(raw)
            if normalized is None:
                continue
            source_id = normalized["source_id"]
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)
            if self._normalize_district(normalized["province"]) != self._normalize_district("İstanbul"):
                continue
            accepted.append(normalized)
        return SourceLoadResult(
            value=PharmacyRoster(rows=tuple(accepted)),
            metadata={
                "scope": "İstanbul on-duty roster",
                "reported_total": reported_total,
                "received_total": reported_total,
                "accepted_total": len(accepted),
                "skipped_total": reported_total - len(accepted),
            },
        )

    def _normalize_row(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        source_id = self._text_or_none(raw.get("sicil"))
        name = self._text_or_none(raw.get("eczane_ad"))
        province = self._text_or_none(raw.get("il"))
        district = self._text_or_none(raw.get("ilce"))
        if (
            not source_id
            or not name
            or not province
            or not district
        ):
            return None
        lat = self._valid_latitude(raw.get("lat"))
        lon = self._valid_longitude(raw.get("lng"))
        address_parts = [
            self._text_or_none(raw.get("mahalle")),
            self._text_or_none(raw.get("cadde_sokak")),
            self._text_or_none(raw.get("bina_kapi")),
            district,
            province,
        ]
        return {
            "source_id": source_id,
            "name": name,
            "phone": self._text_or_none(raw.get("eczane_tel")),
            "province": province,
            "district": district,
            "area": self._text_or_none(raw.get("semt")),
            "neighborhood": self._text_or_none(raw.get("mahalle")),
            "street": self._text_or_none(raw.get("cadde_sokak")),
            "building": self._text_or_none(raw.get("bina_kapi")),
            "directions": self._text_or_none(raw.get("tarif")),
            "postal_code": self._text_or_none(raw.get("posta_kodu")),
            "lat": lat,
            "lon": lon,
            "duty_ends_at": self._text_or_none(raw.get("nobet_bitis")),
            "address": ", ".join(part for part in address_parts if part),
            "maps_url": google_maps_url(lat, lon) if lat is not None and lon is not None else None,
        }

    def _source(self, cached: CachedSourceData) -> Source:
        metadata = cached.metadata or {}
        return IEO_SOURCE.model_copy(
            update={
                "last_successful_refresh_at": cached.refreshed_at_iso,
                "reported_total": metadata.get("reported_total"),
                "received_total": metadata.get("received_total"),
                "accepted_total": metadata.get("accepted_total"),
                "skipped_total": metadata.get("skipped_total"),
            }
        )

    def _freshness(self, cached: CachedSourceData) -> Freshness:
        return Freshness(
            status="stale" if cached.is_stale else "fresh",
            retrieved_at=cached.refreshed_at_iso or utc_now_iso(),
            ttl_seconds=self.settings.ieo_cache_ttl_seconds,
        )

    def _warnings(self, cached: CachedSourceData) -> list[str]:
        warnings: list[str] = []
        if cached.is_stale:
            error_type = type(cached.error).__name__ if cached.error is not None else "UnknownError"
            warnings.append(
                f"İEO kaynağı yenilenemedi ({error_type}); son başarılı liste stale olarak gösteriliyor."
            )
        if any(row.get("duty_ends_at") is None for row in cached.value.rows):
            warnings.append("Kaynak bazı nöbet bitiş zamanlarını vermedi; bitiş zamanı tahmin edilmedi.")
        if any(row.get("lat") is None or row.get("lon") is None for row in cached.value.rows):
            warnings.append(
                "Kaynak bazı eczaneler için konum/koordinat bilgisi vermedi; bu kayıtlar yakınlık sonuçlarına dahil edilmedi."
            )
        warnings.append("Bu sonuçlar İEO'nun nöbetçi eczane listesidir; genel katalog veya kesin nöbet garantisi değildir.")
        return warnings

    def _rate_limited(self, summary: str, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        return error_envelope(
            summary=f"{summary} kaynağı hız sınırına ulaştı.",
            warning=f"IEO source rate limit exceeded; retry_after_seconds={exc.retry_after_seconds:.1f}",
            sources=[IEO_SOURCE],
            limits=["source=ieo", f"retry_after_seconds={exc.retry_after_seconds:.1f}"],
        )

    def _source_error(self, summary: str, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary=summary,
            warning=f"IEO source request failed: {type(exc).__name__}",
            sources=[IEO_SOURCE],
            exception=exc,
        )

    def _normalize_district(self, value: Any) -> str:
        normalized = normalize_place(str(value or ""))
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    def _text_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _float_or_none(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _valid_latitude(self, value: Any) -> float | None:
        coordinate = self._float_or_none(value)
        if coordinate is None or not math.isfinite(coordinate) or not -90 <= coordinate <= 90:
            return None
        return coordinate

    def _valid_longitude(self, value: Any) -> float | None:
        coordinate = self._float_or_none(value)
        if coordinate is None or not math.isfinite(coordinate) or not -180 <= coordinate <= 180:
            return None
        return coordinate
