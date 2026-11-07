"""Official Discovery Feed only; ticket links are never fetched."""
from __future__ import annotations

from datetime import datetime, timezone
import re

import httpx
from pydantic import ValidationError

from app.connectors.events_http import EventSourceError, event_json, read_event_body
from app.core.events import EventObservation, category_for, event_time, event_url, venue_from
from app.services.places import normalize_place

FEED_URL = "https://app.ticketmaster.com/discovery-feed/v2/events.json"


def parse_ticketmaster(payload: dict, *, max_rows: int = 10000) -> tuple[list[EventObservation], dict]:
    rows = payload.get("events") if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) > max_rows:
        raise EventSourceError("Ticketmaster feed is missing events or exceeds row limit")
    result = []
    skipped = 0
    observed = datetime.now(timezone.utc)
    for row in rows:
        if not isinstance(row, dict):
            skipped += 1
            continue
        venue = row.get("venue") or {}
        if not isinstance(venue, dict):
            skipped += 1
            continue
        city = normalize_place(str(venue.get("venueCity") or ""))
        if city != "istanbul" or venue.get("venueCountryCode") != "TR":
            continue
        try:
            start = event_time(row.get("eventStartDateTime"))
            if start is None or not row.get("eventId") or not row.get("eventName"):
                raise ValueError("Missing event facts")
            # Dates without a published clock time must not become midnight sessions.
            if row.get("eventStartLocalTime") in (None, ""):
                raise ValueError("Missing start time")
            end = event_time(row.get("eventEndDateTime"))
            url = event_url(row.get("primaryEventUrl"))
            code = re.search(r"/performance/([A-Za-z0-9]+)/", url or "")
            status = row.get("eventStatus")
            result.append(EventObservation(
                source="ticketmaster", source_id=str(row["eventId"]),
                series_key=code[1] if code else str(row["eventId"]), title=row["eventName"],
                category=category_for(" ".join(str(row.get(key) or "") for key in ("classificationSegment", "classificationGenre", "classificationSubGenre"))),
                start_at=start, end_at=end if end and end > start else None,
                venue=venue_from(str(venue.get("venueName") or ""),
                                 str(venue.get("venueAddress") or ""), venue.get("venueLatitude"), venue.get("venueLongitude")),
                program_status={"onsale": "scheduled", "offsale": "scheduled", "cancelled": "cancelled", "postponed": "postponed", "rescheduled": "rescheduled"}.get(status, "unknown"),
                sales_status={"onsale": "on_sale", "offsale": "sales_closed"}.get(status, "unknown"),
                ticket_url=url, description=str(row.get("eventInfo") or "")[:2000] or None,
                observed_at=observed,
                warnings=["Ticketmaster catalogue: price and ticket availability are unknown."],
            ))
        except (ValueError, TypeError, ValidationError):
            skipped += 1
    if skipped and skipped > max(5, len(rows) // 5):
        raise EventSourceError("Ticketmaster parser rejected too many records")
    return result, {"received": len(rows), "accepted": len(result), "skipped": skipped,
                    "complete": True, "warnings": ["Istanbul subset of Ticketmaster/Biletix inventory; not all city events."]}


class TicketmasterClient:
    def __init__(self, settings, client: httpx.AsyncClient):
        self.settings, self.client = settings, client

    async def catalogue(self):
        if not self.settings.ticketmaster_api_key:
            raise EventSourceError("Ticketmaster API key is not configured")
        body = await read_event_body(self.client, FEED_URL,
                                    params={"apikey": self.settings.ticketmaster_api_key, "countryCode": "TR"},
                                    max_bytes=self.settings.events_max_feed_bytes,
                                    max_uncompressed=self.settings.events_max_uncompressed_bytes)
        return parse_ticketmaster(event_json(body), max_rows=self.settings.events_max_rows)
