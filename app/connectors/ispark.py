from __future__ import annotations

import httpx


class IsparkClient:
    def __init__(self, base_url: str = "https://api.ibb.gov.tr/ispark", timeout: float = 15.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    async def parks(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.get(f"{self.base_url}/Park")
            response.raise_for_status()
            return response.json()
