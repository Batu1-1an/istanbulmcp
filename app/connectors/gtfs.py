"""Bounded ingestion of the İBB stops table, never stop_times or a whole GTFS ZIP."""
from __future__ import annotations

import asyncio
import csv
from dataclasses import dataclass
import io
import math
import re
from typing import Any, Literal
from urllib.parse import urlsplit

import httpx

from app.connectors.ckan import CkanClient, CkanError
from app.core.rate_limit import RateLimiter
from app.core.settings import Settings
from app.core.source_limits import ckan_rate_limiter
from app.connectors.ibb_relay import ibb_http_client

GTFS_DATASET_ID = "iett-gtfs-verisi"
ISTANBUL_GTFS_BOUNDS = (40.70, 41.50, 27.80, 30.20)
GTFS_METADATA_MAX_BYTES = 512 * 1024
GTFS_DATASTORE_PAGE_SIZE = 100
REQUIRED_STOP_FIELDS = frozenset({"stop_id", "stop_name", "stop_lat", "stop_lon"})
GROUPED_COORDINATE_RE = re.compile(r"[0-9]{1,3}(?:\.[0-9]{3}){2,4}\Z")
DECIMAL_COORDINATE_RE = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)\Z")
DOWNLOAD_PATH_RE = re.compile(r"/dataset/[a-zA-Z0-9-]+/resource/([a-zA-Z0-9-]+)/download/stops\.(?:csv|txt)\Z")


class GtfsStopsError(CkanError):
    """A stop snapshot is unsafe, malformed, incomplete or outside its bounds."""


@dataclass(frozen=True)
class GtfsStopsPayload:
    rows: list[dict[str, Any]]
    resource: dict[str, Any]
    reported_total: int
    received_bytes: int
    scope: str


def validate_gtfs_settings(settings: Settings) -> None:
    if not 1 <= settings.gtfs_stops_max_bytes <= 20 * 1024 * 1024:
        raise ValueError("GTFS_STOPS_MAX_BYTES must be between 1 and 20971520")
    if not 1 <= settings.gtfs_stops_max_rows <= 100000:
        raise ValueError("GTFS_STOPS_MAX_ROWS must be between 1 and 100000")
    if not math.isfinite(settings.gtfs_stops_load_timeout_seconds) or not 0 < settings.gtfs_stops_load_timeout_seconds <= 60:
        raise ValueError("GTFS_STOPS_LOAD_TIMEOUT_SECONDS must be finite and between 0 and 60")
    if not 1 <= settings.gtfs_stops_cache_ttl_seconds <= 86400:
        raise ValueError("GTFS_STOPS_CACHE_TTL_SECONDS must be between 1 and 86400")
    if not 0 <= settings.gtfs_stops_stale_if_error_seconds <= 604800:
        raise ValueError("GTFS_STOPS_STALE_IF_ERROR_SECONDS must be between 0 and 604800")


def parse_gtfs_coordinate(value: Any, *, axis: Literal["lat", "lon"]) -> float | None:
    """Decode only decimal WGS84 or the observed İBB digit-grouping defect.

    The source renders e.g. 41.0191700005564 as 410.191.700.005.564.
    For that exact grouping pattern, the first two digits are degrees. Never
    rescale arbitrary integers, repair shifted text, swap axes or relocate a
    foreign coordinate into Istanbul. This rule is source-specific, not a
    general Turkish number parser.
    """
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    if isinstance(value, str):
        value = value.strip()
        if GROUPED_COORDINATE_RE.fullmatch(value):
            digits = value.replace(".", "")
            value = digits[:2] + "." + digits[2:]
        elif not DECIMAL_COORDINATE_RE.fullmatch(value):
            return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    lower, upper = ISTANBUL_GTFS_BOUNDS[:2] if axis == "lat" else ISTANBUL_GTFS_BOUNDS[2:]
    return number if math.isfinite(number) and lower <= number <= upper else None


def is_gtfs_stops_resource(resource: dict[str, Any]) -> bool:
    name = str(resource.get("name") or "").casefold()
    try:
        filename = urlsplit(str(resource.get("url") or "")).path.rsplit("/", 1)[-1].casefold()
    except ValueError:
        return False
    if re.search(r"stop[\s_-]*times", name) or re.search(r"stop[\s_-]*times", filename):
        return False
    if str(resource.get("format") or "").upper() not in {"", "CSV", "TXT"}:
        return False
    if filename in {"stops.csv", "stops.txt"}:
        return True
    # Description mentions of 'durak' also match stop_times; never search them.
    canonical_name = " ".join(name.split())
    return canonical_name in {"stops", "stops.csv", "stops.txt", "gtfs stops", "durak", "duraklar"}


class GtfsStopsClient:
    def __init__(
        self, *, settings: Settings, ckan_client: CkanClient | None = None,
        http_client: httpx.AsyncClient | None = None, rate_limiter: RateLimiter | None = None,
    ):
        validate_gtfs_settings(settings)
        self.settings = settings
        self.ckan = ckan_client or CkanClient(timeout=settings.request_timeout_seconds)
        self._client = http_client
        self._rate_limiter = rate_limiter or ckan_rate_limiter()

    async def resolve_stops_resource(self) -> dict[str, Any]:
        package = await self.ckan.package_show_bounded(GTFS_DATASET_ID, max_bytes=GTFS_METADATA_MAX_BYTES)
        resources = package.get("resources")
        if not isinstance(resources, list):
            raise GtfsStopsError("GTFS package has no resources list")
        candidates = [
            resource for resource in resources
            if isinstance(resource, dict) and is_gtfs_stops_resource(resource)
            and (resource.get("url") or resource.get("datastore_active") is True)
        ]
        if len(candidates) != 1:
            raise GtfsStopsError(f"Expected exactly one GTFS stops resource, found {len(candidates)}")
        resource = dict(candidates[0])
        if not isinstance(resource.get("id"), str) or not resource["id"].strip():
            raise GtfsStopsError("GTFS stops resource has no resource ID")
        resource["package_metadata_modified"] = package.get("metadata_modified")
        return resource

    async def fetch(self) -> GtfsStopsPayload:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.settings.gtfs_stops_load_timeout_seconds
        async with asyncio.timeout(self.settings.gtfs_stops_load_timeout_seconds):
            resource = await self.resolve_stops_resource()
            if resource.get("url"):
                body = await self._download_csv(resource)
                rows = self._parse_csv(body)
                payload = GtfsStopsPayload(rows, resource, len(rows), len(body), "complete_stops_csv")
            else:
                payload = await self._fetch_datastore(resource)
            self._validate_stop_ids(payload.rows)
            # Synchronous parsing cannot be pre-empted by an asyncio timer.
            if loop.time() >= deadline:
                raise TimeoutError("GTFS stops exceeded its load deadline")
            return payload

    @staticmethod
    def _download_url(resource: dict[str, Any]) -> str:
        url = str(resource.get("url") or "")
        try:
            parsed = urlsplit(url)
            match = DOWNLOAD_PATH_RE.fullmatch(parsed.path)
            safe = (
                parsed.scheme == "https" and parsed.hostname == "data.ibb.gov.tr"
                and parsed.port in (None, 443) and parsed.username is None and parsed.password is None
                and not parsed.query and not parsed.fragment and match is not None
                and match.group(1) == resource["id"]
            )
        except (ValueError, KeyError):
            safe = False
        if not safe:
            raise GtfsStopsError("GTFS CSV must use its canonical data.ibb.gov.tr stops download URL")
        return url

    async def _download_csv(self, resource: dict[str, Any]) -> bytes:
        url = self._download_url(resource)
        expected_size = resource.get("size")
        has_size = isinstance(expected_size, int) and not isinstance(expected_size, bool) and expected_size > 0
        if has_size and expected_size > self.settings.gtfs_stops_max_bytes:
            raise GtfsStopsError("GTFS CSV byte limit exceeded")
        await self._rate_limiter.acquire("ckan")

        async def read(client: httpx.AsyncClient) -> bytes:
            async with client.stream(
                "GET", url, follow_redirects=False, timeout=self.settings.request_timeout_seconds,
                headers={"Accept-Encoding": "identity"},
            ) as response:
                response.raise_for_status()
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise GtfsStopsError("Compressed GTFS downloads are not accepted")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if content_type and content_type not in {"text/csv", "text/plain", "application/csv", "application/octet-stream"}:
                    raise GtfsStopsError("Unexpected GTFS CSV content type")
                cap = self.settings.gtfs_stops_max_bytes
                length = response.headers.get("content-length")
                if length is not None and (not length.isdecimal() or int(length) > cap):
                    raise GtfsStopsError("GTFS CSV byte limit exceeded or invalid Content-Length")
                body = bytearray()
                async for chunk in response.aiter_bytes(chunk_size=65536):
                    if len(body) + len(chunk) > cap:
                        raise GtfsStopsError("GTFS CSV byte limit exceeded")
                    body.extend(chunk)
                if has_size and len(body) != expected_size:
                    raise GtfsStopsError("GTFS CSV size does not match catalog; incomplete snapshot")
                return bytes(body)

        if self._client is not None:
            return await read(self._client)
        async with ibb_http_client(timeout=self.settings.request_timeout_seconds) as client:
            return await read(client)

    def _parse_csv(self, body: bytes) -> list[dict[str, Any]]:
        try:
            text = body.decode("utf-8-sig")
            if "\x00" in text:
                raise GtfsStopsError("GTFS CSV contains NUL bytes")
            # Select only a dialect whose header proves this is a stops table.
            for delimiter in (";", ","):
                reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
                fields = [field.strip() for field in next(reader, [])]
                nonempty = [field for field in fields if field]
                if REQUIRED_STOP_FIELDS <= set(nonempty):
                    break
            else:
                raise GtfsStopsError("GTFS stops schema is missing required fields")
            if len(set(nonempty)) != len(nonempty) or any(not field for field in fields[:-1]):
                raise GtfsStopsError("GTFS stops schema has duplicate or empty fields")
            rows = []
            for values in reader:
                if not values:
                    continue
                if len(rows) >= self.settings.gtfs_stops_max_rows:
                    raise GtfsStopsError("GTFS stops row limit exceeded")
                if len(values) != len(fields):
                    raise GtfsStopsError("GTFS CSV row does not match its header")
                # The official trailing unnamed column even contains a 0 in one
                # valid row. Ignore it, never shift or repair named columns.
                rows.append({field: value for field, value in zip(fields, values) if field})
            return rows
        except (UnicodeDecodeError, csv.Error) as exc:
            raise GtfsStopsError("Malformed GTFS CSV encoding or quoting") from exc

    async def _fetch_datastore(self, resource: dict[str, Any]) -> GtfsStopsPayload:
        rows: list[dict[str, Any]] = []
        total = None
        received_bytes = 0
        while total is None or len(rows) < total:
            remaining = self.settings.gtfs_stops_max_bytes - received_bytes
            result, size = await self.ckan.datastore_search_bounded(
                resource_id=resource["id"], limit=GTFS_DATASTORE_PAGE_SIZE,
                offset=len(rows), max_bytes=remaining,
            )
            received_bytes += size
            if received_bytes > self.settings.gtfs_stops_max_bytes:
                raise GtfsStopsError("GTFS DataStore byte limit exceeded")
            fields = result.get("fields")
            names = {
                field["id"] for field in fields
                if isinstance(field, dict) and isinstance(field.get("id"), str)
            } if isinstance(fields, list) else set()
            if not REQUIRED_STOP_FIELDS <= names:
                raise GtfsStopsError("GTFS stops schema is missing required fields")
            page_total = result.get("total")
            if isinstance(page_total, bool) or not isinstance(page_total, int) or page_total < 0:
                raise GtfsStopsError("GTFS stops total is invalid")
            if page_total > self.settings.gtfs_stops_max_rows:
                raise GtfsStopsError("GTFS stops row limit exceeded")
            if total is not None and page_total != total:
                raise GtfsStopsError("GTFS stops pagination total changed")
            total = page_total
            page = result.get("records")
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise GtfsStopsError("Invalid GTFS DataStore records")
            if len(page) > GTFS_DATASTORE_PAGE_SIZE or len(rows) + len(page) > total:
                raise GtfsStopsError("GTFS stops pagination returned excess records")
            if not page and len(rows) < total:
                raise GtfsStopsError("GTFS stops pagination incomplete")
            rows.extend(page)
        return GtfsStopsPayload(rows, resource, total, received_bytes, "all_active_datastore_records")

    @staticmethod
    def _validate_stop_ids(rows: list[dict[str, Any]]) -> None:
        if not rows:
            raise GtfsStopsError("GTFS stops snapshot is empty; preserving the previous layer")
        seen = set()
        for row in rows:
            raw = row.get("stop_id")
            if isinstance(raw, bool) or not isinstance(raw, (str, int)) or not str(raw).strip():
                raise GtfsStopsError("GTFS stop_id is missing or invalid")
            stop_id = str(raw).strip()
            if stop_id in seen:
                raise GtfsStopsError("GTFS snapshot contains duplicate stop_id values")
            seen.add(stop_id)
