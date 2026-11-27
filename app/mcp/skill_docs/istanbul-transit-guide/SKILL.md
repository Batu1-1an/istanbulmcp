---
name: istanbul-transit-guide
description: Look up Istanbul public transit lines, stops, scheduled IETT and GTFS timetables, service disruptions across IETT, Metro, Marmaray, and Sehir Hatlari, and metro accessibility status. Use when the user asks about Istanbul buses, metros, ferries, departures, or transit disruptions.
license: MIT
---

# Istanbul Transit Guide

Use this workflow for Istanbul public transportation queries involving buses (IETT), Metro Istanbul, Marmaray, Sehir Hatlari ferries, scheduled stop departures, and station equipment status.

## Tool Selection

- **Specific IETT bus line (`500T`, `34A`, `15F`, `E-10`):** Call `istanbul_transit_line` with `action="info"`, `"stops"`, or `"departures"` (`limit` is supported only with `action="departures"`).
- **Scheduled stop departures (when enabled):** Call `istanbul_next_departures` (check `istanbul_gtfs_snapshot_status` if GTFS freshness or warm-up state is in question).
- **Service disruptions and official notices:** Call `istanbul_transport_disruptions` (filter by `operator`: `iett`, `metro`, `marmaray`, `sehir_hatlari`, or by `mode` / `line`).
- **Metro elevators and escalators:** Call `istanbul_metro_accessibility_status` (filter by `line`, `station`, or `equipment_type`).
- **Nearby transit stops and parking:** Call `istanbul_mobility_nearby` with a known reference place, district, or coordinates.
- **Published ferry timetables (only if listed):** Call `istanbul_ferry_schedules`.

## Two-Step GTFS Stop Lookup (`istanbul_next_departures`)

1. When searching by name, call `istanbul_next_departures(stop_query=..., limit=...)`.
2. This call returns **candidate `stop_id` records, not departures**. Present the matching stops (with name/location cues) and ask the user to confirm the exact stop before calling `istanbul_next_departures(stop_id=...)`.
3. Do not guess direction, district, or stop identity from ambiguous name suggestions.

## Strict Accuracy Boundaries

- **No live ETA or A-to-B routing:** IETT `departures` are planned main-terminal times, and GTFS departures are published timetables. Never invent real-time vehicle ETAs, intermediate-stop arrival times, transfer durations, or fastest A-to-B routes.
- **Honest disruption coverage:** If an operator returns `unavailable` or `partial` coverage in `sources[]`, never claim service is normal; state clearly which operators were checked and which were unavailable.
- **Accessibility disclaimer:** Metro equipment counts and active faults reflect published status only and never guarantee end-to-end trip accessibility.
- **Location honesty:** Ask for missing coordinates or line codes; never invent coordinates. District-only `istanbul_mobility_nearby` returns parking without distances.
- **Envelope preservation:** Always reflect `freshness`, `limits`, `warnings`, and publisher attribution (IETT, Metro Istanbul, TCDD Tasimacilik / Marmaray, Sehir Hatlari) in the answer.
