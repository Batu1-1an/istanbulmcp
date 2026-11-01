from datetime import datetime, timezone

import httpx
import pytest

from app.connectors.air_quality import AirQualityClient


class RecordingLimiter:
    def __init__(self):
        self.acquired = []
        self.penalties = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


@pytest.mark.asyncio
async def test_air_quality_client_uses_source_limiter_for_stations():
    limiter = RecordingLimiter()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/GetAQIStations")
        return httpx.Response(200, json=[])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AirQualityClient(
            base_url="https://example.test/hava",
            http_client=http_client,
            rate_limiter=limiter,
        )
        assert await client.stations() == []

    assert limiter.acquired == ["air_quality"]


@pytest.mark.asyncio
async def test_air_quality_client_penalizes_429_retry_after():
    limiter = RecordingLimiter()

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"retry-after": "2"}, json={"error": "slow down"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AirQualityClient(
            base_url="https://example.test/hava",
            http_client=http_client,
            rate_limiter=limiter,
        )
        with pytest.raises(httpx.HTTPStatusError):
            await client.readings("station-1")

    assert limiter.acquired == ["air_quality"]
    assert limiter.penalties == [2.0]


@pytest.mark.asyncio
async def test_air_quality_readings_request_hour_aligned_istanbul_window():
    seen = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(dict(request.url.params))
        return httpx.Response(200, json=[{"ReadTime": "2026-11-01T21:00:00", "AQI": {"AQIIndex": 17.0}, "Concentration": {"PM10": 13.6}}])

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = AirQualityClient(base_url="https://example.test/hava", http_client=http_client, rate_limiter=RecordingLimiter())
        rows = await client.readings("station-1", now=datetime(2026, 11, 1, 18, 47, 47, 896053, tzinfo=timezone.utc))

    assert rows[0]["AQI"]["AQIIndex"] == 17.0
    assert seen == [{"StationId": "station-1", "StartDate": "31.10.2026 21:00:00", "EndDate": "01.11.2026 21:00:00"}]
