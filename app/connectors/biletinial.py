"""Biletinial list and detail observations, with explicit partial session coverage."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone, time
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
TIME_CONFLICT_WARNING = (
    "Source time conflict: start_at uses the published Istanbul HTML session date/time; "
    "the conflicting JSON-LD offset and end time were not used. Verify the ticket page before visiting."
)
UNCONFIRMED_TIME_WARNING = (
    "Unconfirmed JSON-LD session time withheld: a published HTML session exists for the same venue/date. "
    "Only the visible session times were indexed; source coverage may be partial."
)
FLEXIBLE_ENTRY_WARNING = (
    "Flexible-entry ticket: the source provides a date, not a fixed visit time. "
    "Confirm opening hours, reservation and admission conditions on the ticket page; "
    "the source timestamp is not a scheduled start."
)


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


def _category(published: str, title: str) -> tuple[str, str]:
    """Keep generic provider buckets distinct from explicit title type markers."""
    kind = category_for(published)
    folded = normalize_place(title)
    if re.search(r"\bstand[\s-]*up\b", folded):
        return "standup", "title_marker"
    if kind != "other":
        return kind, "provider"
    for pattern, value in (
        (r"\batolye(?:si|leri)?\b", "workshop"),
        (r"\bsergi(?:si|leri)?\b", "exhibition"),
        (r"\bfestival(?:i|leri)?\b", "festival"),
        (r"\b(?:seminer(?:i|leri)?|soylesi(?:si|leri)?)\b", "seminar"),
    ):
        if re.search(pattern, folded):
            return value, "title_marker"
    return "other", "unknown"


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
        kind, category_source = _category(str(item.get("categoryName") or category), item["name"])
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
                title=item["name"], category=kind, category_source=category_source, start_at=start,
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


def _session_header(fragment: str) -> tuple[int, int, str | None, str] | None:
    clock = re.search(r'class=["\']tm["\'][^>]*>(.*?)<', fragment, re.S)
    day = re.search(r'class=["\']d["\'][^>]*>(.*?)<', fragment, re.S)
    venue = re.search(r'href=["\']/tr-tr/mekan/[^"\']+["\'][^>]*>(.*?)</a>', fragment, re.S)
    if not (day and venue):
        return None
    parts = normalize_place(plain_text(day[1])).split()
    try:
        return int(parts[0]), MONTHS[parts[1]], plain_text(clock[1]) if clock else None, plain_text(venue[1], 300)
    except (ValueError, KeyError, IndexError):
        return None


def _flexible_entry(value: str) -> bool:
    text = normalize_place(plain_text(value, 8000))
    return bool(re.search(r"\b(?:ilgili|secilen|belirtilen) tarihte(?:ki)? "
                          r"(?:istenilen|istenen|dilediginiz|herhangi bir) saatte "
                          r"(?:kullanilabilir|gecerlidir)\b", text))


def _json_session_starts(items: list[dict], headers: list[tuple]) -> tuple[dict, set]:
    """Reconcile an offset conflict only with an explicit same-venue HTML wall clock.

    A genuine UTC instant matching another HTML slot always wins. JSON-only
    records retain normal timezone conversion; no title or midnight heuristic.
    """
    slots = {(month, day, clock, normalize_place(venue)) for day, month, clock, venue in headers if clock}
    starts, conflicts = {}, set()
    for item in items:
        start = event_time(item.get("startDate"))
        if start is None:
            continue
        venue = normalize_place(str((item.get("location") or {}).get("name", "")))
        instant_slot = (start.month, start.day, start.strftime("%H:%M"), venue)
        try:
            raw = datetime.fromisoformat(item["startDate"].replace("Z", "+00:00"))
        except (ValueError, TypeError):
            raw = None
        if raw is not None and raw.tzinfo is not None and instant_slot not in slots:
            raw_slot = (raw.month, raw.day, raw.strftime("%H:%M"), venue)
            if raw_slot in slots and raw.replace(tzinfo=ISTANBUL) != start:
                # The full year is explicit in JSON; the date and clock are
                # explicitly published in HTML, not inferred from a product name.
                start = raw.replace(tzinfo=ISTANBUL)
                conflicts.add(id(item))
        starts[id(item)] = start
    return starts, conflicts


def parse_biletinial_detail(html: str, url: str, known_starts=()) -> tuple[list[EventObservation], dict]:
    category, slug = detail_ref(url)
    json_events = _json_events(html)
    # Pair HTML sessions with complete source dates, never invent a year from a day/month label.
    session_parser = SessionParser()
    session_parser.feed(html)
    sessions = session_parser.sessions
    headers = [_session_header(fragment) for _, fragment in sessions]
    json_starts, time_conflicts = _json_session_starts(json_events, [header for header in headers if header])
    starts = [value for value in known_starts if isinstance(value, datetime)]
    starts += list(json_starts.values())
    result = []
    matched_json = set()
    observed = datetime.now(timezone.utc)
    missing = 0
    html_days = set()
    flexible_rule = any(_flexible_entry(str(item.get("description") or "")) for item in json_events)
    for (session_id, fragment), header in zip(sessions, headers):
        if header is None:
            missing += 1
            continue
        day, month, clock, venue_name = header
        flexible = _flexible_entry(fragment) or (clock is None and flexible_rule)
        # The source year can anchor an explicitly published HTML date even if
        # its JSON clock is wrong. Never assume that shifted clock is another show.
        related = [s for item in json_events if (s := json_starts.get(id(item))) is not None
                   and s.day == day and s.month == month
                   and normalize_place(str((item.get("location") or {}).get("name", ""))) == normalize_place(venue_name)]
        candidates = {s.isoformat(): s for s in starts if clock and s.day == day and s.month == month and s.strftime("%H:%M") == clock}
        if flexible or not candidates:
            years = {s.year for s in related} or {s.year for s in starts if s.day == day and s.month == month}
            if len(years) == 1 and (flexible or clock):
                try:
                    anchor = datetime.combine(datetime(next(iter(years)), month, day).date(),
                                              time.min if flexible else time.fromisoformat(clock), ISTANBUL)
                    candidates = {anchor.isoformat(): anchor}
                except ValueError:
                    candidates = {}
        if len(candidates) != 1:
            missing += 1
            continue
        start = next(iter(candidates.values()))
        matching = [item for item in json_events if (json_starts.get(id(item)) == start or
                    flexible and json_starts.get(id(item)) is not None and json_starts[id(item)].date() == start.date())
                    and normalize_place(str((item.get("location") or {}).get("name", ""))) == normalize_place(venue_name)]
        linked = next((item for item in matching if id(item) not in time_conflicts), matching[0] if matching else None)
        matched_json.update(id(item) for item in matching)
        conflicting = any(id(item) in time_conflicts for item in matching)
        observation = _detail_observation(linked or (json_events[0] if json_events else {}), category, slug,
                                          session_id, start, venue_name, url, observed, linked is not None,
                                          start_time_basis="html_date" if flexible else "html_session", source_time_conflict=conflicting,
                                          timing_kind="flexible_entry" if flexible else "scheduled")
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
        html_days.add((start.date(), normalize_place(venue_name)))
        result.append(observation)
    unconfirmed = 0
    unconfirmed_days = set()
    for item in json_events:
        if id(item) in matched_json:
            continue
        start = json_starts.get(id(item))
        location = item.get("location") or {}
        address = location.get("address") or {}
        locality = str(address.get("addressLocality") or "") if isinstance(address, dict) else str(address)
        if start is None or "istanbul" not in normalize_place(locality):
            continue
        # A conflicting JSON item belongs to a published HTML session, even if
        # that HTML session could not be indexed (e.g. ambiguous source years).
        if id(item) in time_conflicts:
            continue
        key = (start.date(), normalize_place(str(location.get("name") or "")))
        if key in html_days:
            unconfirmed += 1
            unconfirmed_days.add(key)
            continue
        flexible = _flexible_entry(str(item.get("description") or ""))
        result.append(_detail_observation(item, category, slug, f"json:{start.isoformat()}:{location.get('name')}",
                                          datetime.combine(start.date(), time.min, ISTANBUL) if flexible else start,
                                          str(location.get("name") or ""), url, observed, True,
                                          timing_kind="flexible_entry" if flexible else "scheduled"))
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
            observation.category_source = "provider"
        elif "stand" in folded_genre and "up" in folded_genre:
            observation.category = "standup"
            observation.category_source = "provider"
        elif category_for(genre) != "other":
            observation.category = category_for(genre)
            observation.category_source = "provider"
        if observation.timing_kind == "scheduled" and published_duration and 1 <= int(published_duration[1]) <= 600:
            observation.duration_minutes = int(published_duration[1])
            if observation.end_at is None:
                observation.end_at = observation.start_at + timedelta(minutes=observation.duration_minutes)
                observation.end_source = "published_duration"
        if observation.end_at is not None and observation.end_source == "unknown":
            observation.end_source = "source_end"
        if (observation.start_at.date(), normalize_place(observation.venue.name)) in unconfirmed_days:
            observation.source_time_conflict = True
            observation.warnings.append(UNCONFIRMED_TIME_WARNING)
    if not result:
        raise EventSourceError("Biletinial detail contained no verified Istanbul sessions")
    return result, {"received": max(len(json_events), len(sessions)), "accepted": len(result),
                    "time_conflicts": len(time_conflicts),
                    "unconfirmed_json_sessions": unconfirmed,
                    "skipped": missing + unconfirmed, "complete": missing == 0 and unconfirmed == 0,
                    "warnings": ([TIME_CONFLICT_WARNING] if time_conflicts else []) +
                                ([UNCONFIRMED_TIME_WARNING] if unconfirmed else []) +
                                (["Some HTML sessions had no unambiguous full source date and were not indexed."] if missing else [])}


def _detail_observation(item, category, slug, source_id, start, venue_name, url, observed, linked,
                        *, start_time_basis="json_ld", source_time_conflict=False, timing_kind="scheduled"):
    kind, category_source = _category(category, str(item.get("name") or slug))
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
    end = event_time(item.get("endDate")) if linked and not source_time_conflict and timing_kind == "scheduled" else None
    return EventObservation(
        source="biletinial", source_id=str(source_id), series_key=slug,
        title=str(item.get("name") or slug), category=kind, category_source=category_source, start_at=start,
        start_time_basis=start_time_basis, source_time_conflict=source_time_conflict,
        timing_kind=timing_kind, source_start_at=event_time(item.get("startDate")) if linked and timing_kind == "flexible_entry" else None,
        end_at=end if end and end > start else None, venue=venue_from(venue_name, address_text, geo.get("latitude"), geo.get("longitude")),
        program_status={"EventScheduled": "scheduled", "EventCancelled": "cancelled", "EventPostponed": "postponed", "EventRescheduled": "rescheduled"}.get(str(item.get("eventStatus", "")).rsplit("/", 1)[-1], "unknown") if linked else "unknown",
        offers=parsed_offers, ticket_url=url, description=plain_text(str(item.get("description") or "")) or None,
        organizer=(item.get("organizer") or {}).get("name"), observed_at=observed, detail_checked=True,
        warnings=["Observed ticket prices may depend on ticket type, promotions and service fees; not a checkout quote.",
                  *([TIME_CONFLICT_WARNING] if source_time_conflict else []),
                  *([FLEXIBLE_ENTRY_WARNING] if timing_kind == "flexible_entry" else [])],
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
