"""Bounded event-source HTTP with independent wire/decompression budgets."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import math
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
import zlib
from urllib.parse import urljoin, urlsplit

import httpx

from app.core.rate_limit import AsyncTokenBucket


@lru_cache(maxsize=8)
def event_rate_limiter(host: str) -> AsyncTokenBucket:
    return AsyncTokenBucket(capacity=1, refill_per_second=1.0, max_wait_seconds=1.1)


class RedactEventCredentials(logging.Filter):
    def filter(self, record):
        record.msg = re.sub(r"(?i)(apikey=)[^&\s\"'<>]+", r"\1[redacted]", record.getMessage())
        record.args = ()
        return True


for _logger_name in ("httpx", "httpcore"):
    logging.getLogger(_logger_name).addFilter(RedactEventCredentials())


class EventSourceError(ValueError):
    """Sanitized upstream failure; never contains a credential-bearing URL."""


async def read_event_body(client: httpx.AsyncClient, url: str, *, params=None,
                          max_bytes: int = 2_000_000, max_uncompressed: int = 4_000_000,
                          redirects: int = 0) -> bytes:
    # No automatic redirects: credentials cannot cross to a source-controlled host.
    async with asyncio.timeout(30):
        limiter = event_rate_limiter(urlsplit(url).hostname or "unknown")
        await limiter.acquire("events")
        async with client.stream("GET", url, params=params, headers={"Accept-Encoding": "identity"}, follow_redirects=False) as response:
            if response.status_code in {301, 302, 303, 307, 308} and redirects < 2:
                target = urljoin(str(response.url), response.headers.get("location", ""))
                origin, destination = urlsplit(url), urlsplit(target)
                same_host = origin.hostname == destination.hostname
                ticketmaster_feed = (origin.hostname == "app.ticketmaster.com" and destination.hostname == "s3.amazonaws.com"
                                     and destination.path.startswith("/prd141.dcfd.prod1.us-east-1.tmaws-feeds/")
                                     and destination.path.endswith(".json.gz"))
                if (destination.scheme != "https" or destination.port not in (None, 443)
                        or destination.username or destination.password or not (same_host or ticketmaster_feed)):
                    raise EventSourceError("Event source redirect is not allowed")
                # Never forward the original API-key parameters to the download host.
                return await read_event_body(client, target, max_bytes=max_bytes,
                                             max_uncompressed=max_uncompressed, redirects=redirects + 1)
            if response.status_code != 200:
                if response.status_code == 429:
                    header = response.headers.get("Retry-After", "60")
                    try:
                        delay = float(header)
                    except ValueError:
                        try:
                            delay = (parsedate_to_datetime(header) - datetime.now(timezone.utc)).total_seconds()
                        except (ValueError, TypeError, OverflowError):
                            delay = 60
                    delay = min(3600, max(0, delay)) if math.isfinite(delay) else 60
                    limiter.penalize(delay)
                raise EventSourceError(f"Event source returned HTTP {response.status_code}")
            body = bytearray()
            async for chunk in response.aiter_raw():
                body.extend(chunk)
                if len(body) > max_bytes:
                    raise EventSourceError("Event source exceeded download limit")
    if body[:2] == b"\x1f\x8b":
        inflater = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            decoded = inflater.decompress(bytes(body), max_uncompressed + 1)
        except zlib.error:
            raise EventSourceError("Invalid compressed event source") from None
        if len(decoded) > max_uncompressed or not inflater.eof or inflater.unused_data:
            raise EventSourceError("Compressed event source is incomplete or exceeds limit")
        return decoded
    if len(body) > max_uncompressed:
        raise EventSourceError("Event source exceeded decoded limit")
    return bytes(body)


def event_json(body: bytes):
    try:
        return json.loads(body)
    except (ValueError, RecursionError):
        raise EventSourceError("Invalid event JSON") from None
