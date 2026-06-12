from __future__ import annotations

import httpx


class AirQualityClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def stations(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/GetAQIStations")
            response.raise_for_status()
            return response.json()

    async def readings(self, station_id: str) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(
                f"{self.base_url}/GetAQIByStationId",
                params={"stationId": station_id},
            )
            response.raise_for_status()
            return response.json()
