from __future__ import annotations

from typing import Any
import unicodedata
from urllib.parse import urlparse

import httpx

from app.connectors.sehir_hatlari import SehirHatlariClient
from app.core.envelope import Freshness, Source, error_envelope, success_envelope, utc_now_iso
from app.core.error_responses import validation_error_envelope
from app.core.settings import Settings
from app.core.source_cache import cached_source_data_with_status
from app.core.validation import InputValidationError, validate_limit, validate_text


STATIC_TIMETABLE_LIMIT = "scope=published_static_timetable_not_live_departures_or_eta"


class FerryScheduleService:
    def __init__(self, *, settings: Settings, client: SehirHatlariClient | None = None) -> None:
        self.settings = settings
        self.client = client or SehirHatlariClient(timeout=settings.request_timeout_seconds)

    async def schedules(self, *, route: str, limit: int | None = None) -> dict[str, Any]:
        try:
            safe_route = validate_text(route, field="route", max_length=160)
            safe_limit = validate_limit(
                self.settings.ferry_schedule_default_limit if limit is None else limit,
                self.settings.ferry_schedule_max_limit,
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc)

        checked_at = utc_now_iso()
        index_url = getattr(self.client, "schedule_index_url", "https://sehirhatlari.istanbul/tr/seferler")
        try:
            catalog_cached = await cached_source_data_with_status(
                "ferry_schedules.catalog",
                ttl_seconds=self.settings.ferry_schedule_cache_ttl_seconds,
                loader=self.client.schedule_catalog,
            )
            catalog = catalog_cached.value
            index_url = getattr(self.client, "last_schedule_index_url", index_url)
        except Exception as exc:
            source = self._source(
                name="Şehir Hatları Published Timetable Index",
                url=index_url,
                coverage_status="unavailable",
                last_checked_at=checked_at,
            )
            return error_envelope(
                summary="Şehir Hatları tarife indeksi kullanılamıyor.",
                warning=f"Şehir Hatları tarife indeks kaynağı kullanılamadı: {self._error_detail(exc)}.",
                sources=[source],
                freshness_status="broken",
                limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}"],
            )

        if not isinstance(catalog, list):
            source = self._source(
                name="Şehir Hatları Published Timetable Index",
                url=index_url,
                coverage_status="unavailable",
                last_checked_at=checked_at,
            )
            return error_envelope(
                summary="Şehir Hatları tarife indeksi bozuk.",
                warning="Şehir Hatları tarife indeksi beklenen liste biçiminde değil.",
                sources=[source],
                freshness_status="broken",
                limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}"],
            )

        catalog_source_url = next(
            (
                item.get("source_url")
                for item in catalog
                if isinstance(item, dict) and isinstance(item.get("source_url"), str)
            ),
            None,
        )
        if catalog_source_url:
            index_url = catalog_source_url

        index_source = self._source(
            name="Şehir Hatları Published Timetable Index",
            url=index_url,
            coverage_status="checked",
            last_checked_at=catalog_cached.refreshed_at_iso or checked_at,
        )
        match = next(
            (
                item
                for item in catalog
                if isinstance(item, dict)
                and self._normalize_route(item.get("route_label")) == self._normalize_route(safe_route)
            ),
            None,
        )
        if match is None:
            return success_envelope(
                summary="Şehir Hatları tarife indeksinde eşleşen rota bulunamadı.",
                data=[],
                sources=[index_source],
                freshness=Freshness(
                    status="fresh",
                    retrieved_at=catalog_cached.refreshed_at_iso or checked_at,
                    ttl_seconds=self.settings.ferry_schedule_cache_ttl_seconds,
                ),
                limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}", "route_match=exact_casefold"],
                warnings=["Tarife sonucu yayımlanmış statik plandır; canlı kalkış veya ETA değildir."],
            )

        detail_url = match.get("detail_url")
        if not isinstance(detail_url, str) or not self._is_allowed_detail_url(detail_url, index_url):
            detail_source = self._source(
                name="Şehir Hatları Published Timetable Detail",
                url=detail_url if isinstance(detail_url, str) else None,
                coverage_status="unavailable",
                last_checked_at=checked_at,
            )
            return error_envelope(
                summary="Şehir Hatları tarife rota bağlantısı geçersiz.",
                warning="Tarife detay bağlantısı resmî HTTPS URL'si değil.",
                sources=[index_source, detail_source],
                freshness_status="unknown",
                limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}"],
            )

        cache_key = f"ferry_schedules.detail.{detail_url}"
        try:
            detail_cached = await cached_source_data_with_status(
                cache_key,
                ttl_seconds=self.settings.ferry_schedule_cache_ttl_seconds,
                loader=lambda: self.client.schedule_for_route(
                    detail_url,
                    route_label=str(match.get("route_label") or safe_route),
                ),
            )
            rows = detail_cached.value
        except Exception as exc:
            detail_source = self._source(
                name="Şehir Hatları Published Timetable Detail",
                url=detail_url,
                coverage_status="unavailable",
                last_checked_at=checked_at,
            )
            return error_envelope(
                summary="Şehir Hatları tarife detay sayfası kullanılamıyor.",
                warning=f"Şehir Hatları tarife detay kaynağı kullanılamadı: {self._error_detail(exc)}.",
                sources=[index_source, detail_source],
                freshness_status="unknown",
                limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}"],
            )

        if not isinstance(rows, list):
            raise ValueError("ferry schedule detail payload must be a list")
        data = self._stable_rows(rows)[:safe_limit]
        detail_source = self._source(
            name="Şehir Hatları Published Timetable Detail",
            url=detail_url,
            coverage_status="checked",
            last_checked_at=detail_cached.refreshed_at_iso or checked_at,
        )
        return success_envelope(
            summary=f"{len(data)} yayımlanmış Şehir Hatları tarife kaydı bulundu.",
            data=data,
            sources=[index_source, detail_source],
            freshness=Freshness(
                status="fresh",
                retrieved_at=detail_cached.refreshed_at_iso or checked_at,
                ttl_seconds=self.settings.ferry_schedule_cache_ttl_seconds,
            ),
            limits=[STATIC_TIMETABLE_LIMIT, f"limit={safe_limit}", "route_match=exact_casefold"],
            warnings=["Tarife sonucu yayımlanmış statik plandır; canlı kalkış, gecikme veya ETA değildir."],
        )

    @staticmethod
    def _normalize_route(value: Any) -> str:
        folded = unicodedata.normalize("NFKD", str(value or "").casefold())
        folded = "".join(char for char in folded if not unicodedata.combining(char)).replace("ı", "i")
        return " ".join(folded.split())

    @staticmethod
    def _stable_rows(rows: list[Any]) -> list[dict[str, Any]]:
        unique: dict[tuple[Any, ...], dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError("ferry schedule row must be an object")
            required = (
                row.get("route_label"),
                row.get("stop_name"),
                row.get("direction"),
                row.get("day_type"),
                row.get("planned_departure_time"),
            )
            if not all(required):
                raise ValueError("ferry schedule row is missing a required field")
            key = required + (row.get("stop_sequence"),)
            unique.setdefault(key, row)
        return sorted(
            unique.values(),
            key=lambda row: (
                str(row.get("route_label") or ""),
                str(row.get("day_type") or ""),
                str(row.get("direction") or ""),
                int(row.get("stop_sequence") or 0),
                str(row.get("stop_name") or ""),
                str(row.get("planned_departure_time") or ""),
            ),
        )

    @staticmethod
    def _source(
        *,
        name: str,
        url: str | None,
        coverage_status: str,
        last_checked_at: str,
    ) -> Source:
        return Source(
            name=name,
            publisher="Şehir Hatları",
            operator="sehir_hatlari",
            modes=["ferry"],
            coverage_kind="published_timetable",
            coverage_status=coverage_status,  # type: ignore[arg-type]
            last_checked_at=last_checked_at,
            url=url,
        )

    @staticmethod
    def _error_detail(exc: Exception) -> str:
        if isinstance(exc, httpx.HTTPStatusError):
            return f"{type(exc).__name__} (HTTP {exc.response.status_code})"
        return type(exc).__name__

    @staticmethod
    def _is_allowed_detail_url(detail_url: str, index_url: str) -> bool:
        detail = urlparse(detail_url)
        index = urlparse(index_url)
        if detail.scheme != "https" or not detail.hostname:
            return False
        if index.hostname in {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}:
            return detail.hostname in {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}
        return detail.hostname == index.hostname
