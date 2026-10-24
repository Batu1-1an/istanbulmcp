from __future__ import annotations

from typing import Any
import json

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import ckan_rate_limiter
from app.connectors.ibb_relay import ibb_http_client


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
            async with ibb_http_client(timeout=self.timeout) as client:
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

    async def datastore_search_bounded(
        self, *, resource_id: str, limit: int, offset: int, max_bytes: int,
    ) -> tuple[dict[str, Any], int]:
        """One bounded, stable page for complete captures; never calls upstream SQL."""
        payload = {"resource_id": resource_id, "limit": limit, "offset": offset,
                   "sort": "_id asc", "include_total": True}
        return await self._request_bounded("datastore_search", payload, max_bytes=max_bytes)

    async def package_show_bounded(self, dataset_id: str, *, max_bytes: int) -> dict[str, Any]:
        result, _size = await self._request_bounded("package_show", {"id": dataset_id}, max_bytes=max_bytes)
        return result

    async def _request_bounded(
        self, action: str, payload: dict[str, Any], *, max_bytes: int,
    ) -> tuple[dict[str, Any], int]:
        if max_bytes < 1:
            raise CkanError("CKAN response byte budget exhausted")
        await self._rate_limiter.acquire("ckan")

        async def read_response(client: httpx.AsyncClient) -> tuple[dict[str, Any], int]:
            async with client.stream(
                "POST", f"{self.base_url}/{action}", json=payload,
                headers={"Accept-Encoding": "identity"}, timeout=self.timeout,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise CkanError("Compressed bounded CKAN responses are not accepted")
                declared = response.headers.get("content-length")
                if declared is not None and (not declared.isdecimal() or int(declared) > max_bytes):
                    raise CkanError("CKAN response byte limit exceeded or invalid Content-Length")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > max_bytes:
                        raise CkanError("CKAN response byte limit exceeded")
                    body.extend(chunk)
                def reject_constant(_value):
                    raise CkanError("Non-finite JSON numbers are not accepted")
                parsed = json.loads(body, parse_constant=reject_constant)
                if not isinstance(parsed, dict) or parsed.get("success") is not True or not isinstance(parsed.get("result"), dict):
                    raise CkanError("Invalid bounded CKAN response")
                return parsed["result"], len(body)

        if self._client is not None:
            return await read_response(self._client)
        async with ibb_http_client(timeout=self.timeout) as client:
            return await read_response(client)

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
