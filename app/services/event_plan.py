"""Deterministic one-day enumeration; no invented travel or duration estimates."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
import math
from urllib.parse import urlencode

from app.core.envelope import error_envelope
from app.core.error_responses import validation_error_envelope
from app.core.events import CATEGORIES, ISTANBUL, age_suitability, event_time, normalize_category
from app.core.geo import haversine_m
from app.core.validation import InputValidationError, resolve_limit, validate_text
from app.services.events import EventService, event_clock, event_date


def _ics_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\r", "").replace("\n", "\\n").replace(";", "\\;").replace(",", "\\,")


def _fold_ics(line: str) -> str:
    lines, current, count = [], "", 0
    for char in line:
        size = len(char.encode("utf-8"))
        if count + size > 75:
            lines.append(current)
            current, count = " ", 1
        current += char
        count += size
    return "\r\n".join([*lines, current])


def calendar_output(cards: list[dict]) -> dict:
    lines = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Istanbul MCP//Events//TR", "CALSCALE:GREGORIAN", "X-WR-TIMEZONE:Europe/Istanbul"]
    links, omitted_ends = [], False
    for card in cards:
        start, end = event_time(card["start_at"]), event_time(card["end_at"])
        stamp = lambda dt: dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        venue = card["venue"]["name"]
        uid = sha256(card["performance_id"].encode()).hexdigest()[:24]
        lines += ["BEGIN:VEVENT", f"UID:perf-{uid}@istanbulmcp", "DTSTAMP:" + stamp(event_time(card["last_checked_at"])),
                  "DTSTART:" + stamp(start), "SUMMARY:" + _ics_text(card["title"]), "LOCATION:" + _ics_text(venue)]
        if end:
            lines.append("DTEND:" + stamp(end))
            links.append({"performance_id": card["performance_id"], "url": "https://calendar.google.com/calendar/render?" + urlencode({
                "action": "TEMPLATE", "text": card["title"], "dates": stamp(start) + "/" + stamp(end),
                "ctz": "Europe/Istanbul", "location": venue, "details": card["ticket_url"] or "Verify the source before visiting."})})
        else:
            omitted_ends = True
            lines.append("DESCRIPTION:End time unknown. Verify source before visiting.")
        lines += ["END:VEVENT"]
    lines.append("END:VCALENDAR")
    return {"ics": "\r\n".join(_fold_ics(line) for line in lines) + "\r\n", "google_calendar_links": links,
            "warnings": ["Unknown end time: ICS omits DTEND; no Google Calendar link was generated for that session."] if omitted_ends else []}


def enumerate_plans(cards: list[dict], *, window_end: datetime, max_events=3, min_gap_minutes=30,
                    max_price_try=None, limit=3, interests=()) -> tuple[list[dict], list[dict]]:
    options = []
    cards = sorted(cards, key=lambda c: (c["start_at"], c["performance_id"]))
    for size in range(1, max_events + 1):
        for path in combinations(cards, size):
            if len({c["event_id"] for c in path}) < len(path):
                continue
            warnings, gaps = [], []
            valid = True
            for i, card in enumerate(path):
                end = event_time(card["end_at"])
                if end is None:
                    if i != len(path) - 1:
                        valid = False
                        break
                    warnings.append("Last session has unknown end time; completion within the requested window is unverified.")
                elif end > window_end:
                    valid = False
                    break
                if i:
                    previous = path[i - 1]
                    gap = (event_time(card["start_at"]) - event_time(previous["end_at"])).total_seconds() / 60
                    if gap < min_gap_minutes:
                        valid = False
                        break
                    a, b = previous["venue"], card["venue"]
                    distance = haversine_m(a["lat"], a["lon"], b["lat"], b["lon"]) if all(v is not None for v in (a["lat"], a["lon"], b["lat"], b["lon"])) else None
                    if a["side"] and b["side"] and a["side"] != b["side"]:
                        warnings.append("Boğaz geçişi gerekir; ulaşım süresi hesaplanmadı.")
                    elif distance is None:
                        warnings.append("Venue distance is unknown; only the requested minimum gap was checked.")
                    gaps.append({"minutes": gap, "straight_line_distance_m": round(distance) if distance is not None else None,
                                 "travel_time_minutes": None})
            if not valid:
                continue
            prices = [c["price"]["minimum_observed_try"] for c in path]
            known_total = sum(p for p in prices if p is not None)
            if max_price_try is not None and known_total > max_price_try:
                continue
            budget_status = "unknown" if any(p is None for p in prices) else "within" if max_price_try is not None else "not_requested"
            if budget_status == "unknown":
                warnings.append("Total price is unknown; the plan is not verified within budget.")
            if any(c["availability"] == "unknown" for c in path):
                warnings.append("Ticket availability is unknown for one or more sessions.")
            breakdown = {
                "interest": sum(30 if c["category"] in interests else 15 if not interests else 0 for c in path),
                "time_fit": sum(25 if c["end_known"] else 12.5 for c in path),
                "price": sum(10 if p is not None else 5 for p in prices),
                "source": sum(10 if c["detail_checked"] else 5 for c in path),
                "availability": sum(10 if c["availability"] in {"in_stock", "limited"} else 5 for c in path),
                "category_diversity": 30 * max(0, len({c["category"] for c in path}) - 1),
            }
            options.append({"score": round(sum(breakdown.values()), 2), "score_breakdown": breakdown,
                            "performances": list(path), "gaps": gaps, "known_minimum_total_try": known_total,
                            "total_observed_minimum_try": known_total if all(p is not None for p in prices) else None,
                            "total_price_known": all(p is not None for p in prices), "budget_status": budget_status,
                            "checks": {"time_overlap": False, "minimum_gap_checked": True, "travel_feasibility_verified": False,
                                       "window_end_verified": all(c["end_known"] for c in path)},
                            "warnings": list(dict.fromkeys(warnings))})
    options.sort(key=lambda p: (-p["score"], tuple(c["start_at"] for c in p["performances"]), tuple(c["performance_id"] for c in p["performances"])))
    verified = [p for p in options if max_price_try is None or p["budget_status"] != "unknown"]
    unverified = [p for p in options if max_price_try is not None and p["budget_status"] == "unknown"]
    verified, unverified = diverse_options(verified, limit), diverse_options(unverified, limit)
    for option in [*verified, *unverified]:
        option["calendar"] = calendar_output(option["performances"])
    return verified, unverified


def diverse_options(options: list[dict], limit: int) -> list[dict]:
    """Prefer known observed totals, then penalize overlap with shown event series."""
    remaining, seen = [], set()
    for option in sorted(options, key=lambda item: (not item["total_price_known"], -item["score"],
                         tuple(card["performance_id"] for card in item["performances"]))):
        identity = frozenset(card["event_id"] for card in option["performances"])
        if identity not in seen:
            seen.add(identity)
            remaining.append((option, identity))
    selected, chosen_series = [], []
    while remaining and len(selected) < limit:
        def rank(entry):
            option, identity = entry
            overlap = max((len(identity & other) / len(identity | other) for other in chosen_series), default=0)
            return (not option["total_price_known"], -(option["score"] - 60 * overlap), -option["score"],
                    tuple(card["performance_id"] for card in option["performances"]))
        winner = min(remaining, key=rank)
        remaining.remove(winner)
        selected.append(winner[0])
        chosen_series.append(winner[1])
    return selected


def choose_candidates(cards: list[dict], limit: int = 20) -> list[dict]:
    """Spread the finite candidate budget over the day and distinct series."""
    buckets = defaultdict(list)
    for card in sorted(cards, key=lambda c: (not c["end_known"], not c["detail_checked"], c["start_at"], c["performance_id"])):
        buckets[card["start_at"][:13]].append(card)
    hours = sorted(buckets)
    if len(hours) > limit:
        hours = [hours[round(i * (len(hours) - 1) / (limit - 1))] for i in range(limit)] if limit > 1 else hours[:1]
        buckets = {hour: buckets[hour] for hour in hours}
    selected, seen_series = [], set()
    while len(selected) < limit and any(buckets.values()):
        progressed = False
        for hour in sorted(buckets):
            candidate = next((c for c in buckets[hour] if c["event_id"] not in seen_series), None)
            if candidate is None:
                continue
            buckets[hour].remove(candidate)
            selected.append(candidate)
            seen_series.add(candidate["event_id"])
            progressed = True
            if len(selected) == limit:
                break
        if not progressed:
            seen_series.clear()
    return selected


class EventPlanService:
    def __init__(self, settings, *, events=None):
        self.events = events or EventService(settings)

    async def plan(self, *, date=None, start_time="18:00", end_time="23:59", interests=None,
                   district=None, event_ids=None, max_price_try=None, min_gap_minutes=30, max_events=3, limit=None,
                   child_age=None, require_known_end=False):
        if not self.events.settings.events_enabled:
            return self.events.disabled()
        try:
            day = event_date(date, field="date")
            start, end = event_clock(start_time, "start_time"), event_clock(end_time, "end_time")
            if start is None or end is None or end <= start:
                raise InputValidationError("Provide an increasing same-day HH:MM window", field="end_time")
            if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 3:
                raise InputValidationError("max_events must be 1–3", field="max_events")
            if isinstance(min_gap_minutes, bool) or not isinstance(min_gap_minutes, int) or not 0 <= min_gap_minutes <= 240:
                raise InputValidationError("min_gap_minutes must be 0–240", field="min_gap_minutes")
            if max_price_try is not None and (isinstance(max_price_try, bool) or not math.isfinite(max_price_try) or max_price_try < 0):
                raise InputValidationError("max_price_try must be finite and nonnegative", field="max_price_try")
            if interests is not None:
                if not interests or len(interests) > 5:
                    raise InputValidationError("interests must contain 1–5 supported categories", field="interests")
                interests = list(dict.fromkeys(normalize_category(i) for i in interests))
                if not interests or len(interests) > 5 or any(i not in CATEGORIES for i in interests):
                    raise InputValidationError("interests must contain 1–5 supported categories", field="interests")
            if child_age is not None:
                if isinstance(child_age, bool) or not isinstance(child_age, int) or not 0 <= child_age <= 17:
                    raise InputValidationError("child_age must be 0–17", field="child_age")
                if interests and "family" not in interests:
                    raise InputValidationError("child_age requires family interests", field="interests")
                interests = ["family"]
            if event_ids is not None and (not event_ids or len(event_ids) > 20):
                raise InputValidationError("event_ids must contain 1–20 IDs from search", field="event_ids")
            if event_ids is not None:
                event_ids = [validate_text(identifier, field="event_ids", max_length=64) for identifier in event_ids]
            if event_ids is not None and district is not None:
                raise InputValidationError("Use selected event_ids or district discovery", field="district")
            safe_limit = resolve_limit(limit, 3, 5)
        except InputValidationError as exc:
            return validation_error_envelope(exc)
        if event_ids is not None:
            cards = []
            for identifier in sorted(set(event_ids)):
                detail = await self.events.detail(identifier)
                if not detail["ok"]:
                    return detail
                value = detail["data"][0]
                if identifier.startswith("perf_"):
                    if value.get("selection_status") != "matched":
                        return error_envelope(summary="The selected session is missing or ambiguous after source verification.",
                                              warning="Search or inspect event detail again and select an exact current performance_id.", code="selection_changed", freshness_status="unknown")
                    selected_ids = set(value["selected_performance_ids"])
                    cards.extend(card for card in value["performances"] if card["performance_id"] in selected_ids)
                else:
                    cards.extend(value["performances"])
            snapshots = await asyncio_snapshots(self.events)
            envelope = self.events._envelope("Selected-event plan.", [], snapshots)
            truncated = False
        else:
            cards, truncated, envelope = [], False, None
            for category in interests or [None]:
                response = await self.events.search(date_from=day.isoformat(), date_to=day.isoformat(), time_from=start_time,
                                                   time_to=end_time, district=district, category=category, child_age=child_age,
                                                   max_price_try=max_price_try, limit=self.events.settings.events_max_rows, _planning=True)
                if not response["ok"]:
                    return response
                if envelope is None:
                    envelope = response
                else:
                    envelope["warnings"].extend(response["warnings"])
                cards.extend(response["data"])
                truncated = truncated or response["result_info"]["truncated"]
        window_start, window_end = datetime.combine(day, start, ISTANBUL), datetime.combine(day, end, ISTANBUL)
        rejected, candidates, seen = [], [], set()
        for card in cards:
            if card["performance_id"] in seen:
                continue
            seen.add(card["performance_id"])
            reason = None
            if not window_start <= event_time(card["start_at"]) <= window_end:
                reason = "outside_time_window"
            elif day == datetime.now(ISTANBUL).date() and event_time(card["start_at"]) < datetime.now(ISTANBUL):
                reason = "session_already_started"
            elif card["program_status"] in {"cancelled", "postponed"}:
                reason = "program_unavailable"
            elif card["availability"] == "sold_out" or card["sales_status"] == "sales_closed":
                reason = "ticket_sales_unavailable"
            elif interests and card["category"] not in interests:
                reason = "outside_requested_categories"
            elif child_age is not None and age_suitability(card.get("age_limit"), child_age) != "within":
                reason = "age_not_verified_or_outside"
            elif require_known_end and not card["end_known"]:
                reason = "end_time_unknown"
            elif card["end_known"] and event_time(card["end_at"]) > window_end:
                reason = "ends_after_window"
            if reason:
                rejected.append({"performance_id": card["performance_id"], "reason": reason})
            else:
                candidates.append(card)
        candidate_count = len(candidates)
        evaluated = choose_candidates(candidates)
        options, unverified = enumerate_plans(evaluated, window_end=window_end, max_events=max_events,
                                              min_gap_minutes=min_gap_minutes, max_price_try=max_price_try,
                                              limit=safe_limit, interests=interests or ())
        envelope["data"] = [{"date": day.isoformat(), "window": {"start": start_time, "end": end_time},
                             "options": options, "unverified_budget": unverified, "rejected": rejected,
                             "candidate_count": candidate_count, "evaluated_candidates": min(candidate_count, 20),
                             "candidate_truncated": bool(truncated or candidate_count > 20),
                             "ranking_scope": "evaluated candidates only; not a city-wide optimum"}]
        envelope["data"][0]["requested_categories"] = interests
        envelope["data"][0]["child_age"] = child_age
        envelope["data"][0]["require_known_end"] = require_known_end
        envelope["summary"] = f"{len(options)} daily event plan option(s); travel feasibility is unverified."
        envelope["limits"] = [value for value in envelope["limits"] if not value.startswith("limit=")]
        envelope["result_info"] = {"returned": len(options), "matched": None, "truncated": None, "scope": "data.options",
                                   "next_step": "Inspect unverified_budget, warnings and candidate_truncated."}
        envelope["limits"] += ["Single day; at most 20 evaluated candidates and 3 sessions per option.",
                                "Time gaps and straight-line distances do not establish travel feasibility.",
                                "Unknown end times are allowed only at the final stop."]
        envelope["warnings"] += ["Ulaşım süresi hesaplanmadı; bilet durumu ve ücretler kaynakta yeniden kontrol edilmeli."]
        outside_window = sum(item["reason"] == "outside_time_window" for item in rejected)
        if event_ids is not None and outside_window:
            instruction = (f"{outside_window} selected session(s) are outside date={day.isoformat()} "
                           f"and window {start_time}–{end_time}. Set date to the selected session's day "
                           "and supply start_time/end_time explicitly; the default window is 18:00–23:59.")
            envelope["warnings"].append(instruction)
            if not options:
                envelope["result_info"]["next_step"] = instruction
        if not options:
            envelope["warnings"].append("No verified plan was found; inspect unverified_budget and rejected sessions.")
        return envelope


async def asyncio_snapshots(events):
    import asyncio
    return await asyncio.to_thread(events.repository.snapshots)
