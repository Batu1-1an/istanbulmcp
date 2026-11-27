# Istanbul Events Detailed Rules

## Pricing, Free Events, and Group Budgets

- **Unknown prices are never free or within budget.**
- Use `free_only=true` for observed zero-priced events.
- Use `include_unknown_prices=false` whenever the user requests a verified budget ceiling.
- With `party_size` + `ticket_profile` or a mixed `party` map (such as `{"adult": 2, "child": 1}`), pass the **whole-party total budget** as `max_price_try` without dividing it per person (per event in search, across all stops in plan).
- Never multiply a single minimum ticket price by party size to invent an exact total; rely on `price_quote` and `total_price_known`.
- When `total_price_known=false`, clearly describe `known_minimum_total_try` as a partial subtotal only.
- When `budget_includes_fees=true`, events with unknown checkout or service fees remain unverified.
- Observed `onsale` / `in_stock` statuses never guarantee live checkout prices or adjacent seats.

## Timing and Flexible-Entry Tickets

- `timing_kind="flexible_entry"` tickets have `event_date` with `start_at=null`. Their `source_start_at` is catalogue metadata, never a visit time.
- Never place `flexible_entries` into timed itineraries or ICS calendars; instruct the user to verify visiting hours and entry rules on the source page.
- `admission_window` last-entry clocks are not event start times.
- Never recommend dates with `entry_date_restricted=true`.
- When `source_time_conflict=true`, Istanbul HTML session times took precedence over conflicting JSON-LD timestamps; mention the warning when relevant.
- If the user requires a strict finish time, pass both `end_time` and `require_known_end=true`.

## Age Eligibility and Fulfillment

- `child_age` (0–17) accepts only events with a published compatible family age range; never assume unstated age eligibility.
- When adults want non-children events, pass `exclude_child_only=true` to filter out published upper age limits below 18 without guessing the user's numeric age. Because events without a published upper age limit (including some `family` listings) remain eligible, combine with explicit `category` or `interests` (such as `theatre`, `concert`, `standup`) when adult genres are desired.
- In plans, compare `common_published_age_range` against the user's stated ages.
- Keep `min_events`, `max_events`, and `required_categories` aligned with the user's request. If a plan returns `fulfillment.status="partial"` or `"unmet"`, explain `fulfillment` and which stops or categories were missing instead of passing off `partial_options` as complete.

## Search Modes, Availability, and Conditions

- `match_mode="words"` (default) matches complete normalized words. Use `match_mode="prefix"` only for stems or autocomplete, and present prefix matches as related results rather than verified artist identity.
- Started sessions are excluded unless `include_past=true`; sold-out sessions are excluded unless `include_sold_out=true`.
- Distinguish unknown venue locations from out-of-area exclusions using `empty_reasons` and location counters.
- Check `participation_conditions` for language, entry, reservation, or refund statements; if absent, state that the source did not publish them. Never treat expired or unknown conditions as active confirmation.
