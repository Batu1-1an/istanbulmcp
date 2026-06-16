from __future__ import annotations

import httpx

from app.core.rate_limit import RateLimiter
from app.core.source_limits import air_quality_rate_limiter


class AirQualityClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler",
        timeout: float = 15.0,
        rate_limiter: RateLimiter | None = None,
        http_client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._rate_limiter = rate_limiter or air_quality_rate_limiter()
        self._client = http_client

    async def stations(self) -> list[dict]:
        await self._rate_limiter.acquire("air_quality")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(f"{self.base_url}/GetAQIStations")
        else:
            response = await self._client.get(f"{self.base_url}/GetAQIStations")
        if response.status_code == 429:
            self._rate_limiter.penalize(_retry_after_seconds(response.headers.get("retry-after")))
        response.raise_for_status()
        return response.json()

    async def readings(self, station_id: str) -> list[dict]:
        await self._rate_limiter.acquire("air_quality")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/GetAQIByStationId",
                    params={"stationId": station_id},
                )
        else:
            response = await self._client.get(
                f"{self.base_url}/GetAQIByStationId",
                params={"stationId": station_id},
            )
        if response.status_code == 429:
            self._rate_limiter.penalize(_retry_after_seconds(response.headers.get("retry-after")))
        response.raise_for_status()
        return response.json()


def _retry_after_seconds(value: str | None) -> float:
    if not value:
        return 1.0
    try:
        return max(0.0, float(value))
    except ValueError:
        return 1.0
