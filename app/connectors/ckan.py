from __future__ import annotations

from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import ckan_rate_limiter


class CkanError(RuntimeError):
    pass


class CkanClient:
    def __init__(
        self,
        base_url: str = "https://data.ibb.gov.tr/api/3/action",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or ckan_rate_limiter()

    async def _request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{action}"
        await self._rate_limiter.acquire("ckan")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "POST",
                    url,
                    json=payload,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "POST",
                url,
                json=payload,
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        body = response.json()
        if not body.get("success", False):
            raise CkanError(f"CKAN action failed: {action}")
        return body["result"]

    async def package_search(
        self,
        *,
        query: str,
        rows: int,
        start: int = 0,
        formats: list[str] | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"q": query, "rows": rows, "start": start}
        if formats:
            fq = " OR ".join(f"res_format:{fmt.upper()}" for fmt in formats)
            payload["fq"] = fq
        return await self._request("package_search", payload)

    async def package_show(self, dataset_id: str) -> dict[str, Any]:
        return await self._request("package_show", {"id": dataset_id})

    async def datastore_search(
        self,
        *,
        resource_id: str,
        limit: int,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"resource_id": resource_id, "limit": limit, "offset": offset}
        if filters:
            payload["filters"] = filters
        return await self._request("datastore_search", payload)
