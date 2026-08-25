from __future__ import annotations

import re
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
        announcements_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V3/GetAnnouncementsWithoutHtml/tr",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.announcements_url = announcements_url
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
            line_name = self._text(row.get("LineName") or row.get("lineName"))
            line_code = self._text(
                row.get("LineCode")
                or row.get("LineCodeText")
                or row.get("lineCode")
                or row.get("HATKODU")
                or (line_name if self._looks_like_line_code(line_name) else None)
            )
            route_label = self._text(
                row.get("LineLongDescription")
                or row.get("lineLongDescription")
                or row.get("RouteName")
                or row.get("routeLabel")
                or row.get("HAT")
                or (None if self._looks_like_line_code(line_name) else line_name)
            )
            status = self._text(row.get("Status") or row.get("status") or row.get("Durum"))
            message = self._text(
                row.get("Description")
                or row.get("description")
                or row.get("Message")
                or row.get("message")
                or status
            )
            is_active = self._bool(row.get("IsActive") if "IsActive" in row else row.get("isActive"))
            if is_active is False:
                continue
            if not message or not line_code and not route_label:
                continue
            source_event_type = row.get("EventType") or row.get("eventType")
            event_type = (
                "service_status"
                if is_active is True
                else self._event_type(status, source_event_type)
            )
            normalized.append(
                {
                    "operator": "metro_istanbul",
                    "mode": self._mode_for_line(line_code),
                    "line_code": line_code,
                    "route_label": route_label,
                    "event_type": event_type,
                    "message": message,
                    "updated_at": self._text(
                        row.get("UpdateDate")
                        or row.get("updateDate")
                        or row.get("UpdatedAt")
                        or row.get("updatedAt")
                        or row.get("UpdateTime")
                        or row.get("GuncellemeSaati")
                    ),
                }
            )
        return normalized

    async def announcements(self) -> list[dict[str, Any]]:
        """Return official Metro planned service notices from the V3 endpoint."""
        body = await self._get_json_url(self.announcements_url)
        if isinstance(body, list):
            rows = body
        elif isinstance(body, dict):
            rows = next(
                (body[key] for key in ("Data", "data", "Items", "items") if key in body),
                None,
            )
            if rows is None and "Result" in body:
                rows = body["Result"]
        else:
            rows = None
        if not isinstance(rows, list):
            raise MetroPayloadError("Metro announcements payload must be a list")

        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise MetroPayloadError("Metro announcement row must be an object")
            title = self._text(row.get("Title") or row.get("title"))
            content = self._text(row.get("Content") or row.get("content") or row.get("Description"))
            if not content:
                continue
            line_code = self._infer_line_code(title, content)
            route_label = self._infer_route_label(title, line_code)
            normalized.append(
                {
                    "operator": "metro_istanbul",
                    "mode": self._mode_for_line(line_code),
                    "line_code": line_code,
                    "route_label": route_label,
                    "event_type": "service_change",
                    "message": content,
                    "updated_at": self._text(row.get("StartDate") or row.get("startDate")),
                }
            )
        return normalized

    async def _get_json(self, endpoint: str) -> Any:
        return await self._get_json_url(f"{self.base_url}/{endpoint}")

    async def _get_json_url(self, url: str) -> Any:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    url,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
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
    def _bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().casefold()
        if text in {"true", "1", "yes", "evet"}:
            return True
        if text in {"false", "0", "no", "hayır", "hayir"}:
            return False
        return None

    @staticmethod
    def _looks_like_line_code(value: str | None) -> bool:
        return bool(value and re.fullmatch(r"(?:M|T|F|TF)\d+", value.strip(), flags=re.IGNORECASE))

    @classmethod
    def _infer_line_code(cls, title: str | None, content: str | None) -> str | None:
        match = re.search(r"\b((?:TF|M|T|F)\d+)\b", f"{title or ''} {content or ''}", flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def _infer_route_label(title: str | None, line_code: str | None) -> str | None:
        if not title:
            return None
        text = title.strip()
        if line_code:
            text = re.sub(rf"\b{re.escape(line_code)}\b\s*", "", text, flags=re.IGNORECASE).strip(" -:")
        match = re.search(
            r"([A-Za-zÇĞİÖŞÜçğıöşü]+\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü]+(?:\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü]+)?)",
            text,
        )
        return match.group(1).strip() if match else (text or None)

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
