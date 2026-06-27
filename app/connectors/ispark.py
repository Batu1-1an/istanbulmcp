from __future__ import annotations

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import ispark_rate_limiter


class IsparkPayloadError(RuntimeError):
    pass


class IsparkClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/ispark",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or ispark_rate_limiter()

    async def parks(self) -> list[dict]:
        await self._rate_limiter.acquire("ispark")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/Park",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/Park",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, list):
            raise IsparkPayloadError("ISPark parks payload must be a list")
        return body
