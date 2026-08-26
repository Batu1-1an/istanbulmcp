from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.connectors.metro import MetroClient, _normalize_token
from app.core.envelope import Freshness, Source, success_envelope, utc_now_iso
from app.core.error_responses import source_error_envelope
from app.core.settings import Settings
from app.core.source_cache import SourceLoadResult, cached_source_data_with_status, source_cache_snapshot
from app.core.validation import InputValidationError, validate_text

MAX_LIMIT = 100
DEFAULT_LIMIT = 50
MAX_TEXT_LENGTH = 100

KNOWN_EQUIPMENT_TYPES = {
    "line": "line",
    "station": "station",
    "entrance_exit": "entrance_exit",
    "escalator": "escalator",
    "moving_walkway": "moving_walkway",
    "elevator": "elevator",
    "restroom": "restroom",
    "prayer_room": "prayer_room",
    "baby_care_room": "baby_care_room",
    "accessible_platform": "accessible_platform",
}

# Human-readable (Turkish) equipment labels mapped to canonical keys for tolerance.
EQUIPMENT_LABEL_MAP = {
    "asansor": "elevator",
    "asansorler": "elevator",
    "yuruyen merdiven": "escalator",
    "yuruyen merdivenler": "escalator",
    "merdiven": "escalator",
    "yuruyen bant": "moving_walkway",
    "yuruyen bantlar": "moving_walkway",
    "giris cikis": "entrance_exit",
    "giris cikislar": "entrance_exit",
    "tuvalet": "restroom",
    "tuvaletler": "restroom",
    "mescit": "prayer_room",
    "bebek bakim odasi": "baby_care_room",
    "engelli platformu": "accessible_platform",
    "engelli platformlar": "accessible_platform",
    "platform": "accessible_platform",
}

ACCESSIBILITY_LIMIT = "not_an_end_to_end_accessibility_guarantee"
NO_ALTERNATIVE_ROUTE = "no_alternative_route_inferred"
NO_REPAIR_GUARANTEE = "no_repair_guarantee"

# Deterministic official line-code -> normalized label alias mapping so a code-only
# record (e.g. M2) also matches its normalized official route label (e.g. Yenikapı-
# Hacıosman). Unknown labels are preserved and never coerced to a code.
LINE_ALIASES: dict[str, tuple[str, ...]] = {
    "m1": ("yenikapi-haciosman", "yenikapi-otogar", "yenikapi-otogar-ataturk havalimani"),
    "m1a": ("otogar-ataturk havalimani", "yenikapi-otogar-ataturk havalimani"),
    "m2": ("yenikapi-haciosman",),
    "m3": ("kirazli-basaksehir",),
    "m4": ("kadikoy-sabiha gokcen", "kadikoy-istanbul havalimani"),
    "m5": ("uskudar-sancaktepe", "uskudar-samandira"),
    "m6": ("levent-bogazici universitesi",),
    "m7": ("yildiz-mahmutbey",),
    "m8": ("bostanci-parsel mahallesi",),
    "m9": ("atakoy-iktelli",),
}


def _line_alias_key(value: str) -> set[str]:
    """Return the normalized aliases for a line code or label (exact, no substring)."""
    norm = _normalize_token(value)
    result = {norm}
    result.update(_normalize_token(a) for a in LINE_ALIASES.get(norm, ()))
    return result


@dataclass(frozen=True)
class MetroAccessibilityQuery:
    line: str | None = None
    station: str | None = None
    equipment_type: str | None = None
    limit: int = DEFAULT_LIMIT


def validate_query(
    *,
    line: str | None,
    station: str | None,
    equipment_type: str | None,
    limit: int | None,
    default_limit: int = DEFAULT_LIMIT,
) -> MetroAccessibilityQuery:
    safe_line = validate_text(line, field="line", max_length=MAX_TEXT_LENGTH) if line is not None else None
    safe_station = validate_text(station, field="station", max_length=MAX_TEXT_LENGTH) if station is not None else None
    safe_equipment = validate_text(equipment_type, field="equipment_type", max_length=MAX_TEXT_LENGTH) if equipment_type is not None else None
    safe_limit = _validate_limit(default_limit if limit is None else limit)

    for value, field in ((safe_line, "line"), (safe_station, "station"), (safe_equipment, "equipment_type")):
        if value and "://" in value:
            raise InputValidationError(f"{field} must not contain a URL", field=field)
    return MetroAccessibilityQuery(
        line=safe_line,
        station=safe_station,
        equipment_type=safe_equipment,
        limit=safe_limit,
    )


def _validate_limit(value: int) -> int:
    if value <= 0:
        raise InputValidationError("limit must be positive", field="limit", allowed_min=1)
    if value > MAX_LIMIT:
        raise InputValidationError(f"limit must be <= {MAX_LIMIT}", field="limit", allowed_max=MAX_LIMIT)
    return value


class MetroAccessibilityService:
    def __init__(
        self,
        *,
        settings: Settings,
        metro_client: MetroClient | None = None,
    ) -> None:
        self.settings = settings
        self.metro = metro_client or MetroClient(timeout=settings.request_timeout_seconds)

    async def status(
        self,
        *,
        line: str | None = None,
        station: str | None = None,
        equipment_type: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            query = validate_query(line=line, station=station, equipment_type=equipment_type, limit=limit)
        except InputValidationError as exc:
            from app.core.error_responses import validation_error_envelope

            return validation_error_envelope(exc)

        checked_at = utc_now_iso()
        summary_task = self._load_summary()
        detail_task = self._load_details()

        summary_result, detail_result = await asyncio.gather(summary_task, detail_task)

        summary_source = self._source(
            scope="equipment_summary",
            coverage_status=summary_result.coverage_status,
            last_checked_at=checked_at,
            last_success=summary_result.last_successful_refresh_at,
            url=self.metro.equipment_summary_url,
            reported_total=summary_result.reported_total,
            message=summary_result.message,
        )
        detail_source = self._source(
            scope="fault_details",
            coverage_status=detail_result.coverage_status,
            last_checked_at=checked_at,
            last_success=detail_result.last_successful_refresh_at,
            url=self.metro.equipment_faults_url,
            reported_total=detail_result.received_total,
            message=detail_result.message,
        )

        warnings: list[str] = list(summary_result.warnings) + list(detail_result.warnings)
        frames: list[dict[str, Any]] = []

        summary_available = summary_result.value is not None
        detail_available = detail_result.value is not None

        summary_status = _source_status(summary_result)
        detail_status = _source_status(detail_result)

        if not summary_available and not detail_available:
            warning = "İki kaynak da kullanılamadı; güncel ekipman durumu alınamadı."
            for src in (summary_source, detail_source):
                pass  # sources already carry coverage_status=unavailable below
            response = source_error_envelope(
                summary="Her iki resmî Metro İstanbul kaynağı da kullanılamıyor.",
                warning=warning,
                sources=[summary_source, detail_source],
            )
            response["data"] = [
                {
                    "error_code": "source_unavailable",
                    "summary_source_status": summary_status,
                    "detail_source_status": detail_status,
                    "line": query.line,
                    "station": query.station,
                    "equipment_type": query.equipment_type,
                    "limit": query.limit,
                    "checked_scope": "none",
                    "summary_observed_at": summary_result.observed_at,
                    "details_observed_at": detail_result.observed_at,
                    "summary_last_successful_refresh_at": summary_result.last_successful_refresh_at,
                    "details_last_successful_refresh_at": detail_result.last_successful_refresh_at,
                }
            ]
            response["limits"] = [
                f"line={query.line}" if query.line else "line=none",
                f"station={query.station}" if query.station else "station=none",
                f"equipment_type={query.equipment_type}" if query.equipment_type else "equipment_type=none",
                f"requested_limit={query.limit}",
                "checked_scope=none",
                "scope=Metro İstanbul equipment status",
                ACCESSIBILITY_LIMIT,
                NO_ALTERNATIVE_ROUTE,
                NO_REPAIR_GUARANTEE,
            ]
            response["warnings"] = [warning]
            return response

        partial = not summary_available or not detail_available

        summary_rows = summary_result.value or []
        filtered_faults = self._filter_faults(
            detail_result.value or [],
            line=query.line,
            station=query.station,
            equipment_type=query.equipment_type,
        )
        faults = filtered_faults[: query.limit]

        category_overview = self._category_overview(summary_rows)
        frames.append(
            {
                "equipment_summary": category_overview,
                "faults": faults,
                "line": query.line,
                "station": query.station,
                "equipment_type": query.equipment_type,
                "limit": query.limit,
                "summary_source_status": summary_status,
                "detail_source_status": detail_status,
                "summary_observed_at": summary_result.observed_at,
                "details_observed_at": detail_result.observed_at,
                "summary_reported_total": summary_result.reported_total,
                "details_received_total": detail_result.received_total,
                "details_accepted_total": detail_result.accepted_total,
                "details_skipped_total": detail_result.skipped_total,
                "details_duplicate_total": detail_result.duplicate_total,
                "details_malformed_total": detail_result.malformed_detail_count,
                "details_matched_total": len(filtered_faults),
                "details_returned_total": len(faults),
            }
        )

        # Non-destructive discrepancy warning: compare source inactive totals with
        # the untruncated accepted detail scope BEFORE limiting. Emitted in both
        # mismatch directions while preserving both source values.
        if detail_available and summary_available:
            inactive_total = sum(row.get("inactive_count") or 0 for row in summary_rows)
            if inactive_total > 0 and detail_result.accepted_total == 0:
                warnings.append(
                    "positive_inactive_total_with_empty_details: Kavramsal toplamlar mevcut; "
                    "uzun/geçerli ayrıntı satırı yok."
                )
            elif inactive_total != detail_result.accepted_total:
                warnings.append(
                    "inactive_total_exceeds_detail_scope"
                    if inactive_total > detail_result.accepted_total
                    else "inactive_total_under_detail_scope",
                )

        if not summary_available and detail_available:
            warnings.append(
                "partial_source: Ekipman ayrıntıları korunuyor ancak resmî özet toplamları kullanılamıyor."
            )
        if not detail_available and summary_available:
            warnings.append(
                "partial_source: Resmî özet toplamları korunuyor ancak ekipman ayrıntıları kullanılamıyor."
            )

        if detail_result.stale:
            warnings.append(
                "stale_details: Güncel ayrıntı kontrolü başarısız; son gözlem sunuluyor."
            )
        if summary_result.stale:
            warnings.append(
                "stale_summary: Güncel özet kontrolü başarısız; son gözlem sunuluyor."
            )

        if detail_available:
            scoped = f"limit={query.limit}"
        else:
            scoped = "limit=n/a"

        limits = [
            f"line={query.line}" if query.line else "line=none",
            f"station={query.station}" if query.station else "station=none",
            f"equipment_type={query.equipment_type}" if query.equipment_type else "equipment_type=none",
            scoped,
            f"requested_limit={query.limit}",
            f"checked_scope=summary_and_details" if not partial else "checked_scope=partial",
            "scope=Metro İstanbul equipment status",
            ACCESSIBILITY_LIMIT,
            NO_ALTERNATIVE_ROUTE,
            NO_REPAIR_GUARANTEE,
        ]

        if partial:
            if summary_role := ("summary" if not summary_available else ""):
                limits.append(f"available={summary_detail_label(not detail_available, summary_role)}")
            limits.append(f"available=partial")
            freshness_status = "unknown"
            summary_text = "Kısmi kapsamla Metro İstanbul ekipman durumu kontrol edildi."
        elif not detail_available:
            # Both unavailable is handled above; this is when summary is the only usable source.
            freshness_status = "unknown"
            summary_text = "Kısmi kapsamla Metro İstanbul özet toplamları kontrol edildi."
        else:
            if summary_result.stale or detail_result.stale:
                freshness_status = "stale"
                summary_text = "Eski-veri ile Metro İstanbul ekipman durumu kontrol edildi."
            else:
                freshness_status = "fresh"
                summary_text = "Metro İstanbul ekipman durumu kontrol edildi."

        response = success_envelope(
            summary=summary_text,
            data=frames,
            sources=[summary_source, detail_source],
            freshness=Freshness(
                status=freshness_status,
                retrieved_at=checked_at,
                ttl_seconds=self.settings.metro_accessibility_cache_ttl_seconds,
            ),
            limits=limits,
            warnings=warnings,
        )
        return response

    async def _load_summary(self) -> "_SourceResult":
        async def load() -> SourceLoadResult:
            raw = await self.metro.equipment_summary()
            accepted = self._accepted_summary_rows(raw)
            return SourceLoadResult(
                value=accepted,
                metadata={"received_total": len(raw)},
                max_cache_age_seconds=float(
                    self.settings.metro_accessibility_stale_if_error_seconds
                ),
            )

        try:
            cached = await cached_source_data_with_status(
                "metro_accessibility.summary",
                ttl_seconds=self.settings.metro_accessibility_cache_ttl_seconds,
                loader=load,
                stale_if_error_seconds=self.settings.metro_accessibility_stale_if_error_seconds,
            )
            return self._source_result_from_cached(cached)
        except Exception as exc:
            # Even when the total-age cap forces an unavailable/broken response, the
            # last successful refresh time must be retained for provenance.
            return _SourceResult.unavailable(
                exception=exc,
                last_successful_refresh_at=_last_refresh_for("metro_accessibility.summary"),
            )

    async def _load_details(self) -> "_SourceResult":
        async def load() -> SourceLoadResult:
            raw = await self.metro.equipment_faults()
            malformed_detail_count = getattr(self.metro, "_last_malformed_detail_count", 0) or 0
            accepted, skipped, duplicate_total = self._accepted_fault_rows(raw)
            return SourceLoadResult(
                value=accepted,
                metadata={
                    "received_total": len(raw),
                    "skipped_total": skipped + malformed_detail_count,
                    "duplicate_total": duplicate_total,
                    "malformed_detail_count": malformed_detail_count,
                },
                max_cache_age_seconds=float(
                    self.settings.metro_accessibility_stale_if_error_seconds
                ),
            )

        try:
            cached = await cached_source_data_with_status(
                "metro_accessibility.details",
                ttl_seconds=self.settings.metro_accessibility_cache_ttl_seconds,
                loader=load,
                stale_if_error_seconds=self.settings.metro_accessibility_stale_if_error_seconds,
            )
            return self._detail_source_result_from_cached(cached)
        except Exception as exc:
            # Retain the last successful refresh time for provenance on broken results.
            return _SourceResult.unavailable(
                exception=exc,
                last_successful_refresh_at=_last_refresh_for("metro_accessibility.details"),
            )

    def _source_result_from_cached(self, cached: Any) -> "_SourceResult":
        value = list(cached.value)
        return _SourceResult(
            value=value,
            coverage_status="checked" if value is not None else "unavailable",
            observed_at=cached.refreshed_at_iso,
            last_successful_refresh_at=cached.refreshed_at_iso,
            reported_total=len(value),
            accepted_total=len(value),
            message=None,
            stale=cached.is_stale,
            warnings=[],
        )

    def _detail_source_result_from_cached(self, cached: Any) -> "_SourceResult":
        value = list(cached.value)
        for row in value:
            row.setdefault("observed_at", cached.refreshed_at_iso)
        received_total = cached.metadata.get("received_total") if cached.metadata else None
        skipped_total = cached.metadata.get("skipped_total", 0) if cached.metadata else 0
        duplicate_total = cached.metadata.get("duplicate_total", 0) if cached.metadata else 0
        malformed_detail_count = cached.metadata.get("malformed_detail_count", 0) if cached.metadata else 0
        warnings: list[str] = []
        if malformed_detail_count:
            warnings.append(
                f"schema_drift: {malformed_detail_count} ayrıntı satırı beklendik yapıyı taşımıyor."
            )
        return _SourceResult(
            value=value,
            coverage_status="checked" if value is not None else "unavailable",
            observed_at=cached.refreshed_at_iso,
            last_successful_refresh_at=cached.refreshed_at_iso,
            reported_total=received_total,
            received_total=received_total,
            accepted_total=len(value),
            skipped_total=skipped_total,
            duplicate_total=duplicate_total,
            malformed_detail_count=malformed_detail_count,
            message=None,
            stale=cached.is_stale,
            warnings=warnings,
        )

    @staticmethod
    def _accepted_summary_rows(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
        accepted: list[dict[str, Any]] = []
        for row in raw:
            category_name = row.get("category_name")
            if not category_name:
                continue
            accepted.append(row)
        return accepted

    def _accepted_fault_rows(self, raw: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int, int]:
        accepted_list: list[dict[str, Any]] = []
        skipped = 0
        for row in raw:
            if not row.get("station_name") and not row.get("equipment_type"):
                skipped += 1
                continue
            normalized = self._normalize_fault(row)
            if normalized is None:
                skipped += 1
                continue
            accepted_list.append(normalized)
        deduped = self._dedupe_faults(accepted_list)
        duplicate_total = len(accepted_list) - len(deduped)
        return deduped, skipped, duplicate_total

    @staticmethod
    def _normalize_fault(row: dict[str, Any]) -> dict[str, Any] | None:
        station_name = _token_or_none(row.get("station_name"))
        equipment_label = _token_or_none(row.get("equipment_type"))
        if station_name is None and equipment_label is None:
            return None
        normalized = dict(row)
        normalized["station_name"] = station_name
        # Map a known detail equipment label to its canonical output key while
        # preserving an unknown source label verbatim. The raw source label is kept
        # in equipment_type so an unknown label is not silently renamed.
        normalized["equipment_type"] = _canonical_equipment(equipment_label)
        return normalized

    @staticmethod
    def _dedupe_faults(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[tuple[Any, ...]] = set()
        unique: list[dict[str, Any]] = []
        for row in rows:
            identity = _fault_identity(row)
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(row)
        return unique

    def _filter_faults(
        self,
        rows: list[dict[str, Any]],
        *,
        line: str | None,
        station: str | None,
        equipment_type: str | None,
    ) -> list[dict[str, Any]]:
        line_keys = _line_alias_key(line) if line else None
        station_key = _normalize_token(station) if station else None
        equipment_key = _normalize_type_token(equipment_type) if equipment_type else None

        filtered: list[dict[str, Any]] = []
        for row in rows:
            if line_keys is not None:
                row_code = _normalize_token(row.get("line_code") or "")
                row_label = _normalize_token(row.get("line_label") or "")
                # Match if either the record code/label or any resolved alias intersects
                # the requested alias set (exact, deterministic, no substring match).
                row_keys = _line_alias_key(row_code) if row_code else set()
                if row_label:
                    row_keys.update(_line_alias_key(row_label))
                if not (row_keys & line_keys):
                    continue
            if station_key is not None and _normalize_token(row.get("station_name") or "") != station_key:
                continue
            if equipment_key is not None:
                row_equipment = _normalize_type_token(row.get("equipment_type") or "")
                if row_equipment != equipment_key:
                    continue
            filtered.append(row)

        filtered.sort(
            key=lambda row: (
                _sort_key(row.get("line_code") or ""),
                _sort_key(row.get("station_name") or ""),
                _sort_key(row.get("equipment_type") or ""),
                _sort_key(row.get("location_description") or ""),
                _sort_key(row.get("source_fault_id") or ""),
            )
        )
        return filtered

    @staticmethod
    def _category_overview(summary_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return list(summary_rows)

    @staticmethod
    def _source(
        *,
        scope: str,
        coverage_status: str,
        last_checked_at: str,
        last_success: str | None,
        url: str,
        reported_total: int | None,
        message: str | None = None,
    ) -> Source:
        name = (
            "Metro İstanbul Equipment Summary"
            if scope == "equipment_summary"
            else "Metro İstanbul Equipment Fault Details"
        )
        return Source(
            name=name,
            operator="metro_istanbul",
            coverage_kind="live_status",
            coverage_status=coverage_status,
            last_checked_at=last_checked_at,
            last_successful_refresh_at=last_success,
            scope=scope,
            url=url,
            reported_total=reported_total,
        )


def _source_status(result: "_SourceResult") -> str:
    if result.value is not None and not result.stale:
        return "fresh"
    if result.value is not None and result.stale:
        return "stale"
    return "unavailable"


def _sort_key(value: str) -> str:
    return _normalize_token(value)


def _fault_identity(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row.get("source_fault_id"),
        row.get("source_line_id"),
        row.get("source_station_id"),
        row.get("source_equipment_code"),
        row.get("line_code"),
        row.get("station_name"),
        row.get("equipment_type"),
        row.get("location_description"),
        row.get("reason"),
        row.get("expected_return"),
        row.get("status"),
    )


def _token_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _canonical_equipment(value: str | None) -> str | None:
    """Map a known detail equipment label to its canonical output key.

    Unknown source labels are preserved verbatim; only recognized labels are mapped.
    """
    if value is None:
        return None
    norm = _normalize_token(value)
    if norm in KNOWN_EQUIPMENT_TYPES:
        return KNOWN_EQUIPMENT_TYPES[norm]
    if norm in EQUIPMENT_LABEL_MAP:
        return EQUIPMENT_LABEL_MAP[norm]
    return value


def _normalize_type_token(value: str) -> str:
    norm = _normalize_token(value)
    if norm in KNOWN_EQUIPMENT_TYPES:
        return KNOWN_EQUIPMENT_TYPES[norm]
    if norm in EQUIPMENT_LABEL_MAP:
        return EQUIPMENT_LABEL_MAP[norm]
    return norm


def summary_detail_label(detail_unavailable: bool, summary_role: str) -> str:
    if detail_unavailable:
        return "details_unavailable"
    return "details_available"


@dataclass
class _SourceResult:
    value: list[dict[str, Any]] | None = None
    coverage_status: str = "unavailable"
    observed_at: str | None = None
    last_successful_refresh_at: str | None = None
    reported_total: int | None = None
    received_total: int | None = None
    accepted_total: int = 0
    skipped_total: int = 0
    duplicate_total: int = 0
    malformed_detail_count: int = 0
    message: str | None = None
    stale: bool = False
    warnings: list[str] = field(default_factory=list)

    @classmethod
    def unavailable(
        cls,
        *,
        exception: Exception | None = None,
        last_successful_refresh_at: str | None = None,
    ) -> "_SourceResult":
        return cls(
            coverage_status="unavailable",
            message=_exc_label(exception),
            last_successful_refresh_at=last_successful_refresh_at,
        )


def _exc_label(exception: Exception | None) -> str | None:
    if exception is None:
        return None
    return f"{type(exception).__name__}: {exception}"


def _last_refresh_for(cache_key: str) -> str | None:
    """Read the retained latest refresh time for a cache key from the cache snapshot.

    Used so a broken/unavailable result still carries the last successful refresh
    time for provenance, even after the total-age cap is exceeded.
    """
    # Mirror source_cache's label derivation (first two dot-separated segments).
    parts = cache_key.split(".")
    label = ".".join(parts[:2]) if len(parts) >= 2 else cache_key
    for row in source_cache_snapshot():
        if row.get("source") == label:
            return row.get("refreshed_at")
    return None
