from __future__ import annotations

from html.parser import HTMLParser
from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import ieo_rate_limiter


IEO_SOURCE_URL = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php"


class IeoError(RuntimeError):
    """Base class for safe, source-specific IEO failures."""


class IeoPayloadError(IeoError):
    """The IEO page or marker payload does not match the observed contract."""


class IeoSourceError(IeoError):
    """The IEO source could not be read after bounded retries."""


class IeoAccessError(IeoSourceError):
    """The source rejected the page access/session handshake."""


class _HiddenAccessParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.value: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "input" or self.value:
            return
        attributes = {key.lower(): value for key, value in attrs}
        if attributes.get("id") == "h" or attributes.get("name") == "h":
            value = attributes.get("value")
            if value:
                self.value = value.strip()


class IeoClient:
    def __init__(
        self,
        base_url: str = IEO_SOURCE_URL,
        *,
        timeout: float = 15.0,
        attempts: int = 2,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = attempts
        self._client = http_client
        self._rate_limiter = rate_limiter or ieo_rate_limiter()

    async def markers(self) -> list[dict[str, Any]]:
        await self._rate_limiter.acquire("ieo")
        if self._client is not None:
            return await self._markers_with_client(self._client)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._markers_with_client(client)

    async def _markers_with_client(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        last_access_error: IeoAccessError | None = None
        for _ in range(self.attempts):
            try:
                access = await self._load_access(client)
                return await self._load_markers(client, access)
            except IeoAccessError as exc:
                last_access_error = exc
                continue
        if last_access_error is not None:
            raise last_access_error
        raise IeoSourceError("IEO source request failed after bounded retries.")

    async def _load_access(self, client: httpx.AsyncClient) -> str:
        try:
            response = await request_with_retries(
                client,
                "GET",
                self.base_url,
                attempts=self.attempts,
                rate_limiter=self._rate_limiter,
                headers={"Accept": "text/html,application/xhtml+xml"},
            )
            if response.status_code in {401, 403, 419}:
                raise IeoAccessError(
                    f"IEO page access rejected with HTTP {response.status_code}."
                )
            response.raise_for_status()
        except IeoError:
            raise
        except Exception as exc:
            raise IeoSourceError(f"IEO page request failed: {type(exc).__name__}") from exc

        parser = _HiddenAccessParser()
        parser.feed(response.text)
        if not parser.value:
            raise IeoPayloadError("IEO page did not contain a hidden access value.")
        return parser.value

    async def _load_markers(self, client: httpx.AsyncClient, access: str) -> list[dict[str, Any]]:
        try:
            response = await request_with_retries(
                client,
                "POST",
                self.base_url,
                attempts=self.attempts,
                rate_limiter=self._rate_limiter,
                headers={
                    "Referer": self.base_url,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                data={"jx": "1", "islem": "get_eczane_markers", "h": access},
            )
        except Exception as exc:
            raise IeoSourceError(f"IEO marker request failed: {type(exc).__name__}") from exc

        if response.status_code in {401, 403, 419}:
            raise IeoAccessError(f"IEO marker access rejected with HTTP {response.status_code}.")
        try:
            response.raise_for_status()
        except Exception as exc:
            raise IeoSourceError(f"IEO marker request failed: {type(exc).__name__}") from exc

        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise IeoPayloadError("IEO marker response was not valid JSON.") from exc
        if not isinstance(payload, dict) or payload.get("error") != 0:
            raise IeoPayloadError("IEO marker response had an unexpected error field.")
        rows = payload.get("eczaneler")
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise IeoPayloadError("IEO marker response must contain an object list.")
        return rows
