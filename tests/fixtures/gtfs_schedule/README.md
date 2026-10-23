# Synthetic GTFS timetable fixtures

Small, invented data, not actual İstanbul departure times. Three stops and three
routes exercise weekday/weekend services, calendar exceptions, next-day `25:xx`
times, approximate timepoints, no-pickup and untimed intermediate rows.
`stop_times.csv` is zipped in tests at runtime; no binary or full feed is committed.
The grouped stop coordinate matches the already documented İBB formatting defect.

Official CKAN metadata checked with Exa on 2026-10-23 identifies CSV stop_times
resource `23778613-16fe-4d30-b8b8-8ca934ed2978` as **preview only** and ZIP resource
`80401c1c-c240-4a32-8f40-ef697100a681` (22,753,052 bytes) as the full table.
Source: https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi
This does not validate the ZIP's contents or production-scale ingest performance.
