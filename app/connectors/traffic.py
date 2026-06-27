from __future__ import annotations

import json
import xml.etree.ElementTree as ET

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import traffic_rate_limiter


class TrafficPayloadError(RuntimeError):
    pass


class TrafficClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or traffic_rate_limiter()

    async def index_history(self, period: str = "5M") -> list[dict]:
        await self._rate_limiter.acquire("traffic")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/TrafficIndexHistory/1/{period}",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/TrafficIndexHistory/1/{period}",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        text = response.text.strip()
        if text.startswith("["):
            try:
                body = json.loads(text)
            except json.JSONDecodeError as exc:
                raise TrafficPayloadError("Traffic index history JSON is malformed") from exc
            if not isinstance(body, list):
                raise TrafficPayloadError("Traffic index history JSON payload must be a list")
            return body
        return self._parse_xml_history(text)

    def _parse_xml_history(self, text: str) -> list[dict]:
        try:
            root = ET.fromstring(text)
        except ET.ParseError as exc:
            raise TrafficPayloadError("Traffic index history XML is malformed") from exc
        records = []
        for item in root.iter():
            children = list(item)
            if not children:
                continue
            record = {child.tag.split("}")[-1]: child.text for child in children}
            if "TrafficIndex" in record:
                records.append(record)
        return records
