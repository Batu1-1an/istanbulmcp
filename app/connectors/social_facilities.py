from __future__ import annotations

import io
import math
import re
import unicodedata
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings, get_settings
from app.core.source_limits import social_facilities_rate_limiter


class SocialFacilitiesError(RuntimeError):
    """Base error for official social-facility sources."""


class SocialFacilitiesSourceError(SocialFacilitiesError):
    """The official source could not be read."""


class SocialFacilitiesPayloadError(SocialFacilitiesError):
    """The official source returned malformed or unsupported content."""


class SocialFacilitiesCoordinateError(SocialFacilitiesPayloadError):
    """A source coordinate could not be normalized safely."""


@dataclass(frozen=True)
class SocialFacilityRaw:
    name: str | None
    latitude: float | None
    longitude: float | None
    district: str | None = None
    address: str | None = None
    source_id: str | None = None
    detail_url: str | None = None
    reservation_url: str | None = None
    source: str = "live_catalog"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "latitude": self.latitude,
            "longitude": self.longitude,
            "district": self.district,
            "address": self.address,
            "source_id": self.source_id,
            "detail_url": self.detail_url,
            "reservation_url": self.reservation_url,
            "source": self.source,
        }


@dataclass(frozen=True)
class SocialFacilityRecord:
    """Validated location shape shared by connector-level callers."""

    name: str
    latitude: float
    longitude: float
    source_id: str | None = None
    district: str | None = None
    address: str | None = None
    detail_url: str | None = None
    reservation_url: str | None = None


@dataclass(frozen=True)
class SocialFacilitiesPayload:
    rows: tuple[dict[str, Any], ...]
    reported_total: int | None
    source_updated_at: str | None = None
    fallback_source_updated_at: str | None = None
    primary_source_url: str | None = None
    fallback_source_url: str | None = None
    fallback_resource_id: str | None = None
    received_total: int = 0
    skipped_total: int = 0
    duplicate_total: int = 0
    partial_source: bool = False
    fallback_only: bool = False
    warnings: tuple[str, ...] = ()

    @property
    def accepted_total(self) -> int:
        return len(self.rows)

    @property
    def accounting_valid(self) -> bool:
        return self.reported_total is None or self.reported_total == self.accepted_total + self.skipped_total + self.duplicate_total


ISTANBUL_BOUNDS = (40.70, 41.50, 27.80, 30.20)
SOCIAL_FACILITIES_CATALOG_URL = "https://tesislerimiz.ibb.istanbul/tesisler"
SOCIAL_FACILITIES_RESERVATION_URL = "https://tesislerrezervasyon.ibb.istanbul/"
SOCIAL_FACILITIES_CKAN_URL = "https://data.ibb.gov.tr/dataset/6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d"
FORBIDDEN_FIELDS = frozenset(
    {
        "capacity",
        "occupancy",
        "occupancy_rate",
        "availability",
        "queue",
        "open",
        "closed",
        "is_open",
        "is_available",
        "doluluk",
        "kapasite",
        "müsaitlik",
        "musaitlik",
        "sıra",
        "sira",
    }
)


def normalize_name(value: Any) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def normalize_address(value: Any) -> str:
    return normalize_name(value)


def canonical_url(value: Any, *, base_url: str | None = None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    resolved = urljoin(base_url or SOCIAL_FACILITIES_CATALOG_URL, text)
    parsed = urlparse(resolved)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    if parsed.hostname in {"tesislerimiz.ibb.istanbul", "www.tesislerimiz.ibb.istanbul"}:
        resolved = parsed._replace(scheme="https").geturl()
    return resolved


def canonical_identity(row: dict[str, Any]) -> str:
    source_id = _text(row.get("source_id"))
    if source_id:
        return f"id:{source_id}"
    detail_url = canonical_url(row.get("detail_url"))
    if detail_url:
        return f"url:{detail_url.rstrip('/').lower()}"
    name = normalize_name(row.get("name"))
    address = normalize_address(row.get("address"))
    if address:
        return f"name-address:{name}|{address}"
    lat = _coordinate(row.get("latitude"), -90, 90)
    lon = _coordinate(row.get("longitude"), -180, 180)
    return f"name-coord:{name}|{lat:.5f}|{lon:.5f}" if lat is not None and lon is not None else f"name:{name}"


class _CatalogParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        attr = dict(attrs)
        self._href = attr.get("href")
        self._parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._href is not None:
            self.links.append((self._href, _clean_text(" ".join(self._parts))))
            self._href = None
            self._parts = []


class _DetailParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.heading: list[str] = []
        self.address: list[str] = []
        self.iframe_src: str | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag.lower() in {"h1", "h2", "h3"}:
            self._capture = "heading"
            self._parts = []
        elif tag.lower() == "address" or "address" in (attr.get("class") or "").lower():
            self._capture = "address"
            self._parts = []
        elif tag.lower() == "iframe" and attr.get("src"):
            self.iframe_src = attr["src"]

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag.lower() in {"h1", "h2", "h3", "address", "p"}:
            value = _clean_text(" ".join(self._parts))
            if value:
                if self._capture == "heading" and not self.heading:
                    self.heading.append(value)
                elif self._capture == "address" and not self.address:
                    self.address.append(value)
            self._capture = None
            self._parts = []


class _ReservationParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.cards: list[dict[str, str]] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        classes = (attr.get("class") or "").lower()
        if tag.lower() in {"article", "section", "div"} and "card" in classes:
            if self._current:
                self.cards.append(self._current)
            self._current = {}
        if self._current is None:
            self._current = {}
        if tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6"} or "title" in classes:
            self._capture = "name"
            self._parts = []
        elif tag.lower() in {"p", "address"} or "address" in classes:
            self._capture = "address"
            self._parts = []
        elif tag.lower() == "a" and attr.get("href"):
            href = canonical_url(attr["href"], base_url=SOCIAL_FACILITIES_RESERVATION_URL)
            if href and "/reservation/create/" in href:
                self._current["reservation_url"] = href

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture and tag.lower() in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "address"}:
            value = _clean_text(" ".join(self._parts))
            if value and self._current is not None and self._capture not in self._current:
                self._current[self._capture] = value
            self._capture = None
            self._parts = []

    def close(self) -> None:
        super().close()
        if self._current:
            self.cards.append(self._current)
            self._current = None


class SocialFacilitiesClient:
    """Read-only adapter for the official IBB social-facility sources."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        http_client: httpx.AsyncClient | None = None,
        catalog_url: str | None = None,
        reservation_url: str | None = None,
        fallback_url: str | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.catalog_url = catalog_url or self.settings.social_facilities_catalog_url
        self.reservation_url = reservation_url or self.settings.social_facilities_reservation_url
        self.fallback_url = fallback_url or self.settings.social_facilities_ckan_download_url
        self._http_client = http_client
        self._rate_limiter = social_facilities_rate_limiter()
        self._last_fallback_updated_at: str | None = None
        self._live_failed = False

    async def fetch(self) -> SocialFacilitiesPayload:
        own_client = self._http_client is None
        client = self._http_client or httpx.AsyncClient(
            timeout=self.settings.social_facilities_request_timeout_seconds,
            follow_redirects=True,
        )
        warnings: list[str] = []
        self._live_failed = False
        try:
            primary_rows, primary_reported, primary_skipped, primary_duplicates, partial = await self._fetch_live(client, warnings)
            fallback_rows: list[dict[str, Any]] = []
            fallback_updated_at: str | None = None
            fallback_only = not primary_rows
            if fallback_only or any(
                not _valid_live_row(row) or not _text(row.get("address"))
                for row in primary_rows
            ):
                try:
                    fallback_bytes = await self._get_bytes(client, self.fallback_url)
                    fallback_rows, fallback_updated_at = self.parse_xlsx(fallback_bytes)
                    fallback_updated_at = fallback_updated_at or self._last_fallback_updated_at
                except SourceRateLimitExceeded:
                    raise
                except Exception as exc:
                    warnings.append(f"XLSX fallback unavailable: {type(exc).__name__}.")
            if self._live_failed and not fallback_rows:
                raise SocialFacilitiesSourceError("Live social-facility catalog and XLSX fallback are unavailable")
            merged, discrepancies = self.merge_rows(primary_rows, fallback_rows)
            warnings.extend(discrepancies)
            reported = primary_reported if primary_reported is not None else len(fallback_rows)
            accepted = len(merged)
            skipped = max(0, int(reported) - accepted - primary_duplicates)
            if primary_skipped:
                skipped = max(skipped, primary_skipped)
            if reported < accepted + skipped + primary_duplicates:
                reported = accepted + skipped + primary_duplicates
            if partial:
                warnings.append("Live social-facility catalog was partially enriched; valid rows were preserved.")
            if fallback_only and fallback_rows:
                warnings.append("fallback_only: live social-facility catalog unavailable; official XLSX locations used.")
            return SocialFacilitiesPayload(
                rows=tuple(merged),
                reported_total=reported,
                source_updated_at=None,
                fallback_source_updated_at=fallback_updated_at,
                primary_source_url=self.catalog_url,
                fallback_source_url=self.fallback_url if fallback_rows else None,
                fallback_resource_id="sosyal-tesis-konumlari" if fallback_rows else None,
                received_total=len(primary_rows) + len(fallback_rows),
                skipped_total=skipped,
                duplicate_total=primary_duplicates,
                partial_source=partial,
                fallback_only=fallback_only and bool(fallback_rows),
                warnings=tuple(warnings),
            )
        finally:
            if own_client:
                await client.aclose()

    async def _fetch_live(
        self,
        client: httpx.AsyncClient,
        warnings: list[str],
    ) -> tuple[list[dict[str, Any]], int | None, int, int, bool]:
        links: list[tuple[str, str]] = []
        seen_pages: set[str] = set()
        page_url = self.catalog_url
        page_partial = False
        for _ in range(max(1, min(self.settings.social_facilities_max_catalog_pages, 50))):
            if page_url in seen_pages:
                break
            seen_pages.add(page_url)
            try:
                html = await self._get_text(client, page_url, referer=self.catalog_url)
            except Exception as exc:
                warnings.append(f"Live social-facility catalog unavailable: {type(exc).__name__}.")
                if links:
                    # Keep valid rows from pages already read.  A later-page
                    # outage is partial coverage, not a reason to discard the
                    # successful first page or label the whole source broken.
                    page_partial = True
                    break
                self._live_failed = True
                return [], None, 0, 0, True
            parser = _CatalogParser()
            parser.feed(html)
            page_links = [(href, name) for href, name in parser.links if _is_detail_link(href)]
            links.extend(page_links)
            next_url = self._next_page(parser.links, current=page_url)
            if not next_url:
                break
            page_url = next_url
        unique_links: list[tuple[str, str]] = []
        seen: set[str] = set()
        for href, label in links:
            detail = canonical_url(href, base_url=self.catalog_url)
            if detail and detail not in seen:
                seen.add(detail)
                unique_links.append((detail, label))
        reported = len(unique_links)
        rows: list[dict[str, Any]] = []
        skipped = 0
        duplicates = 0
        seen_ids: set[str] = set()
        identity_rows: dict[str, dict[str, Any]] = {}
        for detail_url, label in unique_links[: max(1, min(self.settings.social_facilities_max_detail_pages, 500))]:
            try:
                html = await self._get_text(client, detail_url, referer=self.catalog_url)
                raw = self.parse_detail(html, detail_url=detail_url, fallback_name=label)
            except Exception as exc:
                warnings.append(f"Skipped social-facility detail {detail_url}: {type(exc).__name__}.")
                skipped += 1
                continue
            # Keep named but incomplete detail records so the official XLSX
            # fallback can fill missing coordinates/address fields per record.
            # Completely unnamed entries cannot be matched safely and are
            # counted as skipped.
            if not _text(raw.get("name")):
                skipped += 1
                continue
            identity = canonical_identity(raw)
            if identity in seen_ids:
                previous = identity_rows[identity]
                if not _identity_conflict(previous, raw):
                    duplicates += 1
                    continue
                warnings.append(f"source_discrepancy: duplicate canonical identity preserved for {raw.get('name') or 'unnamed facility'}.")
            seen_ids.add(identity)
            identity_rows.setdefault(identity, raw)
            rows.append(raw)
        try:
            reservation_html = await self._get_text(client, self.reservation_url, referer=self.catalog_url)
            reservations = self.parse_reservations(reservation_html)
            rows = [self._enrich_reservation(row, reservations, warnings) for row in rows]
        except SourceRateLimitExceeded:
            raise
        except Exception as exc:
            warnings.append(f"Reservation enrichment unavailable: {type(exc).__name__}.")
        return rows, reported, skipped, duplicates, bool(page_partial or skipped or len(rows) < reported)

    async def _get_text(self, client: httpx.AsyncClient, url: str, *, referer: str | None = None) -> str:
        response = await request_with_retries(
            client,
            "GET",
            url,
            attempts=max(1, self.settings.social_facilities_request_attempts),
            rate_limiter=self._rate_limiter,
            headers={"Accept": "text/html", "Referer": referer or self.catalog_url},
            timeout=self.settings.social_facilities_request_timeout_seconds,
        )
        response.raise_for_status()
        return response.text

    async def _get_bytes(self, client: httpx.AsyncClient, url: str) -> bytes:
        response = await request_with_retries(
            client,
            "GET",
            url,
            attempts=max(1, self.settings.social_facilities_request_attempts),
            rate_limiter=self._rate_limiter,
            headers={"Accept": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
            timeout=self.settings.social_facilities_request_timeout_seconds,
        )
        response.raise_for_status()
        self._last_fallback_updated_at = response.headers.get("last-modified")
        return response.content

    @staticmethod
    def _next_page(links: Iterable[tuple[str, str]], *, current: str) -> str | None:
        for href, label in links:
            if re.search(r"(?:page|sayfa)[=/-]?\s*\d+", href, re.I) or label.strip().lower() in {"next", "sonraki", ">"}:
                candidate = canonical_url(href, base_url=current)
                if candidate and candidate != current:
                    return candidate
        return None

    @staticmethod
    def parse_detail(html: str, *, detail_url: str | None = None, fallback_name: str | None = None) -> dict[str, Any]:
        parser = _DetailParser()
        parser.feed(html)
        name = parser.heading[0] if parser.heading else _text(fallback_name)
        address = parser.address[0] if parser.address else _address_after_label(html)
        lat, lon = parse_map_coordinates(parser.iframe_src)
        district = _district_from_address(address)
        return SocialFacilityRaw(
            name=name,
            latitude=lat,
            longitude=lon,
            district=district,
            address=address,
            source_id=_source_id_from_html(html),
            detail_url=canonical_url(detail_url),
        ).as_dict()

    @staticmethod
    def parse_reservations(html: str) -> list[dict[str, str]]:
        parser = _ReservationParser()
        parser.feed(html)
        parser.close()
        return [card for card in parser.cards if card.get("name") and card.get("reservation_url")]

    @classmethod
    def merge_rows(
        cls,
        live_rows: Iterable[dict[str, Any]],
        fallback_rows: Iterable[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[str]]:
        live = [dict(row) for row in live_rows]
        fallback = [dict(row) for row in fallback_rows]
        warnings: list[str] = []
        if not live:
            return fallback, warnings
        for row in live:
            match = cls._match_fallback(row, fallback)
            if match is None:
                continue
            for field in ("name", "address", "district", "latitude", "longitude"):
                current = row.get(field)
                candidate = match.get(field)
                if not _valid_field(field, current) and _valid_field(field, candidate):
                    row[field] = candidate
                elif _valid_field(field, current) and _valid_field(field, candidate) and not _same_value(field, current, candidate):
                    warnings.append(f"source_discrepancy: {field} differs for {row.get('name') or 'unnamed facility'}; live value kept.")
            row["fallback_source"] = "sosyal-tesis-konumlari"
        identities: set[str] = set()
        result: list[dict[str, Any]] = []
        for row in live + [r for r in fallback if not cls._matched_fallback(r, live)]:
            identity = canonical_identity(row)
            if identity in identities:
                continue
            identities.add(identity)
            result.append(row)
        return result, warnings

    @staticmethod
    def _match_fallback(row: dict[str, Any], fallback: list[dict[str, Any]]) -> dict[str, Any] | None:
        name = normalize_name(row.get("name"))
        address = normalize_address(row.get("address"))
        exact = [r for r in fallback if name and normalize_name(r.get("name")) == name and (not address or not normalize_address(r.get("address")) or normalize_address(r.get("address")) == address)]
        return exact[0] if len(exact) == 1 else None

    @classmethod
    def _matched_fallback(cls, fallback: dict[str, Any], live: list[dict[str, Any]]) -> bool:
        return cls._match_fallback(fallback, live) is not None

    @staticmethod
    def _enrich_reservation(row: dict[str, Any], cards: list[dict[str, str]], warnings: list[str]) -> dict[str, Any]:
        name = normalize_name(row.get("name"))
        address = normalize_address(row.get("address"))
        matches = [card for card in cards if normalize_name(card.get("name")) == name and (not address or not card.get("address") or normalize_address(card.get("address")) == address)]
        if len(matches) == 1:
            row["reservation_url"] = matches[0].get("reservation_url")
        elif len(matches) > 1:
            warnings.append(f"ambiguous reservation match: {row.get('name') or 'unnamed facility'}.")
        return row

    @staticmethod
    def parse_xlsx(content: bytes) -> tuple[list[dict[str, Any]], str | None]:
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                shared: list[str] = []
                if "xl/sharedStrings.xml" in archive.namelist():
                    root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                    shared = ["".join(node.itertext()) for node in root]
                sheet_name = "xl/worksheets/sheet1.xml"
                if sheet_name not in archive.namelist():
                    candidates = [n for n in archive.namelist() if n.startswith("xl/worksheets/") and n.endswith(".xml")]
                    if not candidates:
                        raise SocialFacilitiesPayloadError("XLSX has no worksheet")
                    sheet_name = sorted(candidates)[0]
                root = ElementTree.fromstring(archive.read(sheet_name))
        except (zipfile.BadZipFile, ElementTree.ParseError, KeyError) as exc:
            raise SocialFacilitiesPayloadError("Invalid social-facility XLSX payload") from exc
        rows: list[list[str]] = []
        for row_node in root.iter():
            if _local_name(row_node.tag) != "row":
                continue
            values: dict[int, str] = {}
            for cell in list(row_node):
                if _local_name(cell.tag) != "c":
                    continue
                ref = cell.attrib.get("r", "")
                col = _column_number(ref)
                value_node = next((child for child in cell if _local_name(child.tag) == "v"), None)
                if value_node is None:
                    inline_node = next((child for child in cell if _local_name(child.tag) == "is"), None)
                    value = "" if inline_node is None else "".join(inline_node.itertext())
                else:
                    value = "".join(value_node.itertext())
                if cell.attrib.get("t") == "s":
                    try:
                        value = shared[int(value)]
                    except (ValueError, IndexError):
                        value = ""
                values[col] = value
            if values:
                rows.append([values.get(i, "") for i in range(max(values) + 1)])
        if not rows:
            raise SocialFacilitiesPayloadError("XLSX worksheet has no rows")
        headers = [normalize_name(value) for value in rows[0]]
        name_i = _first_index(headers, {"name", "tesis adi", "tesis"}, default=0)
        lat_i = _first_index(headers, {"latitude", "enlem", "lat"}, default=1)
        lon_i = _first_index(headers, {"longitude", "boylam", "lon", "latitude 2"}, default=2)
        address_i = _first_index(headers, {"address", "adres"}, default=3)
        parsed: list[dict[str, Any]] = []
        for values in rows[1:]:
            name = _text(values[name_i] if name_i < len(values) else None)
            lat = implicit_coordinate(values[lat_i] if lat_i < len(values) else None, latitude=True)
            lon = implicit_coordinate(values[lon_i] if lon_i < len(values) else None, latitude=False)
            address = _text(values[address_i] if address_i < len(values) else None)
            if not name or lat is None or lon is None:
                continue
            parsed.append(
                SocialFacilityRaw(
                    name=name,
                    latitude=lat,
                    longitude=lon,
                    district=_district_from_address(address),
                    address=address,
                    source="xlsx_fallback",
                ).as_dict()
            )
        return parsed, None


def parse_map_coordinates(value: str | None) -> tuple[float | None, float | None]:
    if not value:
        return None, None
    match = re.search(r"@=\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", value)
    if not match:
        match = re.search(r"(?:center|ll|coords?)\s*[=/]\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)", value, re.I)
    if not match:
        return None, None
    lon = _coordinate(match.group(1), -180, 180)
    lat = _coordinate(match.group(2), -90, 90)
    return lat, lon


def implicit_coordinate(value: Any, *, latitude: bool) -> float | None:
    if value is None:
        return None
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        parsed = float(text)
    except ValueError:
        return None
    if "." not in text and abs(parsed) >= 1000:
        digits = text.lstrip("+-")
        decimals = 2 if latitude else 2
        parsed = math.copysign(int(digits) / (10 ** (len(digits) - decimals)), parsed)
    maximum = 90 if latitude else 180
    return parsed if math.isfinite(parsed) and -maximum <= parsed <= maximum else None


def _valid_live_row(row: dict[str, Any]) -> bool:
    return bool(_text(row.get("name")) and _coordinate(row.get("latitude"), -90, 90) is not None and _coordinate(row.get("longitude"), -180, 180) is not None)


def _valid_field(field: str, value: Any) -> bool:
    if field == "name":
        return bool(_text(value))
    if field in {"latitude", "longitude"}:
        return _coordinate(value, -90 if field == "latitude" else -180, 90 if field == "latitude" else 180) is not None
    return bool(_text(value))


def _same_value(field: str, left: Any, right: Any) -> bool:
    if field in {"latitude", "longitude"}:
        try:
            return abs(float(left) - float(right)) < 1e-5
        except (TypeError, ValueError):
            return False
    return normalize_name(left) == normalize_name(right)


def _identity_conflict(left: dict[str, Any], right: dict[str, Any]) -> bool:
    try:
        if abs(float(left.get("latitude")) - float(right.get("latitude"))) > 1e-5:
            return True
        if abs(float(left.get("longitude")) - float(right.get("longitude"))) > 1e-5:
            return True
    except (TypeError, ValueError):
        pass
    return bool(left.get("address") and right.get("address") and normalize_address(left["address"]) != normalize_address(right["address"]))


def _is_detail_link(href: str) -> bool:
    text = str(href or "").lower()
    return "/tesis/" in text or "/tesisler/" in text and "page=" not in text


def _district_from_address(address: str | None) -> str | None:
    if not address:
        return None
    parts = [part.strip() for part in re.split(r"[/,|-]", address) if part.strip()]
    return parts[-2] if len(parts) >= 2 and "istanbul" in parts[-1].lower() else (parts[-1] if parts else None)


def _address_after_label(html: str) -> str | None:
    """Handle the current IBB detail layout where the address label is a sibling."""
    match = re.search(
        r"<strong>\s*Adres\s*</strong>.*?<p[^>]*>.*?</p>\s*<p[^>]*>(.*?)</p>",
        html,
        flags=re.I | re.S,
    )
    if not match:
        return None
    text = re.sub(r"<[^>]+>", " ", match.group(1))
    return _clean_text(text)


def _source_id_from_html(html: str) -> str | None:
    match = re.search(r"(?:data-(?:source-)?id|data-id|facility-id)\s*=\s*[\"']([^\"']+)[\"']", html, re.I)
    return _text(match.group(1)) if match else None


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value or "").strip()


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = _clean_text(str(value))
    return text or None


def _coordinate(value: Any, minimum: float, maximum: float) -> float | None:
    if value is None or value == "":
        return None
    try:
        parsed = float(str(value).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) and minimum <= parsed <= maximum else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _column_number(ref: str) -> int:
    letters = re.match(r"[A-Za-z]+", ref or "")
    if not letters:
        return 0
    number = 0
    for char in letters.group(0).upper():
        number = number * 26 + ord(char) - 64
    return number - 1


def _first_index(headers: list[str], candidates: set[str], *, default: int) -> int:
    for index, value in enumerate(headers):
        if value in candidates or any(candidate in value for candidate in candidates):
            return index
    return default
