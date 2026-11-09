"""Deterministic one-day enumeration; no invented travel or duration estimates."""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from collections import defaultdict
from hashlib import sha256
from itertools import combinations
from decimal import Decimal
import math
from urllib.parse import urlencode

from app.core.envelope import error_envelope
from app.core.error_responses import validation_error_envelope
from app.core.events import CATEGORIES, ISTANBUL, EventOffer, age_suitability, child_only_age_range, event_time, normalize_category, published_age_range
from app.core.geo import haversine_m
from app.core.validation import InputValidationError, resolve_limit, validate_text
from app.services.events import EventService, event_clock, event_date
from app.services.event_pricing import resolve_party, apply_party_quote


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
    links, omitted_ends, omitted_flexible, omitted_unverified, omitted_restricted = [], False, False, False, False
    for card in cards:
        if card.get("entry_date_restricted"):
            omitted_restricted = True
            continue
        if card.get("source") == "biletinial" and not card.get("detail_checked"):
            omitted_unverified = True
            continue
        if card.get("timing_kind") == "flexible_entry":
            omitted_flexible = True
            continue
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
            "warnings": (["Unknown end time: ICS omits DTEND; no Google Calendar link was generated for that session."] if omitted_ends else []) +
                        (["Flexible-entry ticket: no fixed visit time; no calendar event was generated."] if omitted_flexible else []) +
                        (["Biletinial catalogue-only timing needs event detail verification; no calendar event was generated."] if omitted_unverified else []) +
                        (["Source weekday admission restriction: no calendar event was generated for that date."] if omitted_restricted else [])}


def _common_age_range(cards: tuple) -> tuple[bool, str, dict | None]:
    known = [bounds for card in cards if (bounds := published_age_range(card.get("age_limit"))) is not None]
    if not known:
        return True, "unknown", None
    minimum = max(bounds[0] for bounds in known)
    upper = [bounds[1] for bounds in known if bounds[1] is not None]
    maximum = min(upper) if upper else None
    return (maximum is None or minimum <= maximum), ("published_ranges_compatible" if len(known) == len(cards) else "partially_known"), {"minimum":minimum,"maximum":maximum}


def enumerate_plans(cards: list[dict], *, window_end: datetime, max_events=3, min_gap_minutes=30,
                    max_price_try=None, limit=3, interests=(), diagnostics=None, min_events=1, required_categories=(), partial_output=None) -> tuple[list[dict], list[dict]]:
    options = []
    cards = sorted((c for c in cards if c.get("timing_kind") != "flexible_entry" and not c.get("entry_date_restricted")
                    and not (c.get("source") == "biletinial" and not c.get("detail_checked"))),
                   key=lambda c: (c["start_at"], c["performance_id"]))
    for size in range(1, max_events + 1):
        for path in combinations(cards, size):
            if len({c["event_id"] for c in path}) < len(path):
                continue
            age_compatible, age_status, age_range = _common_age_range(path)
            if not age_compatible:
                if diagnostics is not None:
                    diagnostics["age_incompatible_combinations"] = diagnostics.get("age_incompatible_combinations", 0) + 1
                continue
            warnings, gaps = [], []
            if age_status == "unknown":
                warnings.append("No published age requirements were available; participant age suitability is unverified.")
            elif age_status == "partially_known":
                warnings.append("Some published age requirements are unknown; a common participant age is only partially verified.")
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
                if diagnostics is not None:diagnostics['timing_incompatible_combinations']=diagnostics.get('timing_incompatible_combinations',0)+1
                continue
            prices = [c.get("budget_price_try",c["price"]["minimum_observed_try"]) for c in path]
            known_total = float(sum((Decimal(str(p)) for p in prices if p is not None),Decimal(0)))
            lower_total=float(sum((Decimal(str(c.get('budget_lower_bound_try',p) or 0)) for c,p in zip(path,prices)),Decimal(0)))
            if max_price_try is not None and lower_total > max_price_try:
                if diagnostics is not None:diagnostics['over_budget_combinations']=diagnostics.get('over_budget_combinations',0)+1
                continue
            budget_status = "unknown" if any(p is None for p in prices) else "within" if max_price_try is not None else "not_requested"
            if budget_status == "unknown":
                warnings.append("Total price is unknown; the plan is not verified within budget.")
            if any(c["availability"] == "unknown" for c in path):
                warnings.append("Ticket availability is unknown for one or more sessions.")
            if any(c.get("source_time_conflict") for c in path):
                warnings.append("Source time conflict: the published HTML Istanbul session time was used; verify the ticket page before visiting.")
            if any(c["price"].get("eligibility_may_apply") for c in path):
                warnings.append("Observed minimum prices may require a ticket type or eligibility condition; they are not guaranteed per-person general-admission prices.")
            breakdown = {
                "interest": sum(30 if c["category"] in interests else 15 if not interests else 0 for c in path),
                "time_fit": sum(25 if c["end_known"] else 12.5 for c in path),
                "price": sum(10 if p is not None else 5 for p in prices),
                "source": sum(10 if c["detail_checked"] else 5 for c in path),
                "availability": sum(10 if c["availability"] in {"in_stock", "limited"} else 5 for c in path),
                "category_diversity": 30 * max(0, len({c["category"] for c in path}) - 1),
            }
            missing_categories=sorted(set(required_categories)-{c['category'] for c in path})
            missing_events=max(0,min_events-len(path))
            fulfillment={'status':'partial' if missing_events or missing_categories else 'complete',
                         'requested_min_events':min_events,'actual_events':len(path),
                         'missing_events':missing_events,'missing_categories':missing_categories}
            options.append({"fulfillment":fulfillment,"checkout_total_verified":False,
                            "total_price_scope":("observed_fee_inclusive_party_totals" if any(c.get('budget_price_basis')=='observed_fee_inclusive_party_total' for c in path)
                                                 else "observed_party_ticket_subtotals" if any('price_quote' in c for c in path)
                                                 else "observed_minimum_ticket_prices_not_per_person"),"score": round(sum(breakdown.values()), 2), "score_breakdown": breakdown,
                            "performances": list(path), "gaps": gaps, "known_minimum_total_try": known_total,
                            "total_observed_minimum_try": known_total if all(p is not None for p in prices) else None,
                            "total_price_known": all(p is not None for p in prices), "budget_status": budget_status,
                            "checks": {"time_overlap": False, "minimum_gap_checked": True, "travel_feasibility_verified": False,
                                       "window_end_verified": all(c["end_known"] for c in path),
                                       "age_compatibility": age_status, "common_published_age_range": age_range},
                            "warnings": list(dict.fromkeys(warnings))})
    options.sort(key=lambda p: (-p["score"], tuple(c["start_at"] for c in p["performances"]), tuple(c["performance_id"] for c in p["performances"])))
    partials=[p for p in options if p['fulfillment']['status']=='partial']
    options=[p for p in options if p['fulfillment']['status']=='complete']
    if partial_output is not None:
        partial_output.extend(diverse_options(partials,limit))
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


def choose_candidates(cards: list[dict], limit: int = 20, required_categories=()) -> list[dict]:
    """Spread the finite candidate budget over the day and distinct series."""
    if required_categories:
        quota=max(1,limit//len(required_categories));selected=[];seen=set()
        for category in required_categories:
            for c in choose_candidates([c for c in cards if c['category']==category],quota):
                if c['performance_id'] not in seen:
                    selected.append(c);seen.add(c['performance_id'])
        for c in choose_candidates([c for c in cards if c['performance_id'] not in seen],limit):
            if len(selected)>=limit:break
            selected.append(c)
        return selected
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
                   child_age=None, require_known_end=False, exclude_child_only=False,
                   min_events=1, required_categories=None, party_size=None, ticket_profile=None,
                   party=None, budget_includes_fees=False):
        if not self.events.settings.events_enabled:
            return self.events.disabled()
        try:
            party=resolve_party(party_size,ticket_profile,party)
            if budget_includes_fees and party is None:party={'general':1}
            day = event_date(date, field="date")
            start, end = event_clock(start_time, "start_time"), event_clock(end_time, "end_time")
            if start is None or end is None or end <= start:
                raise InputValidationError("Provide an increasing same-day HH:MM window", field="end_time")
            if isinstance(max_events, bool) or not isinstance(max_events, int) or not 1 <= max_events <= 3:
                raise InputValidationError("max_events must be 1–3", field="max_events")
            if isinstance(min_events,bool) or not isinstance(min_events,int) or not 1<=min_events<=max_events:
                raise InputValidationError('min_events must be 1–max_events',field='min_events')
            if required_categories is not None:
                if not required_categories or len(required_categories)>3:
                    raise InputValidationError('required_categories must contain 1–3 supported types',field='required_categories')
                required_categories=list(dict.fromkeys(normalize_category(c) for c in required_categories))
                if any(c not in CATEGORIES for c in required_categories) or len(required_categories)>max_events:
                    raise InputValidationError('required_categories must fit max_events and use supported types',field='required_categories')
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
            if required_categories and interests and not set(required_categories)<=set(interests):
                raise InputValidationError('required_categories must be allowed by interests',field='required_categories')
            if event_ids is not None and (not event_ids or len(event_ids) > 20):
                raise InputValidationError("event_ids must contain 1–20 IDs from search", field="event_ids")
            if event_ids is not None:
                event_ids = [validate_text(identifier, field="event_ids", max_length=64) for identifier in event_ids]
            if event_ids is not None and district is not None:
                raise InputValidationError("Use selected event_ids or district discovery", field="district")
            safe_limit = resolve_limit(limit, 3, 5)
        except InputValidationError as exc:
            return validation_error_envelope(exc)
        discovery_diagnostics=[]
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
                                                   time_to=end_time, district=district, category=category, child_age=child_age, exclude_child_only=exclude_child_only,
                                                   max_price_try=max_price_try, limit=self.events.settings.events_max_rows, party=party, budget_includes_fees=budget_includes_fees, _planning=True)
                if not response["ok"]:
                    return response
                if envelope is None:
                    envelope = response
                else:
                    envelope["warnings"].extend(response["warnings"])
                discovery_diagnostics.append({"category":category,"result_info":response.get("result_info")})
                cards.extend(response["data"])
                truncated = truncated or response["result_info"]["truncated"]
        if party is not None and event_ids is not None:
            for card in cards:
                apply_party_quote(card,[EventOffer.model_validate(o) for o in card.get('offers',[])],party,
                                  budget=max_price_try,includes_fees=budget_includes_fees)
        window_start, window_end = datetime.combine(day, start, ISTANBUL), datetime.combine(day, end, ISTANBUL)
        rejected, candidates, flexible_entries, seen = [], [], [], set()
        for card in cards:
            if card["performance_id"] in seen:
                continue
            seen.add(card["performance_id"])
            reason = None
            flexible = card.get("timing_kind") == "flexible_entry"
            if flexible and card["event_date"] != day.isoformat():
                reason = "outside_time_window"
            elif not flexible and not window_start <= event_time(card["start_at"]) <= window_end:
                reason = "outside_time_window"
            elif (day < datetime.now(ISTANBUL).date() if flexible else event_time(card["start_at"]) < datetime.now(ISTANBUL)):
                reason = "session_already_started"
            elif card.get("entry_date_restricted"):
                reason = "entry_date_restricted"
            elif card["program_status"] in {"cancelled", "postponed"}:
                reason = "program_unavailable"
            elif card["availability"] == "sold_out" or card["sales_status"] == "sales_closed":
                reason = "ticket_sales_unavailable"
            elif interests and card["category"] not in interests:
                reason = "outside_requested_categories"
            elif exclude_child_only and child_only_age_range(card.get("age_limit")):
                reason = "child_only_age_range"
            elif child_age is not None and age_suitability(card.get("age_limit"), child_age) != "within":
                reason = "age_not_verified_or_outside"
            elif card.get("source") == "biletinial" and not card.get("detail_checked"):
                reason = "session_detail_required"
            elif flexible:
                if max_price_try is not None and card.get("budget_price_try",card["price"]["minimum_observed_try"]) is not None and card.get("budget_price_try",card["price"]["minimum_observed_try"]) > max_price_try:
                    reason = "over_budget"
                else:
                    reason = "flexible_entry_requires_visit_time"
                    flexible_entries.append(card)
            elif require_known_end and not card["end_known"]:
                reason = "end_time_unknown"
            elif card["end_known"] and event_time(card["end_at"]) > window_end:
                reason = "ends_after_window"
            if reason:
                rejected.append({"performance_id": card["performance_id"], "reason": reason})
            else:
                candidates.append(card)
        candidate_count = len(candidates)
        evaluated = choose_candidates(candidates,required_categories=required_categories or ())
        diagnostics = {"age_incompatible_combinations":0}
        partials=[]
        options, unverified = enumerate_plans(evaluated, window_end=window_end, max_events=max_events,
                                              min_gap_minutes=min_gap_minutes, max_price_try=max_price_try,
                                              limit=safe_limit, interests=interests or (), diagnostics=diagnostics,
                                              min_events=min_events,required_categories=required_categories or (),partial_output=partials)
        envelope["data"] = [{"date": day.isoformat(), "window": {"start": start_time, "end": end_time},
                             "discovery_diagnostics":discovery_diagnostics,"combination_diagnostics":diagnostics,
                             "options": options, "unverified_budget": unverified, "partial_options":partials,"rejected": rejected,
                             "fulfillment":{"status":"complete" if options else "partial" if partials else "unverified_budget" if unverified else "unmet",
                                            "requested_min_events":min_events,"requested_max_events":max_events,
                                            "required_categories":required_categories or [],"complete_option_count":len(options),
                                            "partial_option_count":len(partials)},"party":party,"budget_includes_fees":budget_includes_fees,
                             "flexible_entries": flexible_entries[:20],
                             "flexible_entry_count": len(flexible_entries), "flexible_entries_truncated": len(flexible_entries) > 20,
                             "age_incompatible_combinations": diagnostics["age_incompatible_combinations"],
                             "candidate_count": candidate_count, "evaluated_candidates": min(candidate_count, 20),
                             "candidate_truncated": bool(truncated or candidate_count > 20),
                             "ranking_scope": "evaluated candidates only; not a city-wide optimum"}]
        reasons=[]
        if not options:
            if partials:
                if any(p['fulfillment']['missing_events'] for p in partials):reasons.append('minimum_stops_not_met')
                if any(p['fulfillment']['missing_categories'] for p in partials):reasons.append('required_categories_not_met')
            if unverified:reasons.append('party_budget_unverified')
            reasons += sorted({r['reason'] for r in rejected})
            if diagnostics.get('over_budget_combinations'):reasons.append('observed_basket_over_budget')
            if diagnostics.get('timing_incompatible_combinations'):reasons.append('no_compatible_observed_times')
            for discovery in discovery_diagnostics:
                reasons += (discovery.get('result_info') or {}).get('empty_reasons',[])
            if not reasons:reasons=['no_complete_option_in_evaluated_candidates']
        envelope['data'][0]['fulfillment']['reason_codes']=list(dict.fromkeys(reasons))
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
        if exclude_child_only:
            envelope["warnings"].append("exclude_child_only excludes only published upper age limits below 18; unknown age requirements and the participant's actual age suitability are not verified.")
        if diagnostics["age_incompatible_combinations"]:
            envelope["warnings"].append(f"{diagnostics['age_incompatible_combinations']} combination(s) excluded because published age ranges have no common participant age.")
        if any(item["reason"] == "entry_date_restricted" for item in rejected):
            envelope["warnings"].append("Selected ticket dates excluded by an explicit source weekday admission rule; choose a permitted date and verify remaining conditions on the ticket page.")
        if flexible_entries:
            envelope["warnings"].append("Flexible-entry tickets are listed separately in flexible_entries: choose and verify a visit time, opening hours and admission conditions before making a timed plan or calendar entry.")
            envelope["result_info"]["next_step"] = "Inspect flexible_entries and verify a visit time and admission conditions on the ticket page; no timed stop or calendar entry was generated for them."
        if any(item["reason"] == "session_detail_required" for item in rejected):
            envelope["warnings"].append("Biletinial catalogue-only sessions were not scheduled: call istanbul_event_detail to verify whether each ticket has a fixed start or flexible entry.")
        outside_window = sum(item["reason"] == "outside_time_window" for item in rejected)
        if event_ids is not None and outside_window:
            instruction = (f"{outside_window} selected session(s) are outside date={day.isoformat()} "
                           f"and window {start_time}–{end_time}. Set date to the selected session's day "
                           "and supply start_time/end_time explicitly; the default window is 18:00–23:59.")
            envelope["warnings"].append(instruction)
            if not options:
                envelope["result_info"]["next_step"] = instruction
        if partials:
            envelope['warnings'].append('partial_options do not satisfy the requested minimum stops or required categories; no calendar is generated until the user chooses a partial alternative.')
            if not options:envelope['result_info']['next_step']='Inspect partial_options.fulfillment for missing stops/categories; do not present a partial alternative as a complete requested plan.'
        if party is not None:
            envelope['warnings'].append('Plan prices use the requested party ticket baskets. Fees, eligibility, live group quantities and adjacent seats remain unverified unless explicitly observed; this is not a checkout confirmation.')
        if not options:
            envelope["warnings"].append("No verified plan was found; inspect unverified_budget and rejected sessions.")
        return envelope


async def asyncio_snapshots(events):
    import asyncio
    return await asyncio.to_thread(events.repository.snapshots)
