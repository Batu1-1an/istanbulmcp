from __future__ import annotations

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import iski_rate_limiter


class IskiPayloadError(RuntimeError):
    pass


class IskiClient:
    def __init__(
        self,
        base_url: str = "https://harita.iski.gov.tr/data",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or iski_rate_limiter()

    async def active_faults(self) -> dict:
        body = await self._get_json("mahallelerKesinti.geojson")
        if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
            raise IskiPayloadError("ISKI active faults payload must be a GeoJSON FeatureCollection")
        features = body.get("features")
        if not isinstance(features, list):
            raise IskiPayloadError("ISKI active faults payload must include a features list")
        return body

    async def dams(self) -> list[dict]:
        body = await self._get_json("baraj.json")
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise IskiPayloadError("ISKI dam payload must include a data list")
        return rows

    async def _get_json(self, path: str):
        await self._rate_limiter.acquire("iski")
        url = f"{self.base_url}/{path.lstrip('/')}"
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    url,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        return response.json()
