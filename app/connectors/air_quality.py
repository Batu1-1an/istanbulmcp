from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import air_quality_rate_limiter
from app.connectors.ibb_relay import ibb_http_client

ISTANBUL = ZoneInfo("Europe/Istanbul")
READING_LOOKBACK_HOURS = 24
READING_DATE_FORMAT = "%d.%m.%Y %H:%M:%S"


def reading_window(now: datetime | None = None) -> dict[str, str]:
    end = (now or datetime.now(ISTANBUL)).astimezone(ISTANBUL).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=READING_LOOKBACK_HOURS)
    return {"StartDate": start.strftime(READING_DATE_FORMAT), "EndDate": end.strftime(READING_DATE_FORMAT)}


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
            async with ibb_http_client(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/GetAQIStations",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/GetAQIStations",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        return response.json()

    async def readings(self, station_id: str, *, now: datetime | None = None) -> list[dict]:
        await self._rate_limiter.acquire("air_quality")
        params = {"StationId": station_id, **reading_window(now)}
        if self._client is None:
            async with ibb_http_client(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/GetAQIByStationId",
                    params=params,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/GetAQIByStationId",
                params=params,
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        return response.json()
