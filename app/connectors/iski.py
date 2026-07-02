from __future__ import annotations

import json

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import iski_rate_limiter


class IskiPayloadError(RuntimeError):
    pass


class IskiClient:
    def __init__(
        self,
        base_url: str = "https://harita.iski.gov.tr/data",
        timeout: float = 15.0,
        attempts: int = 3,
        api_base_url: str = "https://iskiapi.iski.istanbul/api",
        api_bearer_token: str | None = None,
        active_faults_snapshot_json: str | None = None,
        dams_snapshot_json: str | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = attempts
        self.api_base_url = api_base_url.rstrip("/")
        self.api_bearer_token = api_bearer_token
        self.active_faults_snapshot_json = active_faults_snapshot_json
        self.dams_snapshot_json = dams_snapshot_json
        self.last_faults_source: str | None = None
        self.last_dams_source: str | None = None
        self._client = http_client
        self._rate_limiter = rate_limiter or iski_rate_limiter()

    async def active_faults(self) -> dict:
        try:
            body = await self._get_json("mahallelerKesinti.geojson")
            self.last_faults_source = "live_geojson"
        except httpx.HTTPError:
            if not self.active_faults_snapshot_json:
                raise
            body = self._snapshot_payload(
                self.active_faults_snapshot_json,
                payload_name="ISKI active faults snapshot",
            )
            self.last_faults_source = "snapshot"
        if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
            raise IskiPayloadError("ISKI active faults payload must be a GeoJSON FeatureCollection")
        features = body.get("features")
        if not isinstance(features, list):
            raise IskiPayloadError("ISKI active faults payload must include a features list")
        return body

    async def dams(self) -> list[dict]:
        last_error: httpx.HTTPError | None = None
        try:
            body = await self._get_json("baraj.json")
            self.last_dams_source = "live_json"
        except httpx.HTTPError as exc:
            last_error = exc
            if self.api_bearer_token:
                try:
                    rows = await self._dams_from_api()
                    self.last_dams_source = "official_api"
                    return rows
                except httpx.HTTPError as api_exc:
                    last_error = api_exc
            if self.dams_snapshot_json:
                body = self._snapshot_payload(
                    self.dams_snapshot_json,
                    payload_name="ISKI dam snapshot",
                )
                self.last_dams_source = "snapshot"
            else:
                raise last_error
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise IskiPayloadError("ISKI dam payload must include a data list")
        return rows

    async def _dams_from_api(self) -> list[dict]:
        body = await self._get_json(
            "iski/baraj/listesi/v2",
            base_url=self.api_base_url,
            headers={"Authorization": f"Bearer {self.api_bearer_token}"},
        )
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise IskiPayloadError("ISKI dam API payload must include a data list")
        return rows

    def _snapshot_payload(self, raw_json: str | None, *, payload_name: str):
        if not raw_json:
            raise IskiPayloadError(f"{payload_name} is not configured")
        try:
            return json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise IskiPayloadError(f"{payload_name} is not valid JSON") from exc

    async def _get_json(
        self,
        path: str,
        *,
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
    ):
        await self._rate_limiter.acquire("iski")
        url = f"{(base_url or self.base_url).rstrip('/')}/{path.lstrip('/')}"
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    url,
                    attempts=self.attempts,
                    rate_limiter=self._rate_limiter,
                    headers=headers,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
                attempts=self.attempts,
                rate_limiter=self._rate_limiter,
                headers=headers,
            )
        response.raise_for_status()
        return response.json()
