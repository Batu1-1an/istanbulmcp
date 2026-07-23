from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter, SourceRateLimitExceeded
from app.core.source_limits import iski_rate_limiter

logger = logging.getLogger("istanbul_mcp.connectors.iski")


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
        relay_base_url: str | None = None,
        relay_token: str | None = None,
        relay_timeout: float = 15.0,
        active_faults_snapshot_json: str | None = None,
        dams_snapshot_json: str | None = None,
        faults_snapshot_captured_at: str | None = None,
        dams_snapshot_captured_at: str | None = None,
        faults_snapshot_max_age_seconds: int = 21600,
        dams_snapshot_max_age_seconds: int = 86400,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.attempts = attempts
        self.api_base_url = api_base_url.rstrip("/")
        self.api_bearer_token = api_bearer_token
        self.relay_base_url = relay_base_url.rstrip("/") if relay_base_url else None
        self.relay_token = relay_token
        self.relay_timeout = relay_timeout
        self.active_faults_snapshot_json = active_faults_snapshot_json
        self.dams_snapshot_json = dams_snapshot_json
        self.faults_snapshot_captured_at = faults_snapshot_captured_at
        self.dams_snapshot_captured_at = dams_snapshot_captured_at
        self.faults_snapshot_max_age_seconds = faults_snapshot_max_age_seconds
        self.dams_snapshot_max_age_seconds = dams_snapshot_max_age_seconds
        self.last_faults_source: str | None = None
        self.last_dams_source: str | None = None
        self.last_faults_source_updated_at: str | None = None
        self.last_dams_source_updated_at: str | None = None
        self.last_faults_source_stale = False
        self.last_dams_source_stale = False
        self.last_faults_cache_max_age_seconds: float | None = None
        self.last_dams_cache_max_age_seconds: float | None = None
        self._client = http_client
        self._rate_limiter = rate_limiter or iski_rate_limiter()
        self._now = now or (lambda: datetime.now(timezone.utc))

    async def active_faults(self) -> dict:
        self.last_faults_source = None
        self.last_faults_source_updated_at = None
        self.last_faults_source_stale = False
        self.last_faults_cache_max_age_seconds = None
        errors: list[Exception] = []

        if self.relay_base_url and self.relay_token:
            body, error = await self._try_json_source(
                "relay_faults",
                self._validated_faults(
                    self._get_json(
                        "iski/faults",
                    base_url=self.relay_base_url,
                    headers={"Authorization": f"Bearer {self.relay_token}"},
                    timeout=self.relay_timeout,
                    )
                ),
            )
            if body is not None:
                self.last_faults_source = "relay_edevlet" if body.get("relay_source") == "edevlet" else "relay_geojson"
                self.last_faults_source_updated_at = self._relay_cached_at(body)
                self.last_faults_source_stale = body.get("relay_cache_status") == "stale"
                return body
            if error:
                errors.append(error)

        body, error = await self._try_json_source(
            "direct_faults",
            self._validated_faults(self._get_json("mahallelerKesinti.geojson")),
        )
        if body is not None:
            self.last_faults_source = "live_geojson"
            return body
        if error:
            errors.append(error)

        if self.api_bearer_token:
            body, error = await self._try_json_source(
                "official_faults_api",
                self._validated_faults(self._faults_from_api()),
            )
            if body is not None:
                self.last_faults_source = "official_api"
                return body
            if error:
                errors.append(error)

        if self.active_faults_snapshot_json:
            body, captured_at, remaining_age_seconds = self._snapshot_payload(
                self.active_faults_snapshot_json,
                payload_name="ISKI active faults snapshot",
                configured_captured_at=self.faults_snapshot_captured_at,
                max_age_seconds=self.faults_snapshot_max_age_seconds,
            )
            self._validate_fault_payload(body)
            self.last_faults_source = "snapshot"
            self.last_faults_source_updated_at = captured_at
            self.last_faults_cache_max_age_seconds = remaining_age_seconds
            return body

        if errors:
            raise errors[-1]
        raise IskiPayloadError("No ISKI active faults source is configured")

    async def dams(self) -> list[dict]:
        self.last_dams_source = None
        self.last_dams_source_updated_at = None
        self.last_dams_source_stale = False
        self.last_dams_cache_max_age_seconds = None
        errors: list[Exception] = []

        sources: list[tuple[str, str, Callable[[], Awaitable[Any]]]] = []
        if self.relay_base_url and self.relay_token:
            sources.append(
                (
                    "relay_dams",
                    "relay_json",
                    lambda: self._validated_dams(
                        self._get_json(
                            "iski/dams",
                            base_url=self.relay_base_url,
                            headers={"Authorization": f"Bearer {self.relay_token}"},
                            timeout=self.relay_timeout,
                        )
                    ),
                )
            )
        sources.append(("direct_dams", "live_json", lambda: self._validated_dams(self._get_json("baraj.json"))))

        for source_name, source_mode, load in sources:
            result, error = await self._try_json_source(source_name, load())
            if result is not None:
                rows, relay_source, cached_at, is_stale = result
                self.last_dams_source = "relay_edevlet" if relay_source == "edevlet" else source_mode
                self.last_dams_source_updated_at = cached_at
                self.last_dams_source_stale = is_stale
                return rows
            if error:
                errors.append(error)

        if self.api_bearer_token:
            rows, error = await self._try_json_source("official_dams_api", self._dams_from_api())
            if rows is not None:
                self.last_dams_source = "official_api"
                return rows
            if error:
                errors.append(error)

        if self.dams_snapshot_json:
            body, captured_at, remaining_age_seconds = self._snapshot_payload(
                self.dams_snapshot_json,
                payload_name="ISKI dam snapshot",
                configured_captured_at=self.dams_snapshot_captured_at,
                max_age_seconds=self.dams_snapshot_max_age_seconds,
            )
            rows = self._dam_rows(body)
            self.last_dams_source = "snapshot"
            self.last_dams_source_updated_at = captured_at
            self.last_dams_cache_max_age_seconds = remaining_age_seconds
            return rows

        if errors:
            raise errors[-1]
        raise IskiPayloadError("No ISKI dam source is configured")

    async def _faults_from_api(self) -> dict:
        headers = {"Authorization": f"Bearer {self.api_bearer_token}"}
        body = await self._get_json(
            "iski/bolgeselAriza/listesi",
            base_url=self.api_base_url,
            headers=headers,
        )
        districts = body.get("data") if isinstance(body, dict) else None
        if not isinstance(districts, list):
            raise IskiPayloadError("ISKI faults API payload must include a data list")

        features: list[dict[str, Any]] = []
        for district in districts:
            district_code = district.get("ilceKodu") if isinstance(district, dict) else None
            if not district_code:
                continue
            detail = await self._get_json(
                "iski/bolgeselAriza/arizaDetayi",
                method="POST",
                base_url=self.api_base_url,
                headers=headers,
                params={"ilceKodu": str(district_code)},
            )
            rows = detail.get("data") if isinstance(detail, dict) else None
            if not isinstance(rows, list):
                raise IskiPayloadError("ISKI fault detail payload must include a data list")
            features.extend(self._api_fault_feature(row) for row in rows if isinstance(row, dict))
        return {"type": "FeatureCollection", "features": features}

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

    def _snapshot_payload(
        self,
        raw_json: str | None,
        *,
        payload_name: str,
        configured_captured_at: str | None,
        max_age_seconds: int,
    ) -> tuple[Any, str, float]:
        if not raw_json:
            raise IskiPayloadError(f"{payload_name} is not configured")
        try:
            decoded = json.loads(raw_json)
        except json.JSONDecodeError as exc:
            raise IskiPayloadError(f"{payload_name} is not valid JSON") from exc
        if isinstance(decoded, dict) and "payload" in decoded:
            payload = decoded.get("payload")
            captured_at_raw = decoded.get("captured_at")
        else:
            payload = decoded
            captured_at_raw = configured_captured_at
        captured_at = self._snapshot_timestamp(captured_at_raw, payload_name=payload_name)
        age_seconds = (self._aware_utc(self._now()) - captured_at).total_seconds()
        if age_seconds < 0 or age_seconds > max_age_seconds:
            raise IskiPayloadError(f"{payload_name} is outside the allowed age window")
        return payload, captured_at.isoformat(), max_age_seconds - age_seconds

    def _snapshot_timestamp(self, value: Any, *, payload_name: str) -> datetime:
        if not isinstance(value, str) or not value.strip():
            raise IskiPayloadError(f"{payload_name} must include captured_at")
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise IskiPayloadError(f"{payload_name} captured_at is not valid ISO 8601") from exc
        if parsed.tzinfo is None:
            raise IskiPayloadError(f"{payload_name} captured_at must include a timezone")
        return parsed.astimezone(timezone.utc)

    def _aware_utc(self, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise IskiPayloadError("Current time must include a timezone")
        return value.astimezone(timezone.utc)

    async def _try_json_source(
        self,
        source: str,
        operation: Awaitable[Any],
    ) -> tuple[Any | None, Exception | None]:
        started = time.perf_counter()
        try:
            return await operation, None
        except (httpx.HTTPError, IskiPayloadError, SourceRateLimitExceeded, json.JSONDecodeError) as exc:
            logger.warning(
                json.dumps(
                    {
                        "event": "iski_source_failed",
                        "source": source,
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        "error_type": type(exc).__name__,
                    },
                    separators=(",", ":"),
                )
            )
            return None, exc

    def _validate_fault_payload(self, body: Any) -> None:
        if not isinstance(body, dict) or body.get("type") != "FeatureCollection":
            raise IskiPayloadError("ISKI active faults payload must be a GeoJSON FeatureCollection")
        if not isinstance(body.get("features"), list):
            raise IskiPayloadError("ISKI active faults payload must include a features list")
        for feature in body["features"]:
            if not isinstance(feature, dict) or not isinstance(feature.get("properties"), dict):
                raise IskiPayloadError("ISKI active faults payload contains an invalid feature")
            geometry = feature.get("geometry")
            if geometry is not None and not isinstance(geometry, dict):
                raise IskiPayloadError("ISKI active faults payload contains an invalid geometry")

    async def _validated_faults(self, operation: Awaitable[Any]) -> dict:
        body = await operation
        self._validate_fault_payload(body)
        return body

    async def _validated_dams(
        self,
        operation: Awaitable[Any],
    ) -> tuple[list[dict], str | None, str | None, bool]:
        body = await operation
        relay_source = body.get("relay_source") if isinstance(body, dict) else None
        cached_at = self._relay_cached_at(body)
        return (
            self._dam_rows(body),
            relay_source if isinstance(relay_source, str) else None,
            cached_at,
            isinstance(body, dict) and body.get("relay_cache_status") == "stale",
        )

    def _relay_cached_at(self, body: Any) -> str | None:
        if not isinstance(body, dict):
            return None
        value = body.get("relay_cached_at")
        return value if isinstance(value, str) else None

    def _dam_rows(self, body: Any) -> list[dict]:
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise IskiPayloadError("ISKI dam payload must include a data list")
        if any(not isinstance(row, dict) for row in rows):
            raise IskiPayloadError("ISKI dam payload contains an invalid row")
        return rows

    def _api_fault_feature(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "type": "Feature",
            "properties": {
                "ARIZA_NO": row.get("arizaNo"),
                "ILCE_KODU": row.get("ilceKodu"),
                "ILCE_ADI": row.get("ilceAdi"),
                "MAHALLE_KODU": row.get("mahalleKodu"),
                "MAHALLE_ADI": row.get("mahalleAdi"),
                "ARIZA_NEVI_ACIKLAMASI": row.get("arizaNeviAciklamasi"),
                "BASLAMA_TARIHI": row.get("baslamaTarihi"),
                "TAHMINI_BITIS_TARIHI": row.get("tahminiBitisTarihi"),
            },
            "geometry": None,
        }

    async def _get_json(
        self,
        path: str,
        *,
        method: str = "GET",
        base_url: str | None = None,
        headers: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        timeout: float | None = None,
    ):
        await self._rate_limiter.acquire("iski")
        url = f"{(base_url or self.base_url).rstrip('/')}/{path.lstrip('/')}"
        if self._client is None:
            async with httpx.AsyncClient(timeout=timeout or self.timeout) as client:
                response = await request_with_retries(
                    client,
                    method,
                    url,
                    attempts=self.attempts,
                    rate_limiter=self._rate_limiter,
                    headers=headers,
                    params=params,
                )
        else:
            response = await request_with_retries(
                self._client,
                method,
                url,
                attempts=self.attempts,
                rate_limiter=self._rate_limiter,
                headers=headers,
                params=params,
            )
        response.raise_for_status()
        return response.json()
