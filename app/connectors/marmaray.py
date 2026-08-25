from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import transport_notice_rate_limiter


class MarmarayPayloadError(RuntimeError):
    pass


class _UrgentNoticeParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_seen = False
        self.empty_seen = False
        self.articles: list[dict[str, Any]] = []
        self.current: dict[str, Any] | None = None
        self.field: str | None = None
        self.buffer: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag == "main" and attributes.get("data-page") == "urgent-notices":
            self.page_seen = True
        if tag == "p" and "empty-state" in classes:
            self.empty_seen = True
        if tag == "article" and "urgent-notice" in classes:
            self.current = {
                "line_code": self._clean(attributes.get("data-line-code")),
                "route_label": self._clean(attributes.get("data-route-label")),
                "updated_at": None,
            }
        if self.current is not None and tag == "h2":
            self.field = "route_label"
            self.buffer = []
        elif self.current is not None and tag == "p" and "message" in classes:
            self.field = "message"
            self.buffer = []
        elif self.current is not None and tag == "time":
            self.current["updated_at"] = self._clean(attributes.get("datetime"))

    def handle_data(self, data: str) -> None:
        if self.current is not None and self.field is not None:
            self.buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if self.field is not None and tag in {"h2", "p"}:
            value = self._clean("".join(self.buffer))
            if value:
                self.current[self.field] = value
            self.field = None
            self.buffer = []
        if tag == "article":
            message = self._clean(self.current.get("message"))
            if not message:
                raise MarmarayPayloadError("Marmaray urgent notice article has no message")
            self.current["operator"] = "marmaray"
            self.current["mode"] = "suburban_rail"
            self.current["event_type"] = "announcement"
            self.current["message"] = message
            self.current = self._ordered_record(self.current)
            self.articles.append(self.current)
            self.current = None

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @staticmethod
    def _ordered_record(record: dict[str, Any]) -> dict[str, Any]:
        return {
            "operator": record["operator"],
            "mode": record["mode"],
            "line_code": record.get("line_code"),
            "route_label": record.get("route_label"),
            "event_type": record["event_type"],
            "message": record["message"],
            "updated_at": record.get("updated_at"),
        }


class MarmarayClient:
    def __init__(
        self,
        *,
        url: str = "https://www.tcddtasimacilik.gov.tr/marmaray/tr/son_dakika",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or transport_notice_rate_limiter()

    async def urgent_notices(self) -> list[dict[str, Any]]:
        html = await self._get_html()
        parser = _UrgentNoticeParser()
        parser.feed(html)
        parser.close()
        if not parser.page_seen:
            raise MarmarayPayloadError("Marmaray urgent notice page markup is unrecognized")
        if not parser.articles and not parser.empty_seen:
            raise MarmarayPayloadError("Marmaray urgent notice page markup is unrecognized")
        return parser.articles

    async def _get_html(self) -> str:
        await self._rate_limiter.acquire("marmaray")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    self.url,
                    rate_limiter=self._rate_limiter,
                    headers={"Accept": "text/html"},
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                self.url,
                rate_limiter=self._rate_limiter,
                headers={"Accept": "text/html"},
            )
        response.raise_for_status()
        return response.text
