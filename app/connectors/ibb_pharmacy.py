from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import ibb_pharmacy_rate_limiter


IBB_PHARMACY_SOURCE_URL = "https://cbsproxy.ibb.gov.tr/?eczanews"


class IbbPharmacyError(RuntimeError):
    """Base class for safe, source-specific İBB pharmacy failures."""


class IbbPharmacyPayloadError(IbbPharmacyError):
    """The İBB response does not match the observed wrapper/cardinality contract."""


class IbbPharmacySourceError(IbbPharmacyError):
    """The İBB source could not be read after bounded retries."""


class IbbPharmacyClient:
    """Read the official İBB City Map pharmacy roster with bounded GET retries."""

    def __init__(
        self,
        base_url: str = IBB_PHARMACY_SOURCE_URL,
        *,
        timeout: float = 15.0,
        attempts: int = 2,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        if attempts < 1:
            raise ValueError("attempts must be at least 1")
        self.base_url = base_url
        self.timeout = timeout
        self.attempts = attempts
        self._client = http_client
        if http_client is None:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme != "https"
                or parsed.hostname != "cbsproxy.ibb.gov.tr"
                or parsed.path not in {"", "/"}
                or (parsed.query and not parsed.query.startswith("eczanews"))
            ):
                raise ValueError("base_url must use the canonical İBB pharmacy host and path")
        self._rate_limiter = rate_limiter or ibb_pharmacy_rate_limiter()

    async def roster(self) -> list[dict[str, Any]]:
        """Fetch one logical roster refresh; retries remain GET-only."""
        await self._rate_limiter.acquire("ibb_pharmacy")
        if self._client is not None:
            return await self._roster_with_client(self._client)

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            return await self._roster_with_client(client)

    async def _roster_with_client(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        try:
            response = await request_with_retries(
                client,
                "GET",
                self._request_url(),
                attempts=self.attempts,
                rate_limiter=self._rate_limiter,
                headers={"Accept": "application/json"},
            )
            response.raise_for_status()
        except IbbPharmacyError:
            raise
        except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
            raise IbbPharmacySourceError("İBB pharmacy source request failed") from exc
        except Exception as exc:
            raise IbbPharmacySourceError("İBB pharmacy source request failed") from exc

        try:
            payload = response.json()
        except Exception as exc:
            raise IbbPharmacyPayloadError("İBB pharmacy response was not valid JSON") from exc
        return self._parse_payload(payload)

    def _request_url(self) -> str:
        if "ilceID=" in self.base_url:
            return re.sub(r"([?&]ilceID=)[^&]*", r"\1all", self.base_url, count=1)
        if "?" in self.base_url:
            return f"{self.base_url}&ilceID=all"
        return f"{self.base_url}?eczanews&ilceID=all"

    @staticmethod
    def _parse_payload(payload: Any) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            raise IbbPharmacyPayloadError("İBB pharmacy response must be a JSON object")
        wrapper = payload.get("ArrayOfAramaList")
        if not isinstance(wrapper, dict):
            raise IbbPharmacyPayloadError("İBB pharmacy response is missing ArrayOfAramaList")
        if "AramaList" not in wrapper:
            raise IbbPharmacyPayloadError("İBB pharmacy response is missing AramaList")
        rows = wrapper["AramaList"]
        if isinstance(rows, dict):
            return [rows]
        if isinstance(rows, list) and all(isinstance(row, dict) for row in rows):
            return rows
        raise IbbPharmacyPayloadError("İBB pharmacy AramaList must be an object or list of objects")
