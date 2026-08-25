from __future__ import annotations

from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import metro_rate_limiter


class MetroPayloadError(RuntimeError):
    pass


class MetroClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or metro_rate_limiter()

    async def stations(self) -> list[dict]:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/GetStations",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/GetStations",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            data = body.get("Data") or []
            if not isinstance(data, list):
                raise MetroPayloadError("Metro stations Data payload must be a list")
            return data
        if not isinstance(body, list):
            raise MetroPayloadError("Metro stations payload must be a list or object")
        return body

    async def service_statuses(self) -> list[dict[str, Any]]:
        body = await self._get_json("GetServiceStatuses")
        if not isinstance(body, dict):
            raise MetroPayloadError("Metro service statuses payload must be an object")
        success = body.get("Success", True)
        if success is False or str(success).lower() == "false":
            raise MetroPayloadError("Metro service statuses response was unsuccessful")
        data = body.get("Data") or body.get("data") or []
        if not isinstance(data, list):
            raise MetroPayloadError("Metro service statuses Data payload must be a list")

        normalized: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                raise MetroPayloadError("Metro service status row must be an object")
            line_code = self._text(
                row.get("LineCode")
                or row.get("LineCodeText")
                or row.get("lineCode")
                or row.get("HATKODU")
            )
            route_label = self._text(
                row.get("LineName")
                or row.get("lineName")
                or row.get("RouteName")
                or row.get("routeLabel")
                or row.get("HAT")
            )
            status = self._text(row.get("Status") or row.get("status") or row.get("Durum"))
            message = self._text(
                row.get("Description")
                or row.get("description")
                or row.get("Message")
                or row.get("message")
                or status
            )
            if not message or not line_code and not route_label:
                continue
            normalized.append(
                {
                    "operator": "metro_istanbul",
                    "mode": self._mode_for_line(line_code),
                    "line_code": line_code,
                    "route_label": route_label,
                    "event_type": self._event_type(status, row.get("EventType") or row.get("eventType")),
                    "message": message,
                    "updated_at": self._text(
                        row.get("UpdatedAt")
                        or row.get("updatedAt")
                        or row.get("UpdateTime")
                        or row.get("GuncellemeSaati")
                    ),
                }
            )
        return normalized

    async def _get_json(self, endpoint: str) -> Any:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/{endpoint}",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/{endpoint}",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _mode_for_line(line_code: str | None) -> str:
        code = (line_code or "").upper()
        if code.startswith("TF"):
            return "cable_car"
        if code.startswith("M"):
            return "metro"
        if code.startswith("T"):
            return "tram"
        if code.startswith("F"):
            return "funicular"
        return "unknown"

    @classmethod
    def _event_type(cls, status: Any, source_event_type: Any) -> str:
        source_type = cls._text(source_event_type)
        if source_type:
            return source_type
        value = (cls._text(status) or "").casefold()
        if "iptal" in value or "durdur" in value:
            return "cancellation"
        if "arıza" in value or "ariza" in value:
            return "disruption"
        if "değiş" in value or "degis" in value or "gecik" in value or "delay" in value:
            return "service_change"
        if "normal" in value or "çalış" in value or "calis" in value:
            return "operational"
        return "announcement"
