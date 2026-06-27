from __future__ import annotations

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
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
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
