# Istanbul MCP Tool Reference

All tools are read-only and return a standard envelope with `summary`, `data`, `freshness`, `sources`, `limits`, and `warnings`.

When local source back-pressure is active, affected tools return `ok=false` with `retry_after_seconds` in `data[0]`.

## Core

- `istanbul_health()` — service and SQLite readiness.

HTTP status endpoints:

- `GET /healthz`
- `GET /readyz`
- `GET /status` — version, tool inventory, source groups, and runtime limits.

## Catalog

- `istanbul_search_datasets(query, formats?, limit?)`
- `istanbul_get_dataset(dataset_id)`
- `istanbul_get_resource_schema(resource_id)`
- `istanbul_query_resource(resource_id, filters?, limit?)`

## Geo & City Services

- `istanbul_nearby(lat, lon, types?, radius_m?, limit?)`
- `istanbul_bbox_search(bbox, types?, limit?)`
- `istanbul_parking_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_metro_stations_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_air_quality_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_traffic_status()`

## Transit

- `istanbul_transit_line_info(line_code)`
- `istanbul_stops_for_line(line_code)`

IETT SOAP services may be unavailable during nightly maintenance. Transit tools return structured warnings/errors rather than inventing missing data.
