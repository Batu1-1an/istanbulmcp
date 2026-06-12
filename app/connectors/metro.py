from __future__ import annotations

import httpx


class MetroClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2",
        timeout: float = 15.0,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def stations(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/GetStations")
            response.raise_for_status()
            body = response.json()
            if isinstance(body, dict):
                return body.get("Data") or []
            return body
