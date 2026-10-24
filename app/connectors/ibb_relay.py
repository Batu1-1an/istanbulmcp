from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import Settings, get_settings

RELAY_HOSTS = frozenset({
    "api.ibb.gov.tr",
    "data.ibb.gov.tr",
    "cbsproxy.ibb.gov.tr",
    "tesislerimiz.ibb.istanbul",
    "www.metro.istanbul",
    "harita.iski.gov.tr",
    "iskiapi.iski.istanbul",
    "sehirhatlari.istanbul",
    "www.sehirhatlari.istanbul",
    "tesislerrezervasyon.ibb.istanbul",
    "www.tcddtasimacilik.gov.tr",
    "marmarayapi.tcddtasimacilik.gov.tr",
})
TOKEN_HEADER = "X-Relay-Token"
ERROR_HEADER = "X-Relay-Error"
MIN_TOKEN_LENGTH = 32
RELAY_ERRORS: dict[str, type[httpx.TransportError]] = {
    "connect_timeout": httpx.ConnectTimeout,
    "connect_error": httpx.ConnectError,
    "read_timeout": httpx.ReadTimeout,
}


def validate_ibb_relay_settings(settings: Settings) -> bool:
    url, token = settings.ibb_relay_base_url, settings.ibb_relay_token
    if not url and not token:
        return False
    if not url or not token:
        raise ValueError("IBB_RELAY_BASE_URL and IBB_RELAY_TOKEN must be set together")
    if httpx.URL(url).scheme != "https":
        raise ValueError("IBB_RELAY_BASE_URL must use https")
    if len(token) < MIN_TOKEN_LENGTH:
        raise ValueError(f"IBB_RELAY_TOKEN must be at least {MIN_TOKEN_LENGTH} characters")
    return True


class IbbRelayTransport(httpx.AsyncBaseTransport):
    def __init__(self, base_url: str, token: str, inner: httpx.AsyncBaseTransport | None = None):
        self.base_url = httpx.URL(base_url.rstrip("/"))
        self.token = token
        self.inner = inner or httpx.AsyncHTTPTransport()

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        url = request.url
        if url.scheme != "https" or url.host not in RELAY_HOSTS or url.port not in (None, 443):
            return await self.inner.handle_async_request(request)
        relay_url = self.base_url.copy_with(
            raw_path=self.base_url.raw_path.rstrip(b"/") + b"/" + url.host.encode("ascii") + url.raw_path
        )
        headers = request.headers.copy()
        headers["Host"] = relay_url.netloc.decode("ascii")
        headers[TOKEN_HEADER] = self.token
        relayed = httpx.Request(request.method, relay_url, headers=headers, stream=request.stream, extensions=request.extensions)
        response = await self.inner.handle_async_request(relayed)
        error = RELAY_ERRORS.get(response.headers.get(ERROR_HEADER, ""))
        if error is not None:
            await response.aclose()
            raise error(f"{url.host} unreachable through IBB relay", request=request)
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def ibb_http_client(**kwargs: Any) -> httpx.AsyncClient:
    settings = get_settings()
    if "transport" not in kwargs and settings.ibb_relay_base_url and settings.ibb_relay_token:
        kwargs["transport"] = IbbRelayTransport(settings.ibb_relay_base_url, settings.ibb_relay_token)
    return httpx.AsyncClient(**kwargs)
