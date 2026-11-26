---
name: istanbul-city-briefing
description: Assemble grounded Istanbul daily briefings, neighborhood profiles, on-duty pharmacies, water/dam status, traffic index, weekly markets, and nearby municipal services. Use when the user asks about Istanbul traffic, ISKI water faults or dams, pharmacies, parking, air quality, markets, or neighborhood data.
license: MIT
---

# Istanbul City Briefing and Local Services

Use this workflow for Istanbul city status summaries, neighborhood data profiles, on-duty pharmacies, water status, weekly markets, and nearby municipal facilities.

## Common Workflows

- **Daily city briefing:** Combine `istanbul_traffic_status`, `istanbul_water_status(kind="faults", district=...)`, and `istanbul_transport_disruptions` with compact limits. Include `istanbul_water_status(kind="dams")` when asked about reservoir levels. Do not invent a district if none was requested; state citywide scope explicitly.
- **Neighborhood profile (`istanbul_neighborhood_profile`):** Summarize 2023 social, building, and earthquake scenario records for the requested district/neighborhood. If no neighborhood is given, list covered neighborhoods rather than guessing one. Always clarify these are historical scenario records — never a live earthquake prediction, individual building safety rating, real-estate score, or emergency guidance.
- **Nearby services (`istanbul_nearby` / `istanbul_city_services_nearby`):**
  - Coordinates (`lat`/`lon` + `radius_m`), `bbox` (`city_feature` only), or `district` (`parking` and `pharmacy` only, without distances).
  - District-only `istanbul_city_services_nearby` returns library and cultural address lists without WiFi or invented distances; point mode adds WiFi.
- **Weekly markets (`istanbul_market_schedule`):** Filter by `district` and day (`today`, `tomorrow`, weekday, or ISO date).

## Mandatory Safety and Boundary Rules

- **On-duty pharmacies (`istanbul_nearby(kind="pharmacy")`):** Always show pharmacy name, district, address, phone number, and clickable `maps_url`. Clearly note that `maps_search_url` is an address search rather than a verified map pin, advise calling before visiting, and never invent duty-end hours. Show source footers only when asked while keeping freshness and safety warnings.
- **Ambiguous place names:** `Acibadem` spans both Kadikoy and Uskudar — ask the user which district they mean rather than assuming. Named places use static reference anchors, not full street-address geocoding.
- **Static snapshots vs live status:** Weekly markets, EV charging stations, taxi stands, Istanbulkart centers, social facilities, libraries, and WiFi locations are published static snapshots — never claim live open/closed or real-time availability status.
- **Traffic and water boundaries:** `istanbul_traffic_status` is a citywide congestion index, not road-level incident reporting. ISKI fault locations are approximate and restoration times are estimates, not guarantees; fallback data may be `stale`.
- **Honest gaps:** Missing results, partial coverage, or unavailable sources never prove low risk or normal service. Always preserve `freshness`, `limits`, `warnings`, and publisher attribution.
