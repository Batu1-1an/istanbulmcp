"""Biletinial list and detail observations, with explicit partial session coverage."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from html import unescape
from html.parser import HTMLParser
import json
import math
import re
from urllib.parse import urlsplit

import httpx

from app.connectors.events_http import EventSourceError, event_json, read_event_body
from app.core.events import EventObservation, EventOffer, ISTANBUL, category_for, event_time, event_url, venue_from
from app.services.places import normalize_place

BASE = "https://biletinial.com"
SLUG = re.compile(r"^[a-z0-9-]{1,180}$")
MONTHS = {name: i for i, name in enumerate("ocak subat mart nisan mayis haziran temmuz agustos eylul ekim kasim aralik".split(), 1)}


class JsonLdParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.active = False
        self.blocks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.active = dict(attrs).get("type", "").lower() == "application/ld+json"

    def handle_endtag(self, tag):
        if tag == "script":
            self.active = False

    def handle_data(self, data):
        if self.active and len(data) <= 512_000:
            self.blocks.append(data)


class SessionParser(HTMLParser):
    """Capture balanced session divs, excluding footer/script sold-out strings."""
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.sessions = []
        self.depth = 0
        self.identity = None
        self.parts = []

    def handle_starttag(self, tag, attrs):
        identity = dict(attrs).get("id", "")
        if not self.depth and tag == "div" and re.fullmatch(r"seans-\d+", identity):
            self.identity = identity.removeprefix("seans-")
            self.parts = []
            self.depth = 1
        elif self.depth and tag == "div":
            self.depth += 1
        if self.depth:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if self.depth:
            self.parts.append(f"</{tag}>")
            if tag == "div":
                self.depth -= 1
                if self.depth == 0:
                    self.sessions.append((self.identity, "".join(self.parts)))

    def handle_data(self, data):
        if self.depth:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def plain_text(value: str, cap=2000) -> str:
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value)).split())[:cap]


def detail_ref(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    path = parts.path.strip("/").split("/")
    if not event_url(url) or parts.hostname not in {"biletinial.com", "www.biletinial.com"} or len(path) != 3 or path[0] != "tr-tr" or not SLUG.fullmatch(path[1]) or not SLUG.fullmatch(path[2]):
        raise EventSourceError("Invalid Biletinial detail reference")
    return path[1], path[2]


def parse_biletinial_list(payload, category: str) -> tuple[list[EventObservation], bool]:
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list) or not isinstance(payload.get("hasMore"), bool):
        raise EventSourceError("Invalid Biletinial catalogue page")
    result = []
    observed = datetime.now(timezone.utc)
    for item in payload["items"]:
        if not isinstance(item, dict) or not SLUG.fullmatch(str(item.get("seoUrl") or "")):
            raise EventSourceError("Invalid Biletinial catalogue item")
        city = normalize_place(str(item.get("cityName") or ""))
        if "istanbul" not in city:
            continue
        slug = item["seoUrl"]
        try:
            hint = float(item["minTicketAmount"]) if not isinstance(item.get("minTicketAmount"), bool) else None
            if hint is not None and (not math.isfinite(hint) or hint < 0):
                hint = None
        except (ValueError, TypeError, KeyError):
            hint = None
        for value in item.get("seances") or []:
            start = event_time(value)
            if start is None:
                continue
            result.append(EventObservation(
                source="biletinial", source_id=f"{slug}:listing:{start.isoformat()}", series_key=slug,
                title=item["name"], category="standup" if re.search(r"\bstand[\s-]*up\b", item["name"], re.I) else category_for(category), start_at=start,
                catalogue_min_price_try=hint, catalogue_is_free=item.get("isFree") if isinstance(item.get("isFree"), bool) else None,
                venue=venue_from("Unknown venue"), observed_at=observed,
                ticket_url=f"https://biletinial.com/tr-tr/{category}/{slug}",
                program_status="scheduled", warnings=["Catalogue session: venue, price and availability require event detail verification."],
            ))
    return result, payload["hasMore"]


def _json_events(html: str) -> list[dict]:
    parser = JsonLdParser()
    parser.feed(html)
    events = []
    def visit(value):
        if isinstance(value, list):
            for child in value:
                visit(child)
        elif isinstance(value, dict):
            if str(value.get("@type", "")).endswith("Event"):
                events.append(value)
            if "@graph" in value:
                visit(value["@graph"])
    for block in parser.blocks:
        try:
            visit(json.loads(block))
        except (ValueError, RecursionError):
            continue
    return events


def parse_biletinial_detail(html: str, url: str, known_starts=()) -> tuple[list[EventObservation], dict]:
    category, slug = detail_ref(url)
    json_events = _json_events(html)
    # Pair HTML sessions with complete source dates, never invent a year from a day/month label.
    starts = [value for value in known_starts if isinstance(value, datetime)]
    starts += [start for item in json_events if (start := event_time(item.get("startDate"))) is not None]
    session_parser = SessionParser()
    session_parser.feed(html)
    sessions = session_parser.sessions
    result = []
    matched_json = set()
    observed = datetime.now(timezone.utc)
    missing = 0
    for session_id, fragment in sessions:
        time_match = re.search(r'class=["\']tm["\'][^>]*>(.*?)<', fragment, re.S)
        day_match = re.search(r'class=["\']d["\'][^>]*>(.*?)<', fragment, re.S)
        venue_match = re.search(r'href=["\']/tr-tr/mekan/[^"\']+["\'][^>]*>(.*?)</a>', fragment, re.S)
        if not (time_match and day_match and venue_match):
            missing += 1
            continue
        day_parts = normalize_place(plain_text(day_match[1])).split()
        clock = plain_text(time_match[1])
        try:
            day, month = int(day_parts[0]), MONTHS[day_parts[1]]
        except (ValueError, KeyError, IndexError):
            missing += 1
            continue
        candidates = {s.isoformat(): s for s in starts if s.day == day and s.month == month and s.strftime("%H:%M") == clock}
        if len(candidates) != 1:
            missing += 1
            continue
        start = next(iter(candidates.values()))
        venue_name = plain_text(venue_match[1], 300)
        linked = next((item for item in json_events if event_time(item.get("startDate")) == start
                       and normalize_place(str((item.get("location") or {}).get("name", ""))) == normalize_place(venue_name)), None)
        if linked:
            matched_json.add(id(linked))
        observation = _detail_observation(linked or (json_events[0] if json_events else {}), category, slug,
                                          session_id, start, venue_name, url, observed, linked is not None)
        text = normalize_place(plain_text(fragment))
        availability = "sold_out" if "tukendi" in text else "limited" if re.search(r"son \d+ bilet", text) else "unknown"
        prices = re.findall(r'class=["\']price-item["\'][^>]*>\s*<span[^>]*>(.*?)</span>\s*<strong[^>]*>(.*?)</strong>', fragment, re.S)
        if prices:
            offers = []
            for name, amount in prices:
                raw = re.sub(r"[^\d,.]", "", plain_text(amount)).replace(".", "").replace(",", ".")
                if raw:
                    offers.append(EventOffer(name=plain_text(name, 120), price=float(raw), currency="TRY",
                                              availability=availability, url=url))
            observation.offers = offers
        elif availability != "unknown":
            for offer in observation.offers:
                offer.availability = availability
            if not observation.offers:
                observation.offers = [EventOffer(availability=availability, url=url)]
        if observation.venue.address and "istanbul" not in normalize_place(observation.venue.address):
            continue
        # HTML city panels can contain nationwide sessions. With no matching JSON-LD,
        # require an explicit Istanbul label in this session's venue line.
        if not linked and "istanbul" not in normalize_place(fragment[:fragment.find('</div>', fragment.find('class="vl"')) + 6]):
            missing += 1
            continue
        result.append(observation)
    for item in json_events:
        if id(item) in matched_json:
            continue
        start = event_time(item.get("startDate"))
        location = item.get("location") or {}
        address = location.get("address") or {}
        locality = str(address.get("addressLocality") or "") if isinstance(address, dict) else str(address)
        if start is None or "istanbul" not in normalize_place(locality):
            continue
        result.append(_detail_observation(item, category, slug, f"json:{start.isoformat()}:{location.get('name')}",
                                          start, str(location.get("name") or ""), url, observed, True))
    # Read dedicated source facts, not a title-based guess about children's content.
    fact_block = re.search(r'<dl\b[^>]*class=["\'][^"\']*event-card-v2__facts[^"\']*["\'][^>]*>(.*?)</dl>', html, re.S)
    facts = {}
    for label, value in re.findall(r'<dt\b[^>]*>(.*?)</dt>\s*<dd\b[^>]*>(.*?)</dd>', fact_block[1] if fact_block else html, re.S):
        facts.setdefault(normalize_place(plain_text(label)).rstrip(":"), plain_text(value, 200))
    genre = facts.get("etkinlik turu", "")
    if not genre:
        genre = " ".join(plain_text(value) for value in re.findall(r'<a\b[^>]*class=["\'][^"\']*yds_genres_link[^"\']*["\'][^>]*>(.*?)</a>', html, re.S))
    folded_genre = normalize_place(genre)
    published_duration = re.fullmatch(r"(\d{1,3})\s*(?:dakika|dk\.?|min(?:utes)?)", facts.get("sure", ""), re.I)
    for observation in result:
        observation.age_limit = facts.get("yas siniri") or None
        if "cocuk oyunu" in folded_genre or "cocuk tiyatro" in folded_genre or "cocuk konser" in folded_genre:
            observation.category = "family"
        elif "stand" in folded_genre and "up" in folded_genre:
            observation.category = "standup"
        if published_duration and 1 <= int(published_duration[1]) <= 600:
            observation.duration_minutes = int(published_duration[1])
            if observation.end_at is None:
                observation.end_at = observation.start_at + timedelta(minutes=observation.duration_minutes)
                observation.end_source = "published_duration"
        if observation.end_at is not None and observation.end_source == "unknown":
            observation.end_source = "source_end"
    if not result:
        raise EventSourceError("Biletinial detail contained no verified Istanbul sessions")
    return result, {"received": max(len(json_events), len(sessions)), "accepted": len(result),
                    "skipped": missing, "complete": missing == 0,
                    "warnings": ["Some HTML sessions had no unambiguous full source date and were not indexed."] if missing else []}


def _detail_observation(item, category, slug, source_id, start, venue_name, url, observed, linked):
    location = item.get("location") or {} if linked else {}
    address = location.get("address") or {}
    address_text = ", ".join(str(address[k]) for k in ("streetAddress", "addressLocality") if address.get(k)) if isinstance(address, dict) else str(address)
    geo = location.get("geo") or {}
    offers = item.get("offers") or [] if linked else []
    if isinstance(offers, dict):
        offers = [offers]
    parsed_offers = []
    for offer in offers:
        price = offer.get("price")
        parsed_offers.append(EventOffer(
            price=float(price) if price not in (None, "") else None, currency=offer.get("priceCurrency"),
            availability={"InStock": "in_stock", "SoldOut": "sold_out", "LimitedAvailability": "limited"}.get(str(offer.get("availability", "")).rsplit("/", 1)[-1], "unknown"), url=url))
    end = event_time(item.get("endDate")) if linked else None
    return EventObservation(
        source="biletinial", source_id=str(source_id), series_key=slug,
        title=str(item.get("name") or slug), category=category_for(category), start_at=start,
        end_at=end if end and end > start else None, venue=venue_from(venue_name, address_text, geo.get("latitude"), geo.get("longitude")),
        program_status={"EventScheduled": "scheduled", "EventCancelled": "cancelled", "EventPostponed": "postponed", "EventRescheduled": "rescheduled"}.get(str(item.get("eventStatus", "")).rsplit("/", 1)[-1], "unknown") if linked else "unknown",
        offers=parsed_offers, ticket_url=url, description=plain_text(str(item.get("description") or "")) or None,
        organizer=(item.get("organizer") or {}).get("name"), observed_at=observed, detail_checked=True,
        warnings=["Observed ticket prices may depend on ticket type, promotions and service fees; not a checkout quote."],
    )


class BiletinialClient:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def catalogue(self):
        result = []
        seen = set()
        for category in ("tiyatro", "muzik", "opera-bale", "etkinlik"):
            seen_items = set()
            for page in range(self.settings.events_biletinial_max_pages):
                body = await read_event_body(self.client, BASE + "/tr-tr/List/GetMoreItems", params={
                    "region": "tr-tr", "organizerUrl": category, "cityId": 147, "cityUrl": "istanbul", "page": page, "order": 0})
                payload = event_json(body)
                rows, more = parse_biletinial_list(payload, category)
                item_ids = {str(item.get("id")) for item in payload["items"]}
                new = [r for r in rows if r.source_id not in seen]
                if more and not (item_ids - seen_items):
                    raise EventSourceError("Biletinial pagination made no progress")
                seen_items.update(item_ids)
                result.extend(new)
                seen.update(r.source_id for r in new)
                if len(result) > self.settings.events_max_rows:
                    raise EventSourceError("Biletinial catalogue exceeds row limit")
                if not more:
                    break
                await asyncio.sleep(1)
            else:
                raise EventSourceError("Biletinial catalogue exceeds page limit")
            await asyncio.sleep(1)
        return result, {"received": len(result), "accepted": len(result), "skipped": 0, "complete": False,
                        "warnings": ["Biletinial list sessions are provisional; detail verification is required for venue, complete sessions, prices and availability."]}

    async def detail(self, url, known_starts=()):
        category, slug = detail_ref(url)
        body = await read_event_body(self.client, f"{BASE}/tr-tr/{category}/{slug}")
        return parse_biletinial_detail(body.decode("utf-8"), url, known_starts)
