from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
import unicodedata

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import transport_notice_rate_limiter


class SehirHatlariPayloadError(RuntimeError):
    pass


OFFICIAL_PAGE_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131.0 Safari/537.36",
}


class _CancellationParser(HTMLParser):
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
        if tag == "main" and attributes.get("data-page") == "cancelled-trips":
            self.page_seen = True
        if tag == "p" and "empty-state" in classes:
            self.empty_seen = True
        if tag == "article" and "cancelled-trip" in classes:
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
                raise SehirHatlariPayloadError("Sehir Hatlari cancellation article has no message")
            self.current["operator"] = "sehir_hatlari"
            self.current["mode"] = "ferry"
            self.current["event_type"] = "cancellation"
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


class _OfficialCancellationParser(HTMLParser):
    """Parse the current Şehir Hatları notice-detail HTML shape.

    The page is a WebForms document whose cancellation content is a single
    dated notice. It does not provide a trustworthy line identifier, so the
    alternate shape intentionally produces a global ferry record only.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_seen = False
        self.date_seen = False
        self.content_depth = 0
        self.date_depth = 0
        self.date_parts: list[str] = []
        self.message_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if self.content_depth:
            self.content_depth += 1
            if tag == "p" and "news-detail-date" in classes:
                self.date_depth = self.content_depth
                self.date_parts = []
            return
        if tag == "div" and "notice-detail-text-content" in classes:
            self.page_seen = True
            self.content_depth = 1

    def handle_data(self, data: str) -> None:
        if not self.content_depth:
            return
        if self.date_depth:
            self.date_parts.append(data)
        else:
            self.message_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.content_depth:
            return
        if self.date_depth == self.content_depth:
            self.date_seen = True
            self.date_depth = 0
        if tag == "div" and self.content_depth == 1:
            self.content_depth = 0
            return
        self.content_depth -= 1

    @property
    def date(self) -> str | None:
        return self._clean("".join(self.date_parts))

    @property
    def message(self) -> str | None:
        return self._clean(" ".join(self.message_parts))

    @staticmethod
    def _clean(value: Any) -> str | None:
        if value is None:
            return None
        text = " ".join(str(value).split())
        return text or None

    @staticmethod
    def is_explicit_empty(message: str) -> bool:
        folded = unicodedata.normalize("NFKD", message.casefold())
        folded = "".join(char for char in folded if not unicodedata.combining(char))
        folded = folded.replace("ı", "i")
        return any(
            phrase in folded
            for phrase in (
                "iptal seferimiz bulunmamaktadir",
                "iptal seferi bulunmamaktadir",
                "iptal sefer bulunmamaktadir",
            )
        )


class SehirHatlariClient:
    def __init__(
        self,
        *,
        url: str = "https://sehirhatlari.istanbul/tr/iptal-seferler",
        timeout: float = 15.0,
        relay_url: str | None = None,
        relay_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.url = url
        self.timeout = timeout
        self.relay_url = relay_url.rstrip("/") if relay_url else None
        self.relay_token = relay_token.strip() if relay_token else None
        self._client = http_client
        self._rate_limiter = rate_limiter or transport_notice_rate_limiter()

    async def cancellations(self) -> list[dict[str, Any]]:
        html = await self._get_html()
        parser = _CancellationParser()
        parser.feed(html)
        parser.close()
        if parser.page_seen:
            if not parser.articles and not parser.empty_seen:
                raise SehirHatlariPayloadError("Sehir Hatlari cancellation page markup is unrecognized")
            return parser.articles

        official_parser = _OfficialCancellationParser()
        official_parser.feed(html)
        official_parser.close()
        if not official_parser.page_seen or not official_parser.date_seen:
            raise SehirHatlariPayloadError("Sehir Hatlari cancellation page markup is unrecognized")
        message = official_parser.message
        if not message:
            raise SehirHatlariPayloadError("Sehir Hatlari official notice has no message")
        if _OfficialCancellationParser.is_explicit_empty(message):
            return []
        return [
            {
                "operator": "sehir_hatlari",
                "mode": "ferry",
                "line_code": None,
                "route_label": None,
                "event_type": "cancellation",
                "message": message,
                "updated_at": official_parser.date,
            }
        ]

    async def _get_html(self) -> str:
        await self._rate_limiter.acquire("sehir_hatlari")
        request_url = self.relay_url if self.relay_url and self.relay_token else self.url
        request_headers = dict(OFFICIAL_PAGE_HEADERS)
        if request_url == self.relay_url and self.relay_token:
            request_headers["Authorization"] = f"Bearer {self.relay_token}"

        try:
            response = await self._request(request_url, request_headers)
            response.raise_for_status()
        except httpx.HTTPStatusError:
            if request_url == self.url:
                raise
            response = await self._request(self.url, OFFICIAL_PAGE_HEADERS)
            response.raise_for_status()
        return response.text

    async def _request(self, url: str, headers: dict[str, str]) -> httpx.Response:
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await request_with_retries(
                    client,
                    "GET",
                    url,
                    rate_limiter=self._rate_limiter,
                    headers=headers,
                )
        return await request_with_retries(
            self._client,
            "GET",
            url,
            rate_limiter=self._rate_limiter,
            headers=headers,
        )
