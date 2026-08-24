# Istanbul MCP Tool Reference

All tools are read-only and return a standard envelope with `summary`, `data`, `freshness`, `sources`, `limits`, and `warnings`.

When local source back-pressure is active, affected tools return `ok=false` with `retry_after_seconds` in `data[0]`.
Expected validation and source failures return `ok=false` envelopes with `error_code`, field/source context, and actionable limits where available.

Repeated CKAN catalog/resource, IETT line/stop, and air-quality requests use local back-pressure or TTL caches to reduce pressure on source systems. `/status` exposes TTL settings and redacted cache metadata with source labels and short key hashes, not raw user query/filter values.

## Core

- `istanbul_health()` — service and SQLite readiness.

HTTP status endpoints:

- `GET /healthz`
- `GET /readyz` — readiness without local database path disclosure.
- `GET /status` — version, tool inventory, source groups, runtime limits, and redacted cache metadata.

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
- `istanbul_parking_by_district(district, limit?)`
- `istanbul_metro_stations_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_air_quality_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_traffic_status()`
- `istanbul_mobility_nearby(place?, lat?, lon?, radius_m?, limit?)`
- `istanbul_city_services_nearby(place?, lat?, lon?, radius_m?, limit?)`

Air quality results include `latest_reading_quality` because the upstream source can return station records with missing AQI values. Traffic status is citywide only and explicitly lists unsupported road-level or incident detail.

Coordinate-bearing location results include `maps_url`, a Google Maps search URL built from the source `lat`/`lon`. Address-only records can include `maps_search_url` and `location_precision=address_search`; this is a map search link, not a claimed exact coordinate.

`istanbul_parking_by_district` lists ISPark records by the source `district` field and does not calculate or return synthetic distances. It is the right tool for questions such as "Başakşehir'de hangi otoparklar var, doluluk oranı nedir?"

`istanbul_mobility_nearby` is for practical questions such as nearby parking, metro, public transport stops, air quality, and the citywide traffic index. It accepts explicit `lat`/`lon` or curated reference points such as `Kadıköy Rıhtım`, `Taksim`, or `Levent`. If a district name is supplied instead, it returns district-wide parking records without distances and asks for an exact place only when distance matters.

`istanbul_city_services_nearby` returns nearby WiFi points and district-level library address/hour records where available. Library records do not have coordinates, so those results are marked as district-level rather than radius-precise, but include `maps_search_url` when name/address data is available.

## Neighborhood Profiles

- `istanbul_neighborhood_profile(district, neighborhood?, limit?)`

Returns a joined neighborhood profile from fixed IBB Open Data CKAN resources: 2023 social-assistance household counts, neighborhood building stock by age/floor band, and earthquake-scenario records. Pass `district` only to list covered neighborhoods; pass both `district` and `neighborhood` for one joined profile.

Neighborhood matching normalizes Turkish characters, source mojibake variants such as `CAFERAÐA`, and source abbreviations such as `19.May`. Earthquake scenario fields are returned as source scenario records only, not as real-time risk, incident, or guidance data.

## Transit

- `istanbul_transit_line_info(line_code)`
- `istanbul_stops_for_line(line_code)`
- `istanbul_transit_disruptions(line_code?, limit?)`
- `istanbul_planned_departures(line_code, limit?)`

IETT SOAP services may be unavailable during nightly maintenance. Transit tools return structured warnings/errors rather than inventing missing data.

`istanbul_transit_disruptions` returns non-empty current IETT announcements, optionally filtered by an exact normalized `line_code`. `limit` defaults to 20 and is capped at 100. Empty announcement messages are omitted; an empty filtered result is still a successful envelope. Live IETT payloads may also provide a human-readable `route_label`; it is kept separate from the actual line code.

`istanbul_planned_departures` requires a normalized `line_code` and uses the IETT planned-service schedule endpoint. `limit` defaults to 20 and is capped at 100. Results preserve direction, route, day type, and planned departure time, and include the explicit limits `main-terminal planned departures` and `not intermediate-stop ETA`. They are scheduled main-terminal departures, not live intermediate-stop arrival estimates.
