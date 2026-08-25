from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from app.connectors.iett import IettClient
from app.connectors.marmaray import MarmarayClient
from app.connectors.metro import MetroClient
from app.connectors.sehir_hatlari import SehirHatlariClient
from app.core.envelope import Freshness, Source, success_envelope, utc_now_iso
from app.core.error_responses import validation_error_envelope
from app.core.settings import Settings
from app.core.source_cache import cached_source_data_with_status
from app.core.validation import InputValidationError, validate_limit, validate_text


SUPPORTED_MODES = (
    "bus",
    "metro",
    "tram",
    "funicular",
    "cable_car",
    "ferry",
    "suburban_rail",
)
SUPPORTED_OPERATORS = ("iett", "metro_istanbul", "sehir_hatlari", "marmaray")
UNSUPPORTED_OPERATORS_LIMIT = "unsupported_live_operators=İDO,Turyol,Dentur,minibus,taksi-dolmus"


@dataclass(frozen=True)
class _SourceSpec:
    key: str
    operator: str
    name: str
    publisher: str
    modes: tuple[str, ...]
    coverage_kind: str
    url: str
    fetch: Callable[[], Awaitable[list[dict[str, Any]]]]


class TransportDisruptionService:
    def __init__(
        self,
        *,
        settings: Settings,
        iett_client: IettClient | None = None,
        metro_client: MetroClient | None = None,
        sehir_hatlari_client: SehirHatlariClient | None = None,
        marmaray_client: MarmarayClient | None = None,
    ) -> None:
        self.settings = settings
        self.iett = iett_client or IettClient(timeout=settings.request_timeout_seconds)
        self.metro = metro_client or MetroClient(timeout=settings.request_timeout_seconds)
        self.sehir_hatlari = sehir_hatlari_client or SehirHatlariClient(timeout=settings.request_timeout_seconds)
        self.marmaray = marmaray_client or MarmarayClient(timeout=settings.request_timeout_seconds)

    async def disruptions(
        self,
        *,
        mode: str | None = None,
        operator: str | None = None,
        line: str | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_mode = self._normalize_choice(mode, field="mode", allowed=SUPPORTED_MODES)
            safe_operator = self._normalize_choice(operator, field="operator", allowed=SUPPORTED_OPERATORS)
            safe_line = validate_text(line, field="line", max_length=160) if line is not None else None
            safe_limit = validate_limit(
                self.settings.default_limit if limit is None else limit,
                self.settings.max_limit,
            )
            specs = self._select_specs(mode=safe_mode, operator=safe_operator)
        except InputValidationError as exc:
            return validation_error_envelope(exc)

        results = await asyncio.gather(*(self._read_source(spec) for spec in specs))
        sources = [result[0] for result in results]
        warnings = [result[1] for result in results if result[1] is not None]
        checked_count = sum(1 for source in sources if source.coverage_status == "checked")
        data = [row for _, _, rows in results for row in rows]
        data = self._filter_and_sort(data, mode=safe_mode, operator=safe_operator, line=safe_line)
        data = data[:safe_limit]

        unavailable_count = len(specs) - checked_count
        if unavailable_count == len(specs):
            summary = "İstenen resmî ulaşım kaynakları kullanılamıyor."
            freshness_status = "broken"
        elif unavailable_count:
            summary = f"Kısmi kapsamla {len(data)} güncel ulaşım aksaklığı kaydı bulundu."
            freshness_status = "unknown"
        elif data:
            summary = f"{len(data)} güncel ulaşım aksaklığı kaydı bulundu."
            freshness_status = "fresh"
        else:
            summary = "kontrol edilen resmî kaynaklarda güncel ulaşım aksaklığı kaydı yok."
            freshness_status = "fresh"

        response = success_envelope(
            summary=summary,
            data=data,
            sources=sources,
            freshness=Freshness(
                status=freshness_status,
                ttl_seconds=self.settings.transport_disruptions_cache_ttl_seconds,
            ),
            limits=[
                f"limit={safe_limit}",
                "scope=official_transport_status_and_announcements",
                UNSUPPORTED_OPERATORS_LIMIT,
            ],
            warnings=warnings,
        )
        if unavailable_count == len(specs):
            response["ok"] = False
        return response

    def _select_specs(self, *, mode: str | None, operator: str | None) -> list[_SourceSpec]:
        specs = self._source_specs()
        selected = [
            spec
            for spec in specs
            if (operator is None or spec.operator == operator)
            and (mode is None or mode in spec.modes)
        ]
        if not selected:
            raise InputValidationError(
                "operator and mode do not describe a compatible official source",
                field="operator",
            )
        return selected

    def _source_specs(self) -> list[_SourceSpec]:
        return [
            _SourceSpec(
                key="iett",
                operator="iett",
                name="IETT SOAP Services",
                publisher="Istanbul Metropolitan Municipality",
                modes=("bus",),
                coverage_kind="live_status",
                url=getattr(self.iett, "duyurular_url", "https://api.ibb.gov.tr/iett/UlasimDinamikVeri/Duyurular.asmx"),
                fetch=self.iett.disruptions,
            ),
            _SourceSpec(
                key="metro_istanbul",
                operator="metro_istanbul",
                name="Metro İstanbul Service Status",
                publisher="Metro İstanbul",
                modes=("metro", "tram", "funicular", "cable_car"),
                coverage_kind="live_status",
                url=f"{getattr(self.metro, 'base_url', 'https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2').rstrip('/')}/GetServiceStatuses",
                fetch=self.metro.service_statuses,
            ),
            _SourceSpec(
                key="sehir_hatlari",
                operator="sehir_hatlari",
                name="Şehir Hatları İptal Seferler",
                publisher="Şehir Hatları",
                modes=("ferry",),
                coverage_kind="official_announcements",
                url=getattr(self.sehir_hatlari, "url", "https://sehirhatlari.istanbul/tr/iptal-seferler"),
                fetch=self.sehir_hatlari.cancellations,
            ),
            _SourceSpec(
                key="marmaray",
                operator="marmaray",
                name="Marmaray Son Dakika",
                publisher="TCDD Taşımacılık A.Ş.",
                modes=("suburban_rail",),
                coverage_kind="official_announcements",
                url=getattr(self.marmaray, "url", "https://www.tcddtasimacilik.gov.tr/marmaray/tr/son_dakika"),
                fetch=self.marmaray.urgent_notices,
            ),
        ]

    async def _read_source(
        self,
        spec: _SourceSpec,
    ) -> tuple[Source, str | None, list[dict[str, Any]]]:
        checked_at = utc_now_iso()

        async def load() -> list[dict[str, Any]]:
            raw_rows = await spec.fetch()
            return self._normalize_rows(spec, raw_rows)

        try:
            cached = await cached_source_data_with_status(
                f"transport_disruptions.{spec.key}",
                ttl_seconds=self.settings.transport_disruptions_cache_ttl_seconds,
                loader=load,
            )
            source = self._source(
                spec,
                coverage_status="checked",
                last_checked_at=cached.refreshed_at_iso or checked_at,
            )
            return source, None, list(cached.value)
        except Exception as exc:
            source = self._source(
                spec,
                coverage_status="unavailable",
                last_checked_at=checked_at,
            )
            warning = f"{spec.operator} kaynağı kullanılamadı: {type(exc).__name__}."
            return source, warning, []

    @staticmethod
    def _source(
        spec: _SourceSpec,
        *,
        coverage_status: str,
        last_checked_at: str,
    ) -> Source:
        return Source(
            name=spec.name,
            publisher=spec.publisher,
            operator=spec.operator,
            modes=list(spec.modes),
            coverage_kind=spec.coverage_kind,
            coverage_status=coverage_status,
            last_checked_at=last_checked_at,
            url=spec.url,
        )

    def _normalize_rows(self, spec: _SourceSpec, rows: Any) -> list[dict[str, Any]]:
        if not isinstance(rows, list):
            raise ValueError(f"{spec.operator} disruption payload must be a list")
        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(f"{spec.operator} disruption row must be an object")
            if spec.operator == "iett":
                record = {
                    "operator": "iett",
                    "mode": "bus",
                    "line_code": self._text(row.get("HATKODU") or row.get("HAT_KODU")),
                    "route_label": self._text(row.get("HAT") or row.get("HAT_ADI")),
                    "event_type": self._text(row.get("TIP") or row.get("TUR")) or "announcement",
                    "message": self._text(row.get("MESAJ") or row.get("MESSAGE")),
                    "updated_at": self._text(row.get("GUNCELLEME_SAATI") or row.get("UPDATED_AT")),
                }
            else:
                record = {
                    "operator": self._text(row.get("operator")) or spec.operator,
                    "mode": self._text(row.get("mode")) or (spec.modes[0] if len(spec.modes) == 1 else "unknown"),
                    "line_code": self._text(row.get("line_code")),
                    "route_label": self._text(row.get("route_label")),
                    "event_type": self._text(row.get("event_type")) or "announcement",
                    "message": self._text(row.get("message")),
                    "updated_at": self._text(row.get("updated_at")),
                }
            if record["message"]:
                normalized.append(record)
        return normalized

    @classmethod
    def _filter_and_sort(
        cls,
        rows: list[dict[str, Any]],
        *,
        mode: str | None,
        operator: str | None,
        line: str | None,
    ) -> list[dict[str, Any]]:
        filtered = []
        line_key = line.casefold() if line is not None else None
        for row in rows:
            if row["event_type"] == "operational":
                continue
            if mode is not None and row["mode"] != mode:
                continue
            if operator is not None and row["operator"] != operator:
                continue
            if line_key is not None and not any(
                value is not None and value.casefold() == line_key
                for value in (row.get("line_code"), row.get("route_label"))
            ):
                continue
            filtered.append(row)

        seen: set[tuple[Any, ...]] = set()
        unique: list[dict[str, Any]] = []
        for row in filtered:
            identity = tuple(row.get(field) for field in (
                "operator",
                "mode",
                "line_code",
                "route_label",
                "event_type",
                "message",
                "updated_at",
            ))
            if identity in seen:
                continue
            seen.add(identity)
            unique.append(row)
        unique.sort(
            key=lambda row: (
                row["operator"],
                row["mode"],
                row.get("line_code") or "",
                row.get("route_label") or "",
                row["event_type"],
                row["message"],
                row.get("updated_at") or "",
            )
        )
        return unique

    @staticmethod
    def _normalize_choice(value: str | None, *, field: str, allowed: tuple[str, ...]) -> str | None:
        if value is None:
            return None
        safe = validate_text(value, field=field, max_length=80).casefold()
        for option in allowed:
            if option.casefold() == safe:
                return option
        raise InputValidationError(
            f"{field} must be one of: {', '.join(allowed)}",
            field=field,
        )

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None
