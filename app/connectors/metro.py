from __future__ import annotations

import re
from typing import Any

import httpx

from app.connectors.http_retry import request_with_retries
from app.core.rate_limit import RateLimiter
from app.core.source_limits import metro_rate_limiter


def _normalize_token(value: str) -> str:
    """Lowercase, strip Turkish diacritics and collapse whitespace for matching."""
    text = value.strip().casefold()
    replacements = {
        "ı": "i", "i": "i", "ö": "o", "ü": "u", "ç": "c", "ş": "s", "ğ": "g",
        "â": "a", "î": "i", "û": "u",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return " ".join(text.split())


class MetroPayloadError(RuntimeError):
    pass


class MetroClient:
    def __init__(
        self,
        base_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2",
        announcements_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V3/GetAnnouncementsWithoutHtml/tr",
        equipment_summary_url: str = "https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetFaultyEquipments",
        equipment_faults_url: str = "https://www.metro.istanbul/MetroIstanbulBuzPateni2024/SeferDurumlari/Ariza",
        timeout: float = 15.0,
        http_client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.announcements_url = announcements_url
        self.equipment_summary_url = equipment_summary_url
        self.equipment_faults_url = equipment_faults_url
        self.timeout = timeout
        self._client = http_client
        self._rate_limiter = rate_limiter or metro_rate_limiter()
        self._last_malformed_detail_count = 0

    async def stations(self) -> list[dict]:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    f"{self.base_url}/GetStations",
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                f"{self.base_url}/GetStations",
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        body = response.json()
        if isinstance(body, dict):
            data = body.get("Data") or []
            if not isinstance(data, list):
                raise MetroPayloadError("Metro stations Data payload must be a list")
            return data
        if not isinstance(body, list):
            raise MetroPayloadError("Metro stations payload must be a list or object")
        return body

    async def service_statuses(self) -> list[dict[str, Any]]:
        body = await self._get_json("GetServiceStatuses")
        if not isinstance(body, dict):
            raise MetroPayloadError("Metro service statuses payload must be an object")
        success = body.get("Success", True)
        if success is False or str(success).lower() == "false":
            raise MetroPayloadError("Metro service statuses response was unsuccessful")
        data = body.get("Data") or body.get("data") or []
        if not isinstance(data, list):
            raise MetroPayloadError("Metro service statuses Data payload must be a list")

        normalized: list[dict[str, Any]] = []
        for row in data:
            if not isinstance(row, dict):
                raise MetroPayloadError("Metro service status row must be an object")
            line_name = self._text(row.get("LineName") or row.get("lineName"))
            line_code = self._text(
                row.get("LineCode")
                or row.get("LineCodeText")
                or row.get("lineCode")
                or row.get("HATKODU")
                or (line_name if self._looks_like_line_code(line_name) else None)
            )
            route_label = self._text(
                row.get("LineLongDescription")
                or row.get("lineLongDescription")
                or row.get("RouteName")
                or row.get("routeLabel")
                or row.get("HAT")
                or (None if self._looks_like_line_code(line_name) else line_name)
            )
            status = self._text(row.get("Status") or row.get("status") or row.get("Durum"))
            message = self._text(
                row.get("Description")
                or row.get("description")
                or row.get("Message")
                or row.get("message")
                or status
            )
            is_active = self._bool(row.get("IsActive") if "IsActive" in row else row.get("isActive"))
            if is_active is False:
                continue
            if not message or not line_code and not route_label:
                continue
            source_event_type = row.get("EventType") or row.get("eventType")
            event_type = (
                "service_status"
                if is_active is True
                else self._event_type(status, source_event_type)
            )
            normalized.append(
                {
                    "operator": "metro_istanbul",
                    "mode": self._mode_for_line(line_code),
                    "line_code": line_code,
                    "route_label": route_label,
                    "event_type": event_type,
                    "message": message,
                    "updated_at": self._text(
                        row.get("UpdateDate")
                        or row.get("updateDate")
                        or row.get("UpdatedAt")
                        or row.get("updatedAt")
                        or row.get("UpdateTime")
                        or row.get("GuncellemeSaati")
                    ),
                }
            )
        return normalized

    async def announcements(self) -> list[dict[str, Any]]:
        """Return official Metro planned service notices from the V3 endpoint."""
        body = await self._get_json_url(self.announcements_url)
        if isinstance(body, list):
            rows = body
        elif isinstance(body, dict):
            rows = next(
                (body[key] for key in ("Data", "data", "Items", "items") if key in body),
                None,
            )
            if rows is None and "Result" in body:
                rows = body["Result"]
        else:
            rows = None
        if not isinstance(rows, list):
            raise MetroPayloadError("Metro announcements payload must be a list")

        normalized: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                raise MetroPayloadError("Metro announcement row must be an object")
            title = self._text(row.get("Title") or row.get("title"))
            content = self._text(row.get("Content") or row.get("content") or row.get("Description"))
            if not content:
                continue
            line_code = self._infer_line_code(title, content)
            route_label = self._infer_route_label(title, line_code)
            normalized.append(
                {
                    "operator": "metro_istanbul",
                    "mode": self._mode_for_line(line_code),
                    "line_code": line_code,
                    "route_label": route_label,
                    "event_type": "service_change",
                    "message": content,
                    "updated_at": self._text(row.get("StartDate") or row.get("startDate")),
                }
            )
        return normalized

    async def equipment_summary(self) -> list[dict[str, Any]]:
        """Return official category equip. counts from the GetFaultyEquipments JSON source."""
        body = await self._get_json_url(self.equipment_summary_url)
        if not isinstance(body, dict):
            raise MetroPayloadError("Metro equipment summary payload must be an object")
        # A missing success marker is NOT treated as success by default; schema drift
        # surfaces as a source parsing failure rather than a fabricated empty result.
        success = body.get("Success", body.get("success"))
        if success is None:
            raise MetroPayloadError("Metro equipment summary response missing Success marker")
        if success is False or str(success).lower() == "false":
            raise MetroPayloadError("Metro equipment summary response was unsuccessful")
        if success is not True and str(success).lower() != "true":
            raise MetroPayloadError("Metro equipment summary Success marker must be a boolean")
        data = body.get("Data") or body.get("data")
        if not isinstance(data, dict):
            raise MetroPayloadError("Metro equipment summary Data payload must be an object")
        if not data:
            # An explicit empty Data object is a legitimate checked-empty summary.
            return []

        group_keys = ("EquipmentServiceStatus", "StationServiceStatus")
        if not any(data.get(key) is not None for key in group_keys):
            # A non-empty Data object that carries neither official status group is a
            # schema drift, not a success; reject it rather than pretending it is empty.
            raise MetroPayloadError("Metro equipment summary Data has no status groups")

        rows: list[dict[str, Any]] = []
        for group_key, raw_rows in ((group_keys[0], data.get(group_keys[0])), (group_keys[1], data.get(group_keys[1]))):
            if raw_rows is None:
                continue
            if not isinstance(raw_rows, list):
                raise MetroPayloadError("Metro equipment summary row group must be a list")
            for row in raw_rows:
                if not isinstance(row, dict):
                    raise MetroPayloadError("Metro equipment summary row must be an object")
                rows.append(self._normalize_summary_row(row, group_key))
        return rows

    async def equipment_faults(self) -> list[dict[str, Any]]:
        """Return official equipment fault detail rows from the Metro İstanbul fault page."""
        self._last_malformed_detail_count = 0
        html = await self._get_text_url(self.equipment_faults_url)
        return self._parse_equipment_faults(html)

    def _parse_equipment_faults(self, html: str) -> list[dict[str, Any]]:
        import re

        rows: list[dict[str, Any]] = []
        row_pattern = re.compile(
            r"<tr\b([^>]*\bdata-arizaid\b[^>]*)>(.*?)</tr>",
            re.IGNORECASE | re.DOTALL,
        )
        malformed_rows = 0
        for match in row_pattern.finditer(html):
            attrs, body = match.group(1), match.group(2)
            row = self._parse_fault_row(attrs, body)
            if row is not None:
                rows.append(row)
            else:
                # A row carrying a fault id but an unusable cell layout is tracked
                # as a malformed row rather than silently dropped.
                malformed_rows += 1
        structured = self._is_structured_fault_page(html)
        if not rows and not structured:
            # No recognizable rows and no table body/header structure -> markup changed
            # or the page is missing the table -> source failure.
            raise MetroPayloadError("Metro equipment fault page markup is unrecognized")
        if not rows and structured and malformed_rows:
            # A structured page where every data row is malformed is not a checked-empty
            # result; it is a schema-drift source failure, not a fabricated empty success.
            raise MetroPayloadError("Metro equipment fault page rows are malformed")
        if malformed_rows and rows:
            # Mixed valid + malformed rows signal schema drift; surface via a flag so
            # the service can report skipped counters and a schema-drift warning.
            self._last_malformed_detail_count = malformed_rows
        return rows

    @staticmethod
    def _is_structured_fault_page(html: str) -> bool:
        import re

        # A checked-empty page still carries the official table structure (a <table>
        # and a <tbody>) plus at least one expected header. Without these, the page
        # cannot be treated as a legitimate checked-empty fault page.
        has_table = re.search(r"<table\b", html, re.IGNORECASE) is not None
        has_body = re.search(r"<tbody\b", html, re.IGNORECASE) is not None
        has_expected_header = bool(
            re.search(r"\b(?:Ekipman|İstasyon|İstasyon|Arıza\s+Nedeni|Konum)\b", html, re.IGNORECASE)
        )
        return has_table and has_body and has_expected_header

    def _parse_fault_row(self, attrs: str, body: str) -> dict[str, Any] | None:
        import re

        def attr(name: str) -> str | None:
            m = re.search(rf"\b{name}=\"([^\"]*)\"", attrs, re.IGNORECASE)
            return m.group(1).strip() or None if m else None

        fault_id = attr("data-arizaid")
        line_id = attr("data-hatid")
        station_id = attr("data-istasyonid")
        equipment_code = attr("data-refekipman")

        cells = [self._strip_html(c) for c in re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.IGNORECASE | re.DOTALL)]
        if len(cells) < 6:
            # A row without the expected number of source cells is treated as unusable.
            return None
        cells = cells[:7]
        raw_line = self._text(cells[0]) if len(cells) > 0 else None
        line_code = raw_line
        if line_code is not None and not self._looks_like_line_code(line_code):
            line_code = self._infer_line_code(line_code, None)
        # Preserve the official line label verbatim when it is a full route label
        # rather than a short M/T/F/TF code, so both representations can match.
        line_label = None
        if raw_line is not None and not self._looks_like_line_code(raw_line):
            line_label = raw_line
        station_name = self._text(cells[1]) if len(cells) > 1 else None
        equipment_label = self._text(cells[2]) if len(cells) > 2 else None
        location = self._text(cells[3]) if len(cells) > 3 else None
        reason = self._text(cells[4]) if len(cells) > 4 else None
        expected_return = self._text(cells[5]) if len(cells) > 5 else None
        status = self._text(cells[6]) if len(cells) > 6 else None

        return {
            "source_fault_id": fault_id,
            "source_line_id": line_id,
            "source_station_id": station_id,
            "source_equipment_code": equipment_code,
            "line_code": line_code,
            "line_label": line_label,
            "station_name": station_name,
            "equipment_type": equipment_label,
            "location_description": location,
            "reason": reason,
            "expected_return": expected_return,
            "status": status,
        }

    @staticmethod
    def _strip_html(value: str) -> str:
        import re

        text = re.sub(r"<br\s*/?>", "\n", value, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&nbsp;", " ", text, flags=re.IGNORECASE)
        text = re.sub(r"&amp;", "&", text, flags=re.IGNORECASE)
        return " ".join(text.split())

    async def _get_text_url(self, url: str) -> str:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await self._request_text(client, "GET", url)
        else:
            response = await self._request_text(self._client, "GET", url)
        response.raise_for_status()
        if not response.content:
            raise MetroPayloadError("Metro equipment fault page returned an empty body")
        return response.text

    async def _request_text(self, client: httpx.AsyncClient, method: str, url: str) -> httpx.Response:
        return await request_with_retries(
            client,
            method,
            url,
            rate_limiter=self._rate_limiter,
        )

    @classmethod
    def _normalize_summary_row(cls, row: dict[str, Any], group_key: str) -> dict[str, Any]:
        name = cls._text(row.get("Name") or row.get("name"))
        group = cls._text(row.get("GroupName") or row.get("Group") or row.get("group"))
        category_name = cls._text(row.get("CategoryName") or row.get("categoryName")) or name
        active = cls._non_negative_int(cls._first_present(row, "ActiveCount", "Active"))
        inactive = cls._non_negative_int(cls._first_present(row, "InactiveCount", "Inactive", "FaultCount"))
        visible = row.get("IsVisible")
        source_order = cls._int(cls._first_present(row, "Order", "SourceOrder", "sourceOrder"))
        if category_name is None:
            raise MetroPayloadError("Metro equipment summary row must have a displayed name")
        if active is None or inactive is None:
            # A category row must carry count values; a missing/negative count is
            # treated as a schema-drift parsing failure, not silently as zero.
            raise MetroPayloadError("Metro equipment summary row requires non-negative counts")
        return cls._summary_row(category_name, name, group, active, inactive, visible, source_order, group_key)

    @classmethod
    def _summary_row(
        cls,
        category_name: str,
        name: str | None,
        group: str | None,
        active: int | None,
        inactive: int | None,
        visible: Any,
        source_order: int | None,
        group_key: str,
    ) -> dict[str, Any]:
        return {
            "category_key": cls._category_key(category_name, group_key),
            "category_name": category_name,
            "group_name": group or name,
            "active_count": active if active is not None else 0,
            "inactive_count": inactive if inactive is not None else 0,
            "is_visible": visible,
            "source_order": source_order,
        }

    @staticmethod
    def _first_present(row: dict[str, Any], *keys: str) -> Any | None:
        for key in keys:
            if key in row and row[key] is not None:
                return row[key]
        return None

    @staticmethod
    def _non_negative_int(value: Any) -> int | None:
        # Reject booleans and non-integral values rather than coercing them.
        if value is None:
            return None
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value >= 0 else None
        if isinstance(value, float):
            if value.is_integer():
                number = int(value)
                return number if number >= 0 else None
            return None
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                number = int(text)
            except ValueError:
                return None
            return number if number >= 0 else None
        return None

    @staticmethod
    def _category_key(category_name: str, group_key: str) -> str:
        normalized = _normalize_token(category_name)
        mapping = {
            "asansor": "elevator",
            "asansorler": "elevator",
            "yuruyen merdiven": "escalator",
            "yuruyen merdivenler": "escalator",
            "merdiven": "escalator",
            "yuruyen bant": "moving_walkway",
            "yuruyen bantlar": "moving_walkway",
            "giris cikis": "entrance_exit",
            "giris cikislar": "entrance_exit",
            "tuvalet": "restroom",
            "tuvaletler": "restroom",
            "mescit": "prayer_room",
            "bebek bakim odasi": "baby_care_room",
            "engelli platformu": "accessible_platform",
            "platform": "accessible_platform",
        }
        if normalized in mapping:
            return mapping[normalized]
        # Unknown categories keep a deterministic, collision-free source-derived key.
        if group_key == "EquipmentServiceStatus":
            return f"equipment:{_normalize_token(category_name)}"
        return f"station:{_normalize_token(category_name)}"

    @staticmethod
    def _int(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, (int, float)):
            return int(value)
        try:
            return int(str(value).strip())
        except (ValueError, TypeError):
            return None

    async def _get_json(self, endpoint: str) -> Any:
        return await self._get_json_url(f"{self.base_url}/{endpoint}")

    async def _get_json_url(self, url: str) -> Any:
        await self._rate_limiter.acquire("metro")
        if self._client is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await request_with_retries(
                    client,
                    "GET",
                    url,
                    rate_limiter=self._rate_limiter,
                )
        else:
            response = await request_with_retries(
                self._client,
                "GET",
                url,
                rate_limiter=self._rate_limiter,
            )
        response.raise_for_status()
        return response.json()

    @staticmethod
    def _text(value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    @staticmethod
    def _bool(value: Any) -> bool | None:
        if isinstance(value, bool):
            return value
        if value is None:
            return None
        text = str(value).strip().casefold()
        if text in {"true", "1", "yes", "evet"}:
            return True
        if text in {"false", "0", "no", "hayır", "hayir"}:
            return False
        return None

    @staticmethod
    def _looks_like_line_code(value: str | None) -> bool:
        return bool(value and re.fullmatch(r"(?:M|T|F|TF)\d+", value.strip(), flags=re.IGNORECASE))

    @classmethod
    def _infer_line_code(cls, title: str | None, content: str | None) -> str | None:
        match = re.search(r"\b((?:TF|M|T|F)\d+)\b", f"{title or ''} {content or ''}", flags=re.IGNORECASE)
        return match.group(1).upper() if match else None

    @staticmethod
    def _infer_route_label(title: str | None, line_code: str | None) -> str | None:
        if not title:
            return None
        text = title.strip()
        if line_code:
            text = re.sub(rf"\b{re.escape(line_code)}\b\s*", "", text, flags=re.IGNORECASE).strip(" -:")
        match = re.search(
            r"([A-Za-zÇĞİÖŞÜçğıöşü]+\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü]+(?:\s*-\s*[A-Za-zÇĞİÖŞÜçğıöşü]+)?)",
            text,
        )
        return match.group(1).strip() if match else (text or None)

    @staticmethod
    def _mode_for_line(line_code: str | None) -> str:
        code = (line_code or "").upper()
        if code.startswith("TF"):
            return "cable_car"
        if code.startswith("M"):
            return "metro"
        if code.startswith("T"):
            return "tram"
        if code.startswith("F"):
            return "funicular"
        return "unknown"

    @classmethod
    def _event_type(cls, status: Any, source_event_type: Any) -> str:
        source_type = cls._text(source_event_type)
        if source_type:
            return source_type
        value = (cls._text(status) or "").casefold()
        if "iptal" in value or "durdur" in value:
            return "cancellation"
        if "arıza" in value or "ariza" in value:
            return "disruption"
        if "değiş" in value or "degis" in value or "gecik" in value or "delay" in value:
            return "service_change"
        if "normal" in value or "çalış" in value or "calis" in value:
            return "operational"
        return "announcement"
