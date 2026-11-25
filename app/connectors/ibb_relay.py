from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
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
POOL_LIMITS = httpx.Limits(max_connections=40, max_keepalive_connections=20, keepalive_expiry=30.0)

_shared_pool: tuple[tuple[str | None, str | None], httpx.AsyncClient] | None = None


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
        self.inner = inner or httpx.AsyncHTTPTransport(limits=POOL_LIMITS)

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


class _BorrowedAsyncClient:
    """Non-owning facade over the lifespan-managed httpx.AsyncClient pool."""

    def __init__(
        self,
        pool: httpx.AsyncClient,
        *,
        timeout: Any = None,
        follow_redirects: bool | None = None,
    ):
        self._pool = pool
        self.timeout = httpx.Timeout(timeout) if timeout is not None else pool.timeout
        self._follow_redirects = follow_redirects

    @property
    def _transport(self) -> httpx.AsyncBaseTransport:
        return self._pool._transport

    def _defaults(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        merged = dict(kwargs)
        merged.setdefault("timeout", self.timeout)
        if self._follow_redirects is not None:
            merged.setdefault("follow_redirects", self._follow_redirects)
        return merged

    async def request(self, method: str, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self._pool.request(method, url, **self._defaults(kwargs))

    async def get(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str | httpx.URL, **kwargs: Any) -> httpx.Response:
        return await self.request("POST", url, **kwargs)

    def stream(self, method: str, url: str | httpx.URL, **kwargs: Any):
        return self._pool.stream(method, url, **self._defaults(kwargs))

    async def __aenter__(self) -> _BorrowedAsyncClient:
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def aclose(self) -> None:
        return None


def _build_client(settings: Settings, **kwargs: Any) -> httpx.AsyncClient:
    if "transport" not in kwargs and settings.ibb_relay_base_url and settings.ibb_relay_token:
        kwargs["transport"] = IbbRelayTransport(settings.ibb_relay_base_url, settings.ibb_relay_token)
    kwargs.setdefault("limits", POOL_LIMITS)
    return httpx.AsyncClient(**kwargs)


@contextlib.asynccontextmanager
async def shared_http_pool(settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    """Open one pooled AsyncClient for the app lifespan and close it on shutdown."""
    global _shared_pool
    previous = _shared_pool
    key = (settings.ibb_relay_base_url, settings.ibb_relay_token)
    client = _build_client(settings, timeout=settings.request_timeout_seconds)
    _shared_pool = (key, client)
    try:
        yield client
    finally:
        _shared_pool = previous
        await client.aclose()


def ibb_http_client(**kwargs: Any) -> Any:
    settings = get_settings()
    key = (settings.ibb_relay_base_url, settings.ibb_relay_token)
    if (
        _shared_pool is not None
        and _shared_pool[0] == key
        and set(kwargs) <= {"timeout", "follow_redirects"}
    ):
        return _BorrowedAsyncClient(
            _shared_pool[1],
            timeout=kwargs.get("timeout"),
            follow_redirects=kwargs.get("follow_redirects"),
        )
    return _build_client(settings, **kwargs)
