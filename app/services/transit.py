from __future__ import annotations

from typing import Any

from app.connectors.iett import IettClient
from app.core.envelope import Freshness, Source, error_envelope, success_envelope
from app.core.geo import google_maps_url
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, validate_line_code
from app.core.error_responses import validation_error_envelope
from app.storage.geo import GeoRepository

IETT_SOURCE = Source(
    name="IETT SOAP Services",
    publisher="Istanbul Metropolitan Municipality",
    url="https://api.ibb.gov.tr/iett",
)


class TransitService:
    def __init__(
        self,
        *,
        settings: Settings,
        iett_client: IettClient | None = None,
        geo_repository: GeoRepository | None = None,
    ):
        self.settings = settings
        self.iett = iett_client or IettClient(timeout=settings.request_timeout_seconds)
        self.geo = geo_repository or GeoRepository(settings.database_path)

    async def line_info(self, line_code: str) -> dict[str, Any]:
        try:
            safe_line_code = validate_line_code(line_code)
            rows = await self._line_info_rows(safe_line_code)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IETT_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("IETT line info", exc)
        except Exception as exc:
            return error_envelope(
                summary=f"IETT line info is unavailable for {safe_line_code}.",
                warning=f"IETT SOAP request failed: {type(exc).__name__}",
                sources=[IETT_SOURCE],
            )
        data = [
            {
                "line_code": row.get("SHATKODU") or row.get("HAT_KODU"),
                "line_name": row.get("SHATADI") or row.get("HAT_ADI"),
                "tariff": row.get("TARIFE"),
                "line_length_km": row.get("HAT_UZUNLUGU"),
                "trip_duration_min": row.get("SEFER_SURESI"),
            }
            for row in rows
        ]
        return success_envelope(
            summary=f"{len(data)} IETT line record(s) found for {safe_line_code}.",
            data=data,
            sources=[IETT_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["IETT SOAP may be unavailable during nightly maintenance."],
        )

    async def stops_for_line(self, line_code: str) -> dict[str, Any]:
        try:
            safe_line_code = validate_line_code(line_code)
            rows = await self._stops_for_line_rows(safe_line_code)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IETT_SOURCE])
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("IETT stops", exc)
        except Exception as exc:
            return error_envelope(
                summary=f"IETT stops are unavailable for line {safe_line_code}.",
                warning=f"IETT SOAP request failed: {type(exc).__name__}",
                sources=[IETT_SOURCE],
            )
        rows.sort(key=lambda row: (row.get("YON") or "", int(row.get("SIRANO") or 0)))
        data = [self._stop_row(row) for row in rows]
        self.geo.upsert_features([self._stop_feature(row) for row in data if row.get("lat") and row.get("lon")])
        return success_envelope(
            summary=f"{len(data)} stop record(s) found for line {safe_line_code}.",
            data=data,
            sources=[IETT_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["IETT SOAP may be unavailable during nightly maintenance."],
        )

    async def _line_info_rows(self, line_code: str) -> list[dict[str, Any]]:
        return await cached_source_data(
            f"iett.line_info.{line_code}",
            ttl_seconds=self.settings.iett_line_cache_ttl_seconds,
            loader=lambda: self.iett.line_info(line_code),
        )

    async def _stops_for_line_rows(self, line_code: str) -> list[dict[str, Any]]:
        return await cached_source_data(
            f"iett.stops_for_line.{line_code}",
            ttl_seconds=self.settings.iett_stops_cache_ttl_seconds,
            loader=lambda: self.iett.stops_for_line(line_code),
        )

    def _stop_row(self, row: dict[str, Any]) -> dict[str, Any]:
        lon = self._float_or_none(row.get("XKOORDINATI"))
        lat = self._float_or_none(row.get("YKOORDINATI"))
        stop = {
            "line_code": row.get("HATKODU"),
            "direction": row.get("YON"),
            "direction_name": (row.get("YON_ADI") or "").strip() or None,
            "sequence": int(row.get("SIRANO") or 0),
            "stop_code": row.get("DURAKKODU"),
            "stop_name": row.get("DURAKADI"),
            "lat": lat,
            "lon": lon,
            "district": row.get("ILCEADI"),
            "stop_type": row.get("DURAKTIPI"),
        }
        if maps_url := google_maps_url(lat, lon):
            stop["maps_url"] = maps_url
        return stop

    def _stop_feature(self, stop: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": f"iett_stop:{stop['stop_code']}",
            "source": "iett",
            "feature_type": "bus_stop",
            "source_id": stop["stop_code"],
            "name": stop.get("stop_name") or stop["stop_code"],
            "lat": stop["lat"],
            "lon": stop["lon"],
            "district": stop.get("district"),
            "properties": {
                "line_code": stop.get("line_code"),
                "direction": stop.get("direction"),
                "direction_name": stop.get("direction_name"),
                "sequence": stop.get("sequence"),
                "stop_type": stop.get("stop_type"),
            },
        }

    def _float_or_none(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        return float(value)

    def _rate_limited(self, action: str, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        retry_after = round(exc.retry_after_seconds, 3)
        return error_envelope(
            summary=f"{action} is temporarily rate limited.",
            warning=f"Local back-pressure is active for {exc.source}; retry after {retry_after} seconds.",
            sources=[IETT_SOURCE],
            freshness_status="stale",
            data=[{"source": exc.source, "retry_after_seconds": retry_after}],
            limits=[f"rate_limited_source={exc.source}", f"retry_after_seconds={retry_after}"],
        )
