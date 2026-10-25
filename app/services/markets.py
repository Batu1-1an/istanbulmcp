"""Weekly İBB market schedule; a published snapshot, not today's live opening."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from app.connectors.city_open_data import MARKET_RESOURCE_ID, CityOpenDataClient, OpenDataLayer, parse_market_coordinate
from app.core.envelope import Freshness, Source, result_info, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.geo import google_maps_url
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, resolve_limit, validate_text
from app.services.places import normalize_place

ISTANBUL = ZoneInfo("Europe/Istanbul")
DAY_NAMES = {
    "monday": ("Pazartesi", 0), "pazartesi": ("Pazartesi", 0),
    "tuesday": ("Salı", 1), "sali": ("Salı", 1),
    "wednesday": ("Çarşamba", 2), "carsamba": ("Çarşamba", 2),
    "thursday": ("Perşembe", 3), "persembe": ("Perşembe", 3),
    "friday": ("Cuma", 4), "cuma": ("Cuma", 4),
    "saturday": ("Cumartesi", 5), "cumartesi": ("Cumartesi", 5),
    "sunday": ("Pazar", 6), "pazar": ("Pazar", 6),
}
RELATIVE_DAYS = {"bugun": 0, "today": 0, "yarin": 1, "tomorrow": 1}
WEEKDAY_NAMES = ("Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar")
MARKET_SOURCE_NAME = "IBB Open Data Portal - Weekly markets"


def _fold(value: str) -> str:
    replacements = str.maketrans("ıİşŞçÇğĞüÜöÖ", "iis sccgguuoo".replace(" ", ""))
    return value.strip().casefold().translate(replacements)


def normalize_day(value: str | None, *, today: date | None = None) -> tuple[str | None, date | None]:
    if value is None:
        return None, None
    text = _fold(validate_text(value, field="day", max_length=30))
    current = today or datetime.now(ISTANBUL).date()
    if text in RELATIVE_DAYS:
        target = current + timedelta(days=RELATIVE_DAYS[text])
        return WEEKDAY_NAMES[target.weekday()], target
    try:
        target = date.fromisoformat(text)
    except ValueError:
        target = None
    if target is not None:
        if target.year < 2000 or target.year > 2100:
            raise InputValidationError("day must be between 2000 and 2100", field="day")
        return WEEKDAY_NAMES[target.weekday()], target
    if text not in DAY_NAMES:
        raise InputValidationError(
            "day must be a Turkish/English weekday, today/yesterday/tomorrow, or an ISO date",
            field="day",
        )
    return DAY_NAMES[text][0], None


class MarketService:
    def __init__(self, settings: Settings, *, client: CityOpenDataClient | None = None):
        self.settings = settings
        self.client = client or CityOpenDataClient(settings=settings)
        self.cache_key = "ibb_open_data.market.v1"

    async def schedule(
        self, *, district: str | None = None, day: str | None = None, limit: int | None = None,
    ) -> dict:
        try:
            max_limit = min(self.settings.max_limit, 100)
            safe_limit = resolve_limit(limit, min(50, max_limit), max_limit)
            safe_district = validate_text(district, field="district", max_length=80) if district is not None else None
            day_name, target_date = normalize_day(day)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[self._unavailable_source()])

        try:
            payload = await cached_source_data(
                self.cache_key,
                ttl_seconds=self.settings.open_data_layers_cache_ttl_seconds,
                loader=self.client.market,
            )
            rows, skipped = self._rows(payload, district=safe_district, day=day_name)
        except Exception as exc:
            return source_error_envelope(
                summary="Weekly market schedule is unavailable; no markets were verified.",
                warning=f"IBB market source failed ({type(exc).__name__}).",
                sources=[self._unavailable_source()],
                exception=exc,
            )

        matched = len(rows)
        rows = rows[:safe_limit]
        warnings = [
            "Weekly published market schedule; holidays, relocations and closures may differ. Verify locally before visiting.",
        ]
        if day_name is None:
            warnings.append("No day filter applied; results are the published weekly schedule, not today's open markets.")
        if skipped:
            warnings.append(f"{skipped} market row(s) had no usable Istanbul coordinate and were excluded.")
        label = f" in {safe_district}" if safe_district else ""
        if day_name:
            label += f" on {day_name}"
        source = self._source(payload, accepted=payload.received_total - skipped)
        return success_envelope(
            summary=f"{len(rows)} market(s) found{label}.",
            data=rows,
            result=result_info(returned=len(rows), matched=matched),
            sources=[source],
            freshness=Freshness(status="fresh", retrieved_at=payload.fetched_at or utc_now_iso(),
                                ttl_seconds=self.settings.open_data_layers_cache_ttl_seconds),
            limits=[
                f"limit={safe_limit}", "weekly_static_schedule", "search_window=published_week",
                f"day={day_name or 'all'}", f"date={target_date.isoformat() if target_date else 'not_applicable'}",
            ],
            warnings=warnings,
        )

    @staticmethod
    def _rows(payload: OpenDataLayer, *, district: str | None, day: str | None) -> tuple[list[dict[str, Any]], int]:
        wanted_district = normalize_place(district) if district else None
        rows: list[dict[str, Any]] = []
        skipped = 0
        for index, row in enumerate(payload.rows):
            point = parse_market_coordinate(row.get("Koordinat"))
            name = str(row.get("Pazar Adi") or "").strip()
            if point is None or not name:
                skipped += 1
                continue
            row_district = str(row.get("Ilce") or "").strip()
            if wanted_district and normalize_place(row_district) != wanted_district:
                continue
            row_day = str(row.get("Gun") or "").strip()
            if day and _fold(row_day) != _fold(day):
                continue
            lat, lon = point
            address = ", ".join(
                str(value).strip() for value in (row.get("Cadde"), row.get("Sokak")) if value
            )
            rows.append({
                "source": "ibb_open_data_market",
                "source_id": str(row.get("_id") or index),
                "market_name": name,
                "district": row_district,
                "neighborhood": row.get("Mahalle"),
                "day": row_day,
                "market_type": row.get("Pazar Tipi"),
                "address": address or None,
                "lat": lat,
                "lon": lon,
                "maps_url": google_maps_url(lat, lon),
            })
        rows.sort(key=lambda item: (normalize_place(item["district"]), normalize_place(item["neighborhood"] or ""), normalize_place(item["market_name"]), item["source_id"]))
        return rows, skipped

    @staticmethod
    def _source(payload: OpenDataLayer, *, accepted: int) -> Source:
        return Source(
            name=MARKET_SOURCE_NAME, resource_id=MARKET_RESOURCE_ID, url=payload.source_url,
            scope="complete_static_snapshot", reported_total=payload.reported_total,
            received_total=payload.received_total, accepted_total=accepted,
            skipped_total=payload.received_total - accepted,
            last_successful_refresh_at=payload.fetched_at,
        )

    @staticmethod
    def _unavailable_source() -> Source:
        return Source(
            name=MARKET_SOURCE_NAME, resource_id=MARKET_RESOURCE_ID, url="https://data.ibb.gov.tr",
            coverage_status="unavailable",
        )
