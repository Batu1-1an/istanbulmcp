from __future__ import annotations

from typing import Any

from app.connectors.iett import IettClient
from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import Settings
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
        rows = await self.iett.line_info(line_code.strip().upper())
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
            summary=f"{len(data)} IETT line record(s) found for {line_code}.",
            data=data,
            sources=[IETT_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["IETT SOAP may be unavailable during nightly maintenance."],
        )

    async def stops_for_line(self, line_code: str) -> dict[str, Any]:
        rows = await self.iett.stops_for_line(line_code.strip().upper())
        rows.sort(key=lambda row: (row.get("YON") or "", int(row.get("SIRANO") or 0)))
        data = [self._stop_row(row) for row in rows]
        self.geo.upsert_features([self._stop_feature(row) for row in data if row.get("lat") and row.get("lon")])
        return success_envelope(
            summary=f"{len(data)} stop record(s) found for line {line_code}.",
            data=data,
            sources=[IETT_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["IETT SOAP may be unavailable during nightly maintenance."],
        )

    def _stop_row(self, row: dict[str, Any]) -> dict[str, Any]:
        lon = self._float_or_none(row.get("XKOORDINATI"))
        lat = self._float_or_none(row.get("YKOORDINATI"))
        return {
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
