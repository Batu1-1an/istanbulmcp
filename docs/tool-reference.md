# Istanbul MCP Tool Reference

All tools are read-only and return a standard envelope with `summary`, `data`, `freshness`, `sources`, `limits`, and `warnings`.

When local source back-pressure is active, affected tools return `ok=false` with `retry_after_seconds` in `data[0]`.
Expected validation and source failures return `ok=false` envelopes with `error_code`, field/source context, and actionable limits where available.

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

Catalog search results include `relevance`, `datastore_active_count`, and `preferred_resources` to help clients choose queryable datasets.

## Geo & City Services

- `istanbul_nearby(lat, lon, types?, radius_m?, limit?)`
- `istanbul_bbox_search(bbox, types?, limit?)`
- `istanbul_parking_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_metro_stations_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_air_quality_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_traffic_status()`
- `istanbul_mobility_nearby(place?, lat?, lon?, radius_m?, limit?)`
- `istanbul_city_services_nearby(place?, lat?, lon?, radius_m?, limit?)`

Air quality results include `latest_reading_quality` because the upstream source can return station records with missing AQI values. Traffic status is citywide only and explicitly lists unsupported road-level or incident detail.

`istanbul_mobility_nearby` is for practical questions such as nearby parking, metro, public transport stops, air quality, and the citywide traffic index. It accepts either a curated Istanbul `place` name such as `Kadıköy`, `Taksim`, or `Beşiktaş`, or explicit `lat`/`lon`.

`istanbul_city_services_nearby` returns nearby WiFi points and district-level library address/hour records where available. Library records do not have coordinates, so those results are marked as district-level rather than radius-precise.

## Neighborhood Profiles

- `istanbul_neighborhood_profile(district, neighborhood?, limit?)`

Returns a joined neighborhood profile from fixed IBB Open Data CKAN resources: 2023 social-assistance household counts, neighborhood building stock by age/floor band, and earthquake-scenario records. Pass `district` only to list covered neighborhoods; pass both `district` and `neighborhood` for one joined profile.

Neighborhood matching normalizes Turkish characters, source mojibake variants such as `CAFERAÐA`, and source abbreviations such as `19.May`. Earthquake scenario fields are returned as source scenario records only, not as real-time risk, incident, or guidance data.

## Transit

- `istanbul_transit_line_info(line_code)`
- `istanbul_stops_for_line(line_code)`

IETT SOAP services may be unavailable during nightly maintenance. Transit tools return structured warnings/errors rather than inventing missing data.
