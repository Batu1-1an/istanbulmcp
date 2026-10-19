# Istanbul MCP Tool Reference

The default surface has **15 read-only tools**. Legacy names are opt-in via
`MCP_LEGACY_TOOLS_ENABLED=true`; see the [migration table](tool-migration.md).
The target count is a product decision, not a protocol limit.

All results preserve `ok`, `summary`, `data`, `freshness`, `sources`,
`limits`, `warnings`, and optional `pagination`, `geojson`, `next_queries`.
Do not drop stale/partial-source warnings or infer that unavailable means empty.
Expected validation/source failures are structured `ok=false` envelopes.
Local back-pressure includes `retry_after_seconds` where available.

## Core and HTTP

- `istanbul_health()` — service and SQLite readiness without the database path.
- `GET /healthz` — liveness.
- `GET /readyz` — readiness without the database path.
- `GET /status` — actual registered tools, source groups, limits, redacted cache
  metadata (source labels and short hashes, not raw query/filter values).

The remote MCP endpoint is public by default: no key is needed to connect.
A per-client burst limit applies, and client identity comes from the ASGI
server's trusted proxy headers. Setting `MCP_API_KEYS` turns on Bearer
verification (and per-key daily quota); `MCP_AUTH_REQUIRED=true` additionally
refuses to start without keys. See [API access](api-access.md). Static keys are
not OAuth discovery.

Each HTTP app owns its own Streamable HTTP session manager; managers are not
reused after shutdown.

## Catalog

- `istanbul_search_datasets(query, formats?, limit?)`
- `istanbul_get_dataset(dataset_id)`
- `istanbul_get_resource_schema(resource_id)`
- `istanbul_query_resource(resource_id, filters?, limit?)`

Search results expose `relevance`, `datastore_active_count`, and
`preferred_resources`. Record queries are CKAN `datastore_search` with guarded
scalar/scalar-list filters; this endpoint is **not SQL**. Metadata and record
calls use TTL caches and source rate limits.

### Guarded local SQL

`istanbul_datastore_query(resource_id,sql,limit?)` runs one SQLite SELECT over
`records` from one operator-allowlisted, complete bounded DataStore capture.
The default allowlist is empty. This is **not** the unavailable upstream
`datastore_search_sql` API. GROUP BY/aggregates are supported; joins, subqueries,
CTEs, windows, writes and arbitrary functions are not. Output limits are always
enforced (20/100). Incomplete/oversized captures never produce partial totals.
See [SQL setup, safety bounds and freshness](datastore-sql.md).

## Unified location search

`istanbul_nearby(lat?, lon?, types?, radius_m?, limit?, kind?, district?, bbox?)`

Choose one mode: both coordinates, a supported district search, or a
city-feature bounding box. Conflicting/unused arguments are rejected before
source access.

| kind | Scope | Default radius |
|---|---|---:|
| `city_feature` (default) | Parking, metro station, AQ station locations, public transport stops, WiFi; filter with `types` | 1,000 m |
| `parking` | ISPark capacity/availability; coordinates **or district** | 1,000 m |
| `pharmacy` | Current on-duty İBB roster; coordinates **or district** | 1,000 m |
| `istanbulkart` | Official static filling-center locations | 2,000 m |
| `social_facility` | Official locations and verified detail/reservation links | 2,000 m |
| `metro_station` | Metro İstanbul station locations | 1,000 m |
| `air_quality` | Stations **and latest readings** | 5,000 m |
| `water_fault` | ISKI faults ordered by approximate geometry center | 1,000 m |

Global radius maximum: 5,000 m; default/max result limits: 20/100 (configurable).
District lists never invent distances. `bbox` is
`[min_lon,min_lat,max_lon,max_lat]`, available only with `kind="city_feature"`.
`types` accepts `parking`, `metro_station`, `air_quality_station`,
`public_transport_stop`, `wifi`; it does not apply to dedicated kinds.

Coordinates produce `maps_url`. Address-only results may have
`maps_search_url` and `location_precision=address_search`, not a verified pin.

### Pharmacy contract

`kind="pharmacy"` uses the official İstanbul roster
`https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=all`. District matching is exact
after Turkish-character normalization; unknown districts give a successful empty
list. Nearby results exclude missing/invalid coordinates and sort by Haversine
distance; district results retain address-only entries.

Rows include `source_id` (`ibb:` + deterministic hash), name, nullable phone,
province, district, source-preserved district ID, address, coordinates and maps
links. `duty_ends_at` is null because the source supplies no duty-end field.
Show clickable maps links, preserve uncertainty, and advise calling first.
This is not a general pharmacy catalog or a working-hours guarantee.

The roster is fresh for 5 minutes; on failure the last successful roster may
be served as stale until its **total age** reaches 30 minutes. Source totals,
accepted/skipped/geo-eligible counts and warnings remain visible.

### Static location contracts

İstanbulkart selects the latest active DataStore resource in the official
`istanbulkart-dolum-merkezi-bilgileri` package. It preserves dataset/resource IDs,
source timestamps, accepted/skipped counts, terminal type and district where
supplied. The annual/static list says nothing about terminal availability,
balance, stock, queues or operating hours. Fresh TTL: 24 h; configured
stale-if-error window: 7 days beyond TTL.

Social facilities use the official İBB catalog. Missing fields can be filled
from the official XLSX; fallback-only data is explicitly warned. Reservation
links are read-only links attached only after trusted name/address matching.
Fresh TTL: 24 h; stale-if-error window: at most 7 days beyond TTL. No live
availability, capacity, queue or opening-state fields are invented.

### Air quality and composite summaries

`kind="air_quality"` includes `latest_reading_quality` because the source may
publish station metadata with missing AQI/concentration values.
`kind="city_feature", types=["air_quality_station"]` includes locations only.

- `istanbul_traffic_status()`: citywide index, not road-level incidents.
- `istanbul_mobility_nearby(place?,lat?,lon?,radius_m?,limit?)`: parking, metro,
  stops, station locations and traffic summary. Curated reference places such as
  Kadıköy Rıhtım/Taksim/Levent are accepted. District names yield district-wide
  parking without synthetic proximity.
- `istanbul_city_services_nearby(place?,lat?,lon?,radius_m?,limit?)`: WiFi plus
  district-level library addresses/hours. Libraries without coordinates are
  marked as district-level and can have map-search links.

## Water

`istanbul_water_status(kind="faults"|"dams",district?,fault_number?,dam_name?,min_occupancy?,limit?)`

Fault lists can filter district; one fault number is exclusive with district
and limit. Dam filters apply only to dams. For coordinate searches use
`istanbul_nearby(kind="water_fault",lat=...,lon=...)`.

The ISKI service retains its relay/direct/bounded-snapshot chain. Source
capture time and age limits apply; an old or un-timestamped snapshot cannot
masquerade as live. Fault distances use approximate source geometry centers.
No restoration-time guarantee is inferred.

## Neighborhood profiles

`istanbul_neighborhood_profile(district,neighborhood?,limit?)` joins fixed
official 2023 social-assistance, building-stock and earthquake-scenario resources.
District only lists covered neighborhoods; neighborhood selects one joined
profile. Matching tolerates Turkish characters, source mojibake and published
abbreviations. Scenario records are **not real-time risk or emergency guidance**.

## Transit

`istanbul_transit_line(line_code,action="info"|"stops"|"departures",limit?)`

- `info`: IETT line information.
- `stops`: ordered stops with directions/maps links.
- `departures`: planned **main-terminal** departures, not intermediate-stop ETA.
  Only this action accepts limit (20/100 by default).

IETT SOAP can be unavailable during maintenance; failures are structured.

`istanbul_transport_disruptions(mode?,operator?,line?,limit?)` combines IETT
and Metro live statuses, Metro official planned notices, Şehir Hatları
cancellation/service-change notices and Marmaray official urgent notices.
Metro status/notices are separate coverage entries. One unreadable scope must
not become a blanket “no disruptions” answer.

Modes: bus, metro, tram, funicular, cable_car, ferry, suburban_rail.
Operators: iett, metro_istanbul, sehir_hatlari, marmaray.
`line` matches normalized line code or route label exactly; labels are not
fabricated line codes. Limit: 20/100; source cache: 120 s. Partial failures
preserve successful data with `coverage_status=unavailable`, unknown freshness
and warnings. Unsupported live operators (İDO, Turyol, Dentur, minibüs,
taksi-dolmuş) remain explicit limits.

The Şehir Hatları relay is for **cancellation notices only**. A dated general
notice without a line identifier remains a global record. HTTP 403 becomes
unavailable, not checked-empty. Marmaray can fall back from an Angular shell
to the official frontend API using configured `MARMARAY_API_BASIC_TOKEN`.

### Ferry timetable gate

`istanbul_ferry_schedules(route,limit?)` is **off by default**, separately from
legacy mode. Requests from the checked egress on 2026-10-19 returned HTTP 403
challenges; that is not proof of failure from every IP. Set
`FERRY_SCHEDULES_ENABLED=true` only after verifying access from the deployment.
The existing cancellation relay does not implement timetable requests.

When enabled, the service matches a bounded route name against the official
`/tr/seferler` index and fetches only an allowed canonical detail URL.
Responses preserve route, stop, direction, day type, planned departure and
optional sequence/note fields. Sources use `coverage_kind=published_timetable`.
These are static published plans, **not live departures, delays or ETA**.
Limit: 50/100; TTL: 120 s. A route miss is checked-empty without a detail
request; HTTP/markup failures are structured source errors.

## Metro accessibility

`istanbul_metro_accessibility_status(line?,station?,equipment_type?,limit?)`
reads official `GetFaultyEquipments` totals and the independently cached
server-rendered fault page. Fresh TTL is 120 s; total stale age is capped at
900 s. Filters apply to fault details, not summary totals; limit is 50/100.
Source labels and canonical keys are normalized exactly, not substring-matched.

Each result includes `equipment_summary`, `faults`, source, observed time,
limits and freshness. Unknown return text such as `İnceleniyor` is preserved.
No alternative route, working backup, guaranteed repair date or end-to-end
station/journey accessibility is inferred. One failed source is partial;
two failed sources give `ok=false`/broken; checked-empty remains successful.
