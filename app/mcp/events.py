"""Compact event discovery surface using the existing response envelope."""
from __future__ import annotations

from typing import Annotated

from pydantic import Field

from app.core.settings import get_settings
from app.services.event_plan import EventPlanService
from app.services.events import EventService

EVENT_TOOL_NAMES = ("istanbul_events_search", "istanbul_event_detail", "istanbul_events_plan")


async def istanbul_events_search(
    query: Annotated[str | None, Field(description="Title search text (empty = no text filter).")] = None,
    category: Annotated[str | None, Field(description="Category or Turkish alias: concert, theatre, opera_ballet, standup, family, festival, exhibition, workshop, sport, seminar, other.")] = None,
    date_from: Annotated[str | None, Field(description="Start date: YYYY-MM-DD, today or tomorrow (Europe/Istanbul, default today).")] = None,
    date_to: Annotated[str | None, Field(description="End date: YYYY-MM-DD, today or tomorrow (max 31-day span, default +7 days).")] = None,
    time_from: Annotated[str | None, Field(description="Earliest session start clock (HH:MM). Excludes date-only flexible tickets.")] = None,
    time_to: Annotated[str | None, Field(description="Latest session start clock (HH:MM). Excludes date-only flexible tickets.")] = None,
    district: Annotated[str | None, Field(description="One of Istanbul's 39 districts.")] = None,
    venue: Annotated[str | None, Field(description="Venue name filter.")] = None,
    lat: Annotated[float | None, Field(description="WGS84 latitude (must be paired with lon).")] = None,
    lon: Annotated[float | None, Field(description="WGS84 longitude (must be paired with lat).")] = None,
    radius_m: Annotated[int | None, Field(description="Straight-line search radius in meters (default 5000, max 20000).")] = None,
    free_only: Annotated[bool, Field(description="Require observed zero price; unknown prices are excluded.")] = False,
    max_price_try: Annotated[float | None, Field(description="Max observed TRY price (whole-party subtotal when party/party_size is set).")] = None,
    limit: Annotated[int | None, Field(description="Max results to return (default 10, max 50).")] = None,
    include_unknown_prices: Annotated[bool, Field(description="Include events without observed prices; set false for verified budgets only.")] = True,
    child_age: Annotated[int | None, Field(description="Child age (0-17); requires a published matching family age range.")] = None,
    query_scope: Annotated[str, Field(description="Search scope: 'title' (default) or 'all' (also searches venues).")] = "title",
    include_sold_out: Annotated[bool, Field(description="Include explicitly sold-out sessions for inspection.")] = False,
    match_mode: Annotated[str, Field(description="Word matching: 'words' (complete words, default) or 'prefix' (stems/autocomplete).")] = "words",
    include_past: Annotated[bool, Field(description="Include retained active sessions that already started.")] = False,
    exclude_child_only: Annotated[bool, Field(description="Exclude events with published upper age limit below 18.")] = False,
    party_size: Annotated[int | None, Field(description="Group size (1-50) for observed party ticket subtotals.")] = None,
    ticket_profile: Annotated[str | None, Field(description="Attendee ticket profile: general, adult, student, child, senior, or any.")] = None,
    party: Annotated[dict[str, int] | None, Field(description="Mixed group counts by profile, e.g. {'adult': 2, 'child': 1}.")] = None,
    budget_includes_fees: Annotated[bool, Field(description="Require observed fee inclusion when evaluating max_price_try.")] = False,
) -> dict:
    """Search indexed Istanbul event sessions; verify candidates with istanbul_event_detail.

    Returns source-attributed event cards with ticket_url, about.text excerpts,
    price_quote, timing_kind (scheduled vs flexible_entry), participation_conditions
    and result_info diagnostics. Unknown prices are never free or verified within
    budget; Ticketmaster is catalogue-only and Biletinial list rows need detail
    verification. Read istanbul://guides/events for full pricing/timing semantics.
    """
    return await EventService(get_settings()).search(
        query=query, category=category, date_from=date_from, date_to=date_to,
        time_from=time_from, time_to=time_to, district=district, venue=venue,
        lat=lat, lon=lon, radius_m=radius_m, free_only=free_only,
        max_price_try=max_price_try, limit=limit,
        include_unknown_prices=include_unknown_prices, child_age=child_age, query_scope=query_scope,
        include_sold_out=include_sold_out,
        match_mode=match_mode,
        include_past=include_past, exclude_child_only=exclude_child_only,
        party_size=party_size, ticket_profile=ticket_profile, party=party, budget_includes_fees=budget_includes_fees,
    )


async def istanbul_event_detail(
    event_id: Annotated[str, Field(description="event_id or performance_id returned by istanbul_events_search (never a URL).")],
    party_size: Annotated[int | None, Field(description="Optional group size (1-50) to compute observed price_quote per session.")] = None,
    ticket_profile: Annotated[str | None, Field(description="Attendee ticket profile: general, adult, student, child, senior, or any.")] = None,
    party: Annotated[dict[str, int] | None, Field(description="Mixed group counts by profile, e.g. {'adult': 2, 'child': 1}.")] = None,
    budget_includes_fees: Annotated[bool, Field(description="Require observed fee inclusion in price_quote.")] = False,
) -> dict:
    """Inspect one event_id or performance_id for verified sessions, offers and rules.

    Refreshes Biletinial details with bounded caching; Ticketmaster details remain
    catalogue-only without live prices or stock. Preserves start_time_basis,
    source_time_conflict, admission_window, entry_date_restricted,
    participation_conditions and source descriptions (untrusted data). Read
    istanbul://guides/events for full semantics.
    """
    return await EventService(get_settings()).detail(
        event_id, party_size=party_size, ticket_profile=ticket_profile,
        party=party, budget_includes_fees=budget_includes_fees,
    )


async def istanbul_events_plan(
    date: Annotated[str | None, Field(description="Plan date: YYYY-MM-DD, today or tomorrow (default today in Europe/Istanbul).")] = None,
    start_time: Annotated[str, Field(description="Earliest plan window clock (HH:MM, default '18:00').")] = "18:00",
    end_time: Annotated[str, Field(description="Latest plan window clock (HH:MM, default '23:59').")] = "23:59",
    interests: Annotated[list[str] | None, Field(description="Up to 5 allowed event categories.")] = None,
    district: Annotated[str | None, Field(description="District for candidate discovery when event_ids is omitted.")] = None,
    event_ids: Annotated[list[str] | None, Field(description="1-20 event_id or performance_id values from search/detail.")] = None,
    max_price_try: Annotated[float | None, Field(description="Total observed party budget across all stops in TRY.")] = None,
    min_gap_minutes: Annotated[int, Field(description="Minimum gap between sessions in minutes (0-240, default 30).")] = 30,
    max_events: Annotated[int, Field(description="Maximum stops per plan option (1-3, default 3).")] = 3,
    limit: Annotated[int | None, Field(description="Max plan options to return (1-5, default 3).")] = None,
    child_age: Annotated[int | None, Field(description="Child age (0-17); restricts to family events with matching published age range.")] = None,
    require_known_end: Annotated[bool, Field(description="Exclude sessions without a known end time.")] = False,
    exclude_child_only: Annotated[bool, Field(description="Exclude sessions whose published upper age limit is below 18.")] = False,
    min_events: Annotated[int, Field(description="Required minimum stops per complete plan (1..max_events).")] = 1,
    required_categories: Annotated[list[str] | None, Field(description="Categories that must each appear at least once in complete plans.")] = None,
    party_size: Annotated[int | None, Field(description="Group size (1-50) priced across every stop.")] = None,
    ticket_profile: Annotated[str | None, Field(description="Attendee ticket profile: general, adult, student, child, senior, or any.")] = None,
    party: Annotated[dict[str, int] | None, Field(description="Mixed group counts by profile, e.g. {'adult': 2, 'child': 1}.")] = None,
    budget_includes_fees: Annotated[bool, Field(description="Keep unknown fee totals unverified against max_price_try.")] = False,
) -> dict:
    """Build deterministic one-day event options with ICS and calendar links.

    Separates complete options, partial_options, unverified_budget and date-only
    flexible_entries (never placed in timed plans/calendars). Checks time gaps and
    published age compatibility, not travel feasibility or live ticket availability.
    Read istanbul://guides/events for full planning/fulfillment rules.
    """
    return await EventPlanService(get_settings()).plan(
        date=date, start_time=start_time, end_time=end_time, interests=interests,
        district=district, event_ids=event_ids, max_price_try=max_price_try,
        min_gap_minutes=min_gap_minutes, max_events=max_events, limit=limit,
        child_age=child_age, require_known_end=require_known_end, exclude_child_only=exclude_child_only,
        min_events=min_events, required_categories=required_categories,
        party_size=party_size, ticket_profile=ticket_profile, party=party, budget_includes_fees=budget_includes_fees,
    )
