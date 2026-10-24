from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from app.core.rate_limit import RateLimiter


RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
CONNECT_TIMEOUT_SECONDS = 5.0
UNREACHABLE_HOST_COOLDOWN_SECONDS = 60.0
SleepCallable = Callable[[float], Awaitable[None]]
_clock: Callable[[], float] = time.monotonic
_unreachable_until: dict[str, float] = {}


def reset_unreachable_hosts() -> None:
    _unreachable_until.clear()


def _connect_capped(timeout: Any) -> httpx.Timeout:
    timeout = httpx.Timeout(timeout)
    connect = CONNECT_TIMEOUT_SECONDS if timeout.connect is None else min(timeout.connect, CONNECT_TIMEOUT_SECONDS)
    return httpx.Timeout(connect=connect, read=timeout.read, write=timeout.write, pool=timeout.pool)


def retry_after_seconds(value: str | None) -> float:
    if not value:
        return 1.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 1.0


async def request_with_retries(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    attempts: int = 3,
    rate_limiter: RateLimiter | None = None,
    sleep: SleepCallable | None = None,
    retry_statuses: frozenset[int] = RETRYABLE_STATUS_CODES,
    **kwargs: Any,
) -> httpx.Response:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    sleep_fn = sleep or asyncio.sleep
    penalized_retry_after = False
    host = httpx.URL(url).host
    remaining = _unreachable_until.get(host, 0.0) - _clock()
    if host and remaining > 0:
        raise httpx.ConnectTimeout(
            f"{host} was unreachable recently; skipping for {remaining:.0f}s",
            request=httpx.Request(method, url),
        )
    kwargs["timeout"] = _connect_capped(kwargs.get("timeout", client.timeout))

    for attempt in range(1, attempts + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except httpx.ConnectTimeout:
            if host:
                _unreachable_until[host] = _clock() + UNREACHABLE_HOST_COOLDOWN_SECONDS
            raise
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt >= attempts:
                raise
            await sleep_fn(0.0)
            continue

        if response.status_code not in retry_statuses:
            return response

        retry_delay = 0.0
        if response.status_code == 429:
            retry_delay = retry_after_seconds(response.headers.get("retry-after"))
            if rate_limiter is not None and not penalized_retry_after:
                rate_limiter.penalize(retry_delay)
                penalized_retry_after = True

        if attempt >= attempts:
            response.raise_for_status()
            return response

        await sleep_fn(retry_delay)

    raise RuntimeError("retry loop exhausted unexpectedly")
