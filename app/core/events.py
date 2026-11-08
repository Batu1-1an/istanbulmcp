"""Validated event observations; missing facts remain explicit unknowns."""
from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import math
import re
from typing import Literal
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field, field_validator

from app.services.places import district_from_text, normalize_place

ISTANBUL = ZoneInfo("Europe/Istanbul")
Category = Literal["concert", "theatre", "opera_ballet", "standup", "family", "festival", "exhibition", "workshop", "sport", "seminar", "other"]
CATEGORIES = ("concert", "theatre", "opera_ballet", "standup", "family", "festival", "exhibition", "workshop", "sport", "seminar", "other")
CATEGORY_ALIASES = {"tiyatro": "theatre", "theater": "theatre", "konser": "concert", "muzik": "concert",
                    "opera": "opera_ballet", "bale": "opera_ballet", "opera bale": "opera_ballet",
                    "stand up": "standup", "stand-up": "standup", "cocuk": "family", "aile": "family",
                    "sergi": "exhibition", "atolye": "workshop", "spor": "sport", "seminer": "seminar",
                    "muzikal": "theatre", "musical": "theatre"}


def normalize_category(value: str) -> str:
    text = normalize_place(value)
    return CATEGORY_ALIASES.get(text, text)


def published_age_range(age_limit: str | None) -> tuple[int, int | None] | None:
    """A published range only; unknown is not an unrestricted age range."""
    text = normalize_place(age_limit or "")
    if text in {"tum yaslar", "her yas", "all ages", "yas siniri yok"}:
        return 0, None
    match = re.fullmatch(r"(\d{1,2})\s*[-–]\s*(\d{1,2})(?:\s*yas)?", text)
    if match:
        return (int(match[1]), int(match[2])) if int(match[1]) <= int(match[2]) else None
    match = re.fullmatch(r"(\d{1,2})\s*(?:\+|yas(?: ve)? (?:uzeri|ustu))", text)
    if match:
        return int(match[1]), None
    return None


def age_suitability(age_limit: str | None, child_age: int) -> str:
    bounds = published_age_range(age_limit)
    if bounds is None:
        return "unknown"
    low, high = bounds
    return "within" if child_age >= low and (high is None or child_age <= high) else "outside"


def stable_id(kind: str, *parts: str) -> str:
    return kind + "_" + sha256("\0".join(parts).encode()).hexdigest()[:24]


def event_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return result.replace(tzinfo=ISTANBUL) if result.tzinfo is None else result.astimezone(ISTANBUL)
    except (ValueError, TypeError):
        return None


def event_url(value: str | None) -> str | None:
    try:
        url = urlsplit(value or "")
        if (url.scheme == "https" and url.hostname in {"www.biletix.com", "biletix.com", "biletinial.com", "www.biletinial.com", "www.ticketmaster.com", "ticketmaster.com"}
                and url.port in (None, 443) and not url.username and not url.password):
            return value
    except ValueError:
        pass
    return None


def category_for(value: str) -> Category:
    text = normalize_place(value)
    # Match this distinct genre before the broader music/muzik substring,
    # while retaining the existing priority of family/festival labels.
    musical = bool(re.search(r"\b(?:muzikal|muzikaller|musical|musicals|muzikli\s+oyun)\b", text))
    for words, category in (
        (("stand up", "standup", "comedy"), "standup"),
        (("opera", "bale", "ballet"), "opera_ballet"),
        (("children", "child", "family", "cocuk"), "family"),
        (("festival",), "festival"), (("exhibition", "sergi"), "exhibition"),
        (("workshop", "atolye"), "workshop"), (("sport", "spor"), "sport"),
        (("seminar", "seminer", "soylesi"), "seminar"),
        (("theatre", "theater", "tiyatro"), "theatre"),
        (("concert", "music", "muzik", "konser"), "concert"),
    ):
        if any(word in text for word in words) or category == "theatre" and musical:
            return category
    return "other"


class EventVenue(BaseModel):
    name: str = Field(default="Unknown venue", max_length=300)
    district: str | None = None
    address: str | None = None
    lat: float | None = None
    lon: float | None = None
    side: Literal["europe", "asia"] | None = None

    @field_validator("lat", "lon")
    @classmethod
    def valid_coordinate(cls, value):
        if value is not None and not math.isfinite(value):
            raise ValueError("Non-finite coordinate")
        return value


class EventOffer(BaseModel):
    name: str = "Standard"
    price: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    currency: str | None = None
    fees_included: bool | None = None
    availability: Literal["in_stock", "limited", "sold_out", "unknown"] = "unknown"
    url: str | None = None


class EventAdmissionWindow(BaseModel):
    opens_at: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    last_entry_at: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    closes_at: str | None = Field(default=None, pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class EventObservation(BaseModel):
    source: Literal["ticketmaster", "biletinial"]
    source_id: str = Field(min_length=1, max_length=240)
    series_key: str = Field(min_length=1, max_length=240)
    title: str = Field(min_length=1, max_length=500)
    category: Category = "other"
    category_source: Literal["provider", "title_marker", "unknown"] = "provider"
    start_at: datetime
    start_time_basis: Literal["provider_datetime", "html_session", "html_date", "json_ld"] = "provider_datetime"
    timing_kind: Literal["scheduled", "flexible_entry"] = "scheduled"
    source_start_at: datetime | None = None
    admission_window: EventAdmissionWindow | None = None
    excluded_weekdays: list[Literal[0, 1, 2, 3, 4, 5, 6]] = Field(default_factory=list, max_length=7)
    source_time_conflict: bool = False
    end_at: datetime | None = None
    venue: EventVenue
    program_status: Literal["scheduled", "cancelled", "postponed", "rescheduled", "unknown"] = "unknown"
    sales_status: Literal["on_sale", "sales_closed", "not_open", "unknown"] = "unknown"
    offers: list[EventOffer] = Field(default_factory=list, max_length=100)
    ticket_url: str | None = None
    description: str | None = None
    organizer: str | None = None
    age_limit: str | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    end_source: Literal["source_end", "published_duration", "unknown"] = "unknown"
    catalogue_min_price_try: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    catalogue_is_free: bool | None = None
    observed_at: datetime
    detail_checked: bool = False
    warnings: list[str] = Field(default_factory=list)

    @field_validator("start_at", "end_at", "observed_at", "source_start_at")
    @classmethod
    def aware_time(cls, value):
        if value is not None and value.tzinfo is None:
            raise ValueError("Timezone required")
        return value.astimezone(ISTANBUL) if value is not None else None

    @property
    def performance_id(self) -> str:
        return stable_id("perf", self.source, self.source_id)

    @property
    def event_id(self) -> str:
        return stable_id("event", self.source, self.series_key)


def venue_from(name: str, address: str = "", lat=None, lon=None) -> EventVenue:
    district = district_from_text(address)
    asia = {"adalar", "atasehir", "beykoz", "cekmekoy", "kadikoy", "kartal", "maltepe", "pendik", "sancaktepe", "sultanbeyli", "sile", "tuzla", "umraniye", "uskudar"}
    try:
        latitude, longitude = float(lat), float(lon)
        if not (40.7 <= latitude <= 41.7 and 27.9 <= longitude <= 30.0):
            latitude = longitude = None
    except (ValueError, TypeError):
        latitude = longitude = None
    return EventVenue(name=name.strip()[:300] or "Unknown venue", address=address[:600] or None,
                      district=district, lat=latitude, lon=longitude,
                      side=("asia" if normalize_place(district) in asia else "europe") if district else None)


def search_text(value: str) -> str:
    return " ".join(re.findall(r"\w+", normalize_place(value)))
