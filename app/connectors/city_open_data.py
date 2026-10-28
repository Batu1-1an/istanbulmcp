"""Bounded access to the static IBB layers used by nearby and market tools.

These are published snapshots, not live operating status. Every download has a
canonical-URL check, a byte cap and a row/feature cap. GeoJSON and XLSX are parsed
only after the complete bounded body has arrived; market DataStore pages are
validated as a complete capture.
"""
from __future__ import annotations

import asyncio
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.connectors.ckan import CkanClient, CkanError
from app.connectors.xlsx import read_first_sheet_rows
from app.core.rate_limit import RateLimiter
from app.core.settings import Settings
from app.core.source_limits import ckan_rate_limiter
from app.connectors.ibb_relay import ibb_http_client

EV_DATASET_ID = "79b0e26e-e923-498b-a675-453382274178"
EV_RESOURCE_ID = "726e9d82-37f7-4142-8fa0-4f70a5530188"
EV_URL = f"https://data.ibb.gov.tr/dataset/{EV_DATASET_ID}/resource/{EV_RESOURCE_ID}/download/sarj_istasyonlari.geojson"
TAXI_DATASET_ID = "10fc48d1-ba69-423d-9414-8bb3487e6e2a"
TAXI_RESOURCE_ID = "33c384f3-f456-474c-90cf-1c4e65ac221f"
TAXI_URL = f"https://data.ibb.gov.tr/dataset/{TAXI_DATASET_ID}/resource/{TAXI_RESOURCE_ID}/download/istanbul_taksi_duraklari.geojson"
MARKET_RESOURCE_ID = "78d6e0eb-9012-43c1-9eb1-cd30f743f3a8"
MARKET_PAGE_SIZE = 100
CULTURAL_DATASET_ID = "d299950a-3476-4576-967a-9ab7bbe2aa06"
CULTURAL_RESOURCE_ID = "9f16f741-742f-41f8-9e36-918fb7fc2a7f"
CULTURAL_URL = f"https://data.ibb.gov.tr/dataset/{CULTURAL_DATASET_ID}/resource/{CULTURAL_RESOURCE_ID}/download/kultur-merkezleri-veri-seti_.xlsx"

LAYER_CONFIG = {
    "ev_charging": (EV_DATASET_ID, EV_RESOURCE_ID, EV_URL, "sarj_istasyonlari.geojson"),
    "taxi_stand": (TAXI_DATASET_ID, TAXI_RESOURCE_ID, TAXI_URL, "istanbul_taksi_duraklari.geojson"),
    "cultural_centre": (CULTURAL_DATASET_ID, CULTURAL_RESOURCE_ID, CULTURAL_URL, "kultur-merkezleri-veri-seti_.xlsx"),
}


class OpenDataLayerError(ValueError):
    """Invalid or incomplete static layer; never a checked-empty result."""


@dataclass(frozen=True)
class OpenDataLayer:
    kind: str
    rows: list[dict[str, Any]]
    dataset_id: str | None
    resource_id: str | None
    source_url: str
    reported_total: int | None
    received_bytes: int
    received_total: int
    fetched_at: str | None = None


def validate_open_data_settings(settings: Settings) -> None:
    for name, cap in (
        ("open_data_layers_max_bytes", 32 * 1024 * 1024),
        ("open_data_layers_max_rows", 10000),
        ("open_data_layers_cache_ttl_seconds", 86400),
    ):
        value = getattr(settings, name)
        if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
            raise ValueError(f"{name.upper()} must be between 1 and {cap}")
    if not math.isfinite(settings.open_data_layers_request_timeout_seconds) or not 0 < settings.open_data_layers_request_timeout_seconds <= 30:
        raise ValueError("OPEN_DATA_LAYERS_REQUEST_TIMEOUT_SECONDS must be finite and between 0 and 30")


def _canonical_url(url: str, resource_id: str, filename: str, dataset_id: str) -> str:
    try:
        parsed = urlsplit(url)
        expected = f"/dataset/{dataset_id}/resource/{resource_id}/download/{filename}"
        safe = (
            parsed.scheme == "https"
            and parsed.hostname == "data.ibb.gov.tr"
            and parsed.port in (None, 443)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and parsed.path == expected
        )
    except ValueError:
        safe = False
    if not safe:
        raise OpenDataLayerError("Static layer requires its canonical HTTPS data.ibb.gov.tr URL")
    return url


class CityOpenDataClient:
    def __init__(
        self,
        settings: Settings,
        *,
        ckan_client: CkanClient | None = None,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        validate_open_data_settings(settings)
        self.settings = settings
        self.ckan = ckan_client or CkanClient(
            timeout=settings.open_data_layers_request_timeout_seconds,
        )
        self._client = http_client
        self._rate_limiter = rate_limiter or ckan_rate_limiter()

    async def layer(self, kind: str) -> OpenDataLayer:
        if kind in {"ev_charging", "taxi_stand"}:
            return await self._geojson(kind)
        if kind == "cultural_centre":
            return await self._cultural_xlsx()
        raise OpenDataLayerError(f"Unsupported static layer: {kind}")

    async def market(self) -> OpenDataLayer:
        rows: list[dict[str, Any]] = []
        total: int | None = None
        received_bytes = 0
        page_size = min(MARKET_PAGE_SIZE, self.settings.open_data_layers_max_rows)
        while total is None or len(rows) < total:
            remaining = self.settings.open_data_layers_max_bytes - received_bytes
            if remaining < 1:
                raise OpenDataLayerError("Market DataStore byte budget exhausted")
            result, size = await self.ckan.datastore_search_bounded(
                resource_id=MARKET_RESOURCE_ID, limit=page_size, offset=len(rows), max_bytes=remaining,
            )
            received_bytes += size
            records = result.get("records")
            fields = result.get("fields")
            page_total = result.get("total")
            if not isinstance(records, list) or any(not isinstance(row, dict) for row in records):
                raise OpenDataLayerError("Market DataStore records are malformed")
            if isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0:
                raise OpenDataLayerError("Market DataStore total is missing")
            if page_total > self.settings.open_data_layers_max_rows:
                raise OpenDataLayerError("Market DataStore row budget exceeded")
            names = {
                field.get("id") for field in fields
                if isinstance(field, dict) and isinstance(field.get("id"), str)
            } if isinstance(fields, list) else set()
            if not {"Ilce", "Pazar Adi", "Koordinat", "Gun"} <= names:
                raise OpenDataLayerError("Market DataStore schema is missing required fields")
            if total is not None and page_total != total:
                raise OpenDataLayerError("Market DataStore total changed during pagination")
            total = page_total
            if len(records) > page_size or len(rows) + len(records) > total:
                raise OpenDataLayerError("Market DataStore pagination returned excess records")
            if not records and len(rows) < total:
                raise OpenDataLayerError("Market DataStore pagination is incomplete")
            rows.extend(records)
        if not rows:
            raise OpenDataLayerError("Market DataStore is empty")
        return OpenDataLayer(
            kind="market", rows=rows, dataset_id=None, resource_id=MARKET_RESOURCE_ID,
            source_url=f"https://data.ibb.gov.tr/api/3/action/datastore_search?resource_id={MARKET_RESOURCE_ID}",
            reported_total=total, received_bytes=received_bytes, received_total=len(rows),
            fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _geojson(self, kind: str) -> OpenDataLayer:
        dataset_id, resource_id, url, filename = LAYER_CONFIG[kind]
        _canonical_url(url, resource_id, filename, dataset_id)
        body = await self._download(url, allowed={"application/geo+json", "application/json", "application/octet-stream"})
        try:
            payload = json.loads(body.decode("utf-8-sig"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OpenDataLayerError("Malformed GeoJSON layer") from exc
        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise OpenDataLayerError("Static layer is not a GeoJSON FeatureCollection")
        features = payload["features"]
        if len(features) > self.settings.open_data_layers_max_rows:
            raise OpenDataLayerError("GeoJSON feature budget exceeded")
        if not features or any(not isinstance(feature, dict) for feature in features):
            raise OpenDataLayerError("GeoJSON layer has no usable features")
        return OpenDataLayer(
            kind=kind, rows=features, dataset_id=dataset_id, resource_id=resource_id,
            source_url=url, reported_total=len(features), received_bytes=len(body),
            received_total=len(features), fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _cultural_xlsx(self) -> OpenDataLayer:
        dataset_id, resource_id, url, filename = LAYER_CONFIG["cultural_centre"]
        _canonical_url(url, resource_id, filename, dataset_id)
        body = await self._download(
            url,
            allowed={
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "application/octet-stream",
            },
        )
        try:
            rows = await asyncio.to_thread(
                read_first_sheet_rows, body, max_rows=self.settings.open_data_layers_max_rows)
        except ValueError as exc:
            raise OpenDataLayerError("Malformed cultural-centre XLSX") from exc
        if len(rows) < 2:
            raise OpenDataLayerError("Cultural-centre XLSX has no data rows")
        headers = [str(value).strip() for value in rows[0]]
        named = [header for header in headers if header]
        if len(named) != len(set(named)):
            raise OpenDataLayerError("Cultural-centre XLSX has duplicate headers")
        records = [
            {header: value for header, value in zip(headers, values) if header}
            for values in rows[1:]
        ]
        records = [row for row in records if any(str(value).strip() for value in row.values())]
        if not records:
            raise OpenDataLayerError("Cultural-centre XLSX has no non-empty rows")
        return OpenDataLayer(
            kind="cultural_centre", rows=records, dataset_id=dataset_id, resource_id=resource_id,
            source_url=url, reported_total=len(records), received_bytes=len(body),
            received_total=len(records), fetched_at=datetime.now(timezone.utc).isoformat(),
        )

    async def _download(self, url: str, *, allowed: set[str]) -> bytes:
        await self._rate_limiter.acquire("ckan")

        async def read(client: httpx.AsyncClient) -> bytes:
            try:
                async with client.stream(
                    "GET", url, follow_redirects=False,
                    timeout=self.settings.open_data_layers_request_timeout_seconds,
                    headers={"Accept-Encoding": "identity"},
                ) as response:
                    return await read_response(response)
            except httpx.HTTPError as exc:
                raise OpenDataLayerError("Static-layer HTTP request failed") from exc

        async def read_response(response: httpx.Response) -> bytes:
            response.raise_for_status()
            if response.status_code != 200:
                raise OpenDataLayerError("Static layer returned a partial HTTP response")
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise OpenDataLayerError("Compressed static layers are not accepted")
            content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
            if content_type and content_type not in allowed:
                raise OpenDataLayerError("Unexpected static-layer content type")
            cap = self.settings.open_data_layers_max_bytes
            length = response.headers.get("content-length")
            if length is not None and (not length.isdecimal() or int(length) > cap):
                raise OpenDataLayerError("Static-layer byte limit exceeded or invalid Content-Length")
            body = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=65536):
                if len(body) + len(chunk) > cap:
                    raise OpenDataLayerError("Static-layer byte limit exceeded")
                body.extend(chunk)
            return bytes(body)

        if self._client is not None:
            return await read(self._client)
        async with ibb_http_client(timeout=self.settings.open_data_layers_request_timeout_seconds) as client:
            return await read(client)


def parse_market_coordinate(value: Any) -> tuple[float, float] | None:
    if not isinstance(value, str):
        return None
    parts = [part.strip() for part in value.replace(";", ",").split(",")]
    if len(parts) != 2:
        return None
    try:
        lat, lon = float(parts[0]), float(parts[1])
    except ValueError:
        return None
    if not (math.isfinite(lat) and math.isfinite(lon)):
        return None
    if not (40.70 <= lat <= 41.50 and 27.80 <= lon <= 30.20):
        return None
    return lat, lon
