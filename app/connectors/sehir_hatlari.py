from __future__ import annotations

from html.parser import HTMLParser
from typing import Any
import re
from urllib.parse import urljoin, urlparse
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


class _ScheduleCatalogParser(HTMLParser):
    """Collect canonical route links from the official tariff index."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._href: str | None = None
        self._parts: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        href = dict(attrs).get("href")
        if href:
            self._href = href.strip()
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        label = _clean_text("".join(self._parts))
        if label:
            self.links.append((self._href, label))
        self._href = None
        self._parts = []


class _ScheduleDetailParser(HTMLParser):
    """Parse the published timetable tables used by Şehir Hatları route pages."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.page_title: str | None = None
        self._heading_parts: list[str] = []
        self._heading_tag: str | None = None
        self._table: dict[str, Any] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []
        self.tables: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if tag in {"h1", "h2"} and self._heading_tag is None:
            self._heading_tag = tag
            self._heading_parts = []
        if tag == "table" and "single-table" in classes:
            self._table = {"info": "", "stop_name": None, "times": []}
        if self._table is None:
            return
        if tag == "td" and "table-head-information" in classes:
            self._capture = "info"
            self._parts = []
        elif tag == "th":
            self._capture = "stop"
            self._parts = []
        elif tag == "tr" and "hours-tr" in classes:
            self._capture = "time"
            self._parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_tag is not None:
            self._heading_parts.append(data)
        if self._capture is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._heading_tag == tag:
            if self.page_title is None:
                self.page_title = _clean_text("".join(self._heading_parts))
            self._heading_tag = None
            self._heading_parts = []
        if self._table is None:
            return
        if self._capture == "info" and tag == "td":
            self._table["info"] = _clean_text("".join(self._parts)) or ""
            self._capture = None
            self._parts = []
        elif self._capture == "stop" and tag == "th":
            self._table["stop_name"] = _clean_text("".join(self._parts))
            self._capture = None
            self._parts = []
        elif self._capture == "time" and tag == "tr":
            raw = _clean_text("".join(self._parts))
            if raw:
                match = re.search(r"\b(\d{1,2}:\d{2})\b", raw)
                if match:
                    self._table["times"].append(
                        {"time": match.group(1), "note": raw[len(match.group(1)):].strip() or None}
                    )
            self._capture = None
            self._parts = []
        if tag == "table":
            if self._table.get("stop_name") and self._table.get("times"):
                self.tables.append(self._table)
            self._table = None


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _normalized_route(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char)).replace("ı", "i")
    return " ".join(folded.split())


def _day_type(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold())
    folded = "".join(char for char in folded if not unicodedata.combining(char))
    if "her gun" in folded:
        return "all_days"
    if "cumartesi" in folded:
        return "saturday"
    if "pazar" in folded:
        return "sunday"
    if "resmi tatil" in folded or "resm tatil" in folded:
        return "holiday"
    if "hafta ici" in folded:
        return "weekday"
    return "unknown"


class SehirHatlariClient:
    def __init__(
        self,
        *,
        url: str = "https://sehirhatlari.istanbul/tr/iptal-seferler",
        schedule_index_url: str = "https://sehirhatlari.istanbul/tr/seferler",
        timeout: float = 15.0,
        relay_url: str | None = None,
        relay_token: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self.url = url
        self.schedule_index_url = schedule_index_url
        self.timeout = timeout
        self.relay_url = relay_url.rstrip("/") if relay_url else None
        self.relay_token = relay_token.strip() if relay_token else None
        self._client = http_client
        self._rate_limiter = rate_limiter or transport_notice_rate_limiter()
        self.last_schedule_index_url: str = "https://sehirhatlari.istanbul/tr/seferler"

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

        last_error: Exception | None = None
        candidates = [request_url]
        if request_url != self.url:
            candidates.append(self.url)
        candidates.extend(candidate for candidate in self._cancellation_candidates() if candidate not in candidates)
        for candidate in candidates:
            try:
                headers = request_headers if candidate == request_url else OFFICIAL_PAGE_HEADERS
                response = await self._request(candidate, headers)
                response.raise_for_status()
                return response.text
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise SehirHatlariPayloadError("Şehir Hatları cancellation source has no URL candidates")

    def _cancellation_candidates(self) -> list[str]:
        parsed = urlparse(self.url)
        if parsed.hostname not in {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}:
            return [self.url]
        return [
            "https://www.sehirhatlari.istanbul/tr/iptal-seferler",
            "https://sehirhatlari.istanbul/tr/iptal-seferler",
            "https://sehirhatlari.istanbul/tr/duyurular/iptal-seferler-905",
        ]

    def _schedule_candidates(self, url: str) -> list[str]:
        parsed = urlparse(url)
        if parsed.hostname not in {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}:
            return [url]
        path = parsed.path or "/"
        return [
            f"https://www.sehirhatlari.istanbul{path}",
            f"https://sehirhatlari.istanbul{path}",
        ]

    def _is_allowed_schedule_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            return False
        configured_host = urlparse(self.schedule_index_url).hostname
        if configured_host in {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}:
            allowed_hosts = {"sehirhatlari.istanbul", "www.sehirhatlari.istanbul"}
        else:
            allowed_hosts = {configured_host}
        return parsed.hostname in allowed_hosts

    async def _get_schedule_html(self, url: str) -> tuple[str, str]:
        if not self._is_allowed_schedule_url(url):
            raise SehirHatlariPayloadError("Şehir Hatları schedule URL is outside the canonical operator scope")
        last_error: Exception | None = None
        for candidate in self._schedule_candidates(url):
            try:
                response = await self._request(candidate, OFFICIAL_PAGE_HEADERS)
                response.raise_for_status()
                return response.text, candidate
            except Exception as exc:
                last_error = exc
        if last_error is not None:
            raise last_error
        raise SehirHatlariPayloadError("Şehir Hatları schedule source has no URL candidates")

    async def schedule_catalog(self) -> list[dict[str, str]]:
        """Resolve published route labels to canonical official detail URLs."""
        html, source_url = await self._get_schedule_html(self.schedule_index_url)
        self.last_schedule_index_url = source_url
        parser = _ScheduleCatalogParser()
        parser.feed(html)
        parser.close()
        routes: list[dict[str, str]] = []
        seen: set[str] = set()
        for href, label in parser.links:
            detail_url = urljoin(source_url, href)
            parsed = urlparse(detail_url)
            path_parts = [part for part in parsed.path.split("/") if part]
            if not self._is_allowed_schedule_url(detail_url) or len(path_parts) < 5 or "seferler" not in path_parts:
                continue
            if detail_url in seen:
                continue
            seen.add(detail_url)
            routes.append(
                {
                    "route_label": label,
                    "detail_url": detail_url,
                    "source_url": source_url,
                }
            )
        if not routes:
            raise SehirHatlariPayloadError("Sehir Hatlari schedule index markup is unrecognized")
        return routes

    async def schedule_for_route(
        self,
        detail_url: str,
        *,
        route_label: str | None = None,
    ) -> list[dict[str, Any]]:
        """Parse published timetable rows from one canonical route detail page."""
        html, source_url = await self._get_schedule_html(detail_url)
        parser = _ScheduleDetailParser()
        parser.feed(html)
        parser.close()
        if not parser.tables:
            raise SehirHatlariPayloadError("Sehir Hatlari schedule detail markup is unrecognized")
        label = self._route_label_from_heading(parser.page_title) or route_label
        if not label:
            raise SehirHatlariPayloadError("Sehir Hatlari schedule detail has no route label")
        endpoints = [part.strip() for part in re.split(r"\s+-\s+", label) if part.strip()]
        rows: list[dict[str, Any]] = []
        for table in parser.tables:
            stop_name = table["stop_name"]
            direction = None
            if len(endpoints) == 2 and _normalized_route(stop_name) == _normalized_route(endpoints[0]):
                direction = endpoints[1]
            elif len(endpoints) == 2 and _normalized_route(stop_name) == _normalized_route(endpoints[1]):
                direction = endpoints[0]
            day_type = _day_type(table.get("info") or "")
            for item in table["times"]:
                row = {
                    "operator": "sehir_hatlari",
                    "mode": "ferry",
                    "route_label": label,
                    "stop_name": stop_name,
                    "direction": direction,
                    "day_type": day_type,
                    "planned_departure_time": item["time"],
                    "stop_sequence": 1,
                    "source_url": source_url,
                    "source_updated_at": None,
                }
                if item.get("note"):
                    row["schedule_note"] = item["note"]
                rows.append(row)
        if not rows:
            raise SehirHatlariPayloadError("Sehir Hatlari schedule detail contains no departure times")
        return rows

    @staticmethod
    def _route_label_from_heading(heading: str | None) -> str | None:
        if not heading:
            return None
        match = re.search(r"(.+?)\s+Sefer(?:i|leri)\b", heading, flags=re.IGNORECASE)
        if match:
            return _clean_text(match.group(1))
        return None

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
