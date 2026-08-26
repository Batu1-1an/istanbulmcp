from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass
from typing import Any

from app.connectors.ibb_pharmacy import (
    IBB_PHARMACY_SOURCE_URL,
    IbbPharmacyClient,
    IbbPharmacyPayloadError,
)
from app.core.envelope import Freshness, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url, haversine_m
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import CachedSourceData, SourceLoadResult, cached_source_data_with_status
from app.core.validation import (
    InputValidationError,
    validate_lat_lon,
    validate_limit,
    validate_radius,
    validate_text,
)
from app.services.places import normalize_place


IBB_CACHE_KEY = "ibb_pharmacy.on_duty_pharmacies"
IBB_SOURCE_NAME = "İBB Şehir Haritası - Nöbetçi Eczaneler"
IBB_MAX_RADIUS_M = 5_000
IBB_MAX_LIMIT = 100
IBB_SOURCE = Source(
    name=IBB_SOURCE_NAME,
    publisher="İstanbul Büyükşehir Belediyesi",
    operator="ibb",
    coverage_kind="live_status",
    coverage_status="checked",
    scope="İstanbul on-duty roster",
    url=IBB_PHARMACY_SOURCE_URL,
)


@dataclass(frozen=True)
class PharmacyRoster:
    rows: tuple[dict[str, Any], ...]


class PharmacyService:
    def __init__(self, *, settings: Settings, ibb_client: IbbPharmacyClient | None = None) -> None:
        self.settings = settings
        self.ibb = ibb_client or IbbPharmacyClient(
            base_url=settings.ibb_pharmacy_base_url,
            timeout=settings.ibb_pharmacy_request_timeout_seconds,
            attempts=settings.ibb_pharmacy_request_attempts,
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
            self._validate_coordinates(lat, lon)
            safe_radius = self._validate_radius(radius_m)
            safe_limit = self._validate_limit(limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IBB_SOURCE])

        try:
            cached = await self._roster()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("İBB nöbetçi eczane", exc)
        except Exception as exc:
            return self._source_error("İBB nöbetçi eczane kaynağı kullanılamıyor.", exc)

        data: list[dict[str, Any]] = []
        for row in cached.value.rows:
            if row["lat"] is None or row["lon"] is None:
                continue
            distance = haversine_m(float(lat), float(lon), row["lat"], row["lon"])
            if distance <= safe_radius:
                item = dict(row)
                item["distance_m"] = round(distance, 1)
                data.append(item)
        data.sort(key=lambda row: (row["distance_m"], normalize_place(row["name"]), row["source_id"]))
        data = data[:safe_limit]
        warnings = self._warnings(cached)
        metadata = cached.metadata or {}
        return success_envelope(
            summary=(
                f"{len(data)} nöbetçi eczane {safe_radius} metre içinde bulundu."
                if data
                else f"{safe_radius} metre içinde nöbetçi eczane bulunamadı."
            ),
            data=data,
            sources=[self._source(cached)],
            freshness=self._freshness(cached),
            limits=[
                f"radius_m={safe_radius}",
                f"limit={safe_limit}",
                "distance=straight-line Haversine",
                "scope=İstanbul on-duty roster",
                f"accepted_total={metadata.get('accepted_total', 0)}",
                f"geo_eligible_total={metadata.get('geo_eligible_total', 0)}",
            ],
            warnings=warnings,
        )

    async def by_district(self, *, district: str, limit: int | None = None) -> dict[str, Any]:
        try:
            safe_district = validate_text(district, field="district", max_length=80)
            safe_limit = self._validate_limit(limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IBB_SOURCE])

        try:
            cached = await self._roster()
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("İBB nöbetçi eczane", exc)
        except Exception as exc:
            return self._source_error("İBB nöbetçi eczane kaynağı kullanılamıyor.", exc)

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
            summary=(
                f"{len(data)} nöbetçi eczane {safe_district} ilçesinde bulundu."
                if data
                else f"{safe_district} ilçesinde nöbetçi eczane bulunamadı."
            ),
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
            IBB_CACHE_KEY,
            ttl_seconds=self.settings.ibb_pharmacy_cache_ttl_seconds,
            stale_if_error_seconds=self.settings.ibb_pharmacy_stale_if_error_seconds,
            loader=self._load_roster,
        )

    async def _load_roster(self) -> SourceLoadResult:
        raw_rows = await self.ibb.roster()
        reported_total = len(raw_rows)
        accepted: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        skipped_total = 0
        invalid_total = 0
        duplicate_total = 0
        geo_eligible_total = 0
        for raw in raw_rows:
            normalized = self._normalize_row(raw)
            if normalized is None:
                skipped_total += 1
                invalid_total += 1
                continue
            source_id = normalized["source_id"]
            if source_id in seen_ids:
                skipped_total += 1
                duplicate_total += 1
                continue
            seen_ids.add(source_id)
            if normalized["lat"] is not None and normalized["lon"] is not None:
                geo_eligible_total += 1
            accepted.append(normalized)
        if reported_total > 0 and not accepted:
            raise IbbPharmacyPayloadError("İBB pharmacy roster contained no domain-valid rows")
        return SourceLoadResult(
            value=PharmacyRoster(rows=tuple(accepted)),
            metadata={
                "scope": "İstanbul on-duty roster",
                "reported_total": reported_total,
                "received_total": reported_total,
                "accepted_total": len(accepted),
                "skipped_total": skipped_total,
                "invalid_total": invalid_total,
                "duplicate_total": duplicate_total,
                "geo_eligible_total": geo_eligible_total,
            },
            max_cache_age_seconds=self.settings.ibb_pharmacy_max_cache_age_seconds,
        )

    def _normalize_row(self, raw: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(raw, dict):
            return None
        name = self._text_or_none(raw.get("ADI"))
        address = self._text_or_none(raw.get("ADRES"))
        district = self._text_or_none(raw.get("ILCEADI"))
        district_id = self._text_or_none(raw.get("ILCEID"))
        if not name or not address or not district or not district_id:
            return None
        lat = self._valid_latitude(raw.get("LAT"))
        lon = self._valid_longitude(raw.get("LON"))
        if lat is None or lon is None:
            lat = None
            lon = None
        phone = self._text_or_none(raw.get("TELEFON"))
        identity = "|".join(
            [
                district_id,
                normalize_place(name),
                normalize_place(address),
                normalize_place(phone or ""),
                "" if lat is None else f"{lat:.7f}",
                "" if lon is None else f"{lon:.7f}",
            ]
        )
        source_id = f"ibb:{hashlib.sha256(identity.encode('utf-8')).hexdigest()}"
        return {
            "source_id": source_id,
            "name": name,
            "phone": phone,
            "province": "İstanbul",
            "district": district,
            "district_id": district_id,
            "area": None,
            "neighborhood": None,
            "street": None,
            "building": None,
            "directions": None,
            "postal_code": None,
            "lat": lat,
            "lon": lon,
            "duty_ends_at": None,
            "address": address,
            "maps_url": google_maps_url(lat, lon),
        }

    def _source(self, cached: CachedSourceData) -> Source:
        metadata = cached.metadata or {}
        return IBB_SOURCE.model_copy(
            update={
                "last_checked_at": cached.refreshed_at_iso,
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
            ttl_seconds=self.settings.ibb_pharmacy_cache_ttl_seconds,
        )

    def _warnings(self, cached: CachedSourceData) -> list[str]:
        warnings: list[str] = []
        if cached.is_stale:
            error_type = type(cached.error).__name__ if cached.error is not None else "UnknownError"
            warnings.append(
                f"İBB kaynağı yenilenemedi ({error_type}); son başarılı liste stale olarak gösteriliyor."
            )
        if any(row.get("duty_ends_at") is None for row in cached.value.rows):
            warnings.append("Kaynak nöbet bitiş zamanını vermedi; bitiş zamanı tahmin edilmedi.")
        metadata = cached.metadata or {}
        if metadata.get("geo_eligible_total", 0) < metadata.get("accepted_total", 0):
            warnings.append(
                "Kaynak bazı eczaneler için geçerli konum/koordinat vermedi; bu kayıtlar yakınlık sonuçlarına dahil edilmedi."
            )
        warnings.append(
            "Bu sonuçlar İBB Şehir Haritası'nın nöbetçi eczane listesidir; genel katalog, çalışma saati veya kesin nöbet bitiş garantisi değildir."
        )
        return warnings

    def _rate_limited(self, summary: str, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        retry_after = round(exc.retry_after_seconds, 3)
        return error_envelope(
            summary=f"{summary} kaynağı hız sınırına ulaştı.",
            warning=f"IBB pharmacy source rate limit exceeded; retry_after_seconds={retry_after:.1f}",
            sources=[IBB_SOURCE.model_copy(update={"coverage_status": "unavailable"})],
            data=[
                {
                    "error_code": "source_rate_limited",
                    "source": "ibb_pharmacy",
                    "retry_after_seconds": retry_after,
                }
            ],
            limits=["source=ibb_pharmacy", f"retry_after_seconds={retry_after:.1f}"],
        )

    def _source_error(self, summary: str, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary=summary,
            warning=f"IBB pharmacy source request failed: {type(exc).__name__}",
            sources=[IBB_SOURCE.model_copy(update={"coverage_status": "unavailable"})],
            exception=exc,
        )

    @staticmethod
    def _validate_coordinates(lat: float, lon: float) -> None:
        if isinstance(lat, bool) or not isinstance(lat, (int, float)) or not math.isfinite(float(lat)):
            raise InputValidationError("lat must be a finite number", field="lat")
        if isinstance(lon, bool) or not isinstance(lon, (int, float)) or not math.isfinite(float(lon)):
            raise InputValidationError("lon must be a finite number", field="lon")
        validate_lat_lon(float(lat), float(lon))

    def _validate_radius(self, radius_m: Any) -> int:
        if isinstance(radius_m, bool) or not isinstance(radius_m, int):
            raise InputValidationError("radius_m must be an integer", field="radius_m")
        return validate_radius(radius_m, min(self.settings.max_radius_m, IBB_MAX_RADIUS_M))

    def _validate_limit(self, limit: Any) -> int:
        value = min(self.settings.default_limit, IBB_MAX_LIMIT) if limit is None else limit
        if isinstance(value, bool) or not isinstance(value, int):
            raise InputValidationError("limit must be an integer", field="limit")
        return validate_limit(value, min(self.settings.max_limit, IBB_MAX_LIMIT))

    @staticmethod
    def _normalize_district(value: Any) -> str:
        normalized = normalize_place(str(value or ""))
        normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
        return " ".join(normalized.split())

    @staticmethod
    def _text_or_none(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _float_or_none(value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _valid_latitude(self, value: Any) -> float | None:
        coordinate = self._float_or_none(value)
        if coordinate is None or not math.isfinite(coordinate) or not -90 <= coordinate <= 90 or coordinate == 0:
            return None
        return coordinate

    def _valid_longitude(self, value: Any) -> float | None:
        coordinate = self._float_or_none(value)
        if coordinate is None or not math.isfinite(coordinate) or not -180 <= coordinate <= 180 or coordinate == 0:
            return None
        return coordinate
