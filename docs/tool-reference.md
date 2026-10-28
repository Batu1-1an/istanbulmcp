# Istanbul MCP Tool Reference

The default surface has **16 read-only tools**. Legacy names are opt-in via
`MCP_LEGACY_TOOLS_ENABLED=true`; see the [migration table](tool-migration.md).
The target count is a product decision, not a protocol limit. The optional
`istanbul_next_departures` and `istanbul_gtfs_snapshot_status` add two tools only
with `GTFS_SCHEDULE_ENABLED=true` (18 with GTFS on, 16 by default). Full-ZIP live
acceptance passed on 2026-10-25 and the production deployment enables them; the
source default stays `false`. All registered tools have explicit human-readable
titles and read-only annotations.

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
reused after shutdown. The SDK is `mcp>=2.3,<3` (`MCPServer`); HTTP transport
options are applied at app construction. Legacy initialize and modern
`2026-07-28` requests share the same guarded, stateless endpoint.

## Resources, prompts and structured output

Three local JSON resources are listed by `resources/list`: `istanbul://coverage`,
`istanbul://sources`, and `istanbul://schema/catalog`. They describe configuration
and capability metadata, **not current upstream health**, and reading them does
not contact external data APIs or expose deployment secrets.

`prompts/list` exposes four user-selected workflows: `gunun_ozeti(district?)`,
`mahalle_ozeti(district,neighborhood?)`, `veri_kesfi(query)` and
`yolculuk_plani(origin,destination,line_code?)`. Prompt rendering does not execute
tools; the travel workflow is not a route engine or live ETA. Arguments are
bounded printable strings (1–200 characters per supplied value).

Six default tools publish the canonical `ResponseEnvelope` output schema:
`istanbul_nearby` (including pharmacy), `istanbul_traffic_status`,
`istanbul_water_status`, `istanbul_transit_line`, `istanbul_transport_disruptions`
and `istanbul_market_schedule`.
Their `structuredContent` equals the backwards-compatible JSON text. Direct
Python calls still return dictionaries; domain records inside `data` remain open
objects. Expected `ok=false` envelopes are not MCP execution errors. When legacy
names are enabled, the two pharmacy aliases also publish this schema.

## Weekly market schedule

`istanbul_market_schedule(district?, day?, limit?)` returns the published İBB
weekly market snapshot. `day` accepts Turkish/English weekdays,
`bugün/yarın/today/tomorrow`, or an ISO date. `district`
is matched after Turkish-character normalization. Rows include district,
neighborhood, day, market type, source coordinate, `maps_url` and source ID.
Default limit is 50 (max 100). This is a weekly static schedule, not proof a
market is open today; holidays, relocations and closures may differ.

See [MCP interface and verification](mcp-interface.md) for protocol-era behavior,
source-health caveats, output schema cost and official sources.

## Catalog

- `istanbul_search_datasets(query, formats?, limit?)`
- `istanbul_get_dataset(dataset_id)`
- `istanbul_get_resource_schema(resource_id)`
- `istanbul_query_resource(resource_id, filters?, limit?)`

Search results expose `relevance`, `datastore_active_count`, and
`preferred_resources`. Record queries are CKAN `datastore_search` with guarded
scalar/scalar-list filters; this endpoint is **not SQL**. Metadata and record
calls use TTL caches and source rate limits.

An unknown dataset or resource ID returns a `not_found` error with
`field=dataset_id` or `field=resource_id` and `freshness=unknown`. This means the
identifier does not exist; it does **not** mean CKAN is unavailable. A reachable
CKAN failure still returns `source_unavailable` with `freshness=broken`.

### Guarded local SQL

`istanbul_datastore_query(resource_id,sql,limit?)` runs one SQLite SELECT over
`records` from one operator-allowlisted, complete bounded DataStore capture.
The default allowlist is empty. This is **not** the unavailable upstream
`datastore_search_sql` API. GROUP BY/aggregates are supported; joins, subqueries,
CTEs, windows, writes and arbitrary functions are not. Output limits are always
enforced (20/100). Incomplete/oversized captures never produce partial totals.
See [SQL setup, safety bounds and freshness](datastore-sql.md).

## Scheduled stop departures

`istanbul_next_departures(stop_id?,lat?,lon?,line?,at?,radius_m=500,limit?)`
uses the full official GTFS `stop_times.zip` with agency/stops/routes/trips/calendar
and optional calendar_dates. The preview CSV is never used. Enabled in production
after the 2026-10-25 live acceptance; the source default remains disabled.
A startup warm-up loads the timetable in the background. During warm-up the tool
returns `error_code=warming_up` with `retry_after_seconds=60` instead of blocking.
`stop_id` and coordinates are exclusive; coordinate mode selects at most five stops
in a bounded radius. `line` matches `route_short_name`; `at` is an ISO datetime
with an explicit UTC offset, or now in Europe/Istanbul. Results cover 24 hours,
ordered by scheduled departure. Extended `25:xx` times retain their original
service date. Calendar exceptions, untimed rows and no-pickup stops are respected.
No interpolation, live ETA, cancellation detection or route planning.
Invalid/outside-calendar/unavailable results do not establish no service.
Structured/text envelopes match.

See [GTFS schedule limits and acceptance](gtfs-schedule.md).

## Named-place and district summaries

`istanbul_mobility_nearby(place?,lat?,lon?,radius_m=1500,limit?,district?)`
and `istanbul_city_services_nearby(place?,lat?,lon?,radius_m=1500,limit?,district?)`
accept all 39 Istanbul districts (Turkish/ASCII names). Explicit `district` is
exclusive with `place` and coordinates. District-only `place` requests, including
`Pendik merkez`, use the same mode. They never invent a district centroid:

- Mobility returns district parking only; other mobility components are not checked.
- City services return district library/cultural-centre addresses; WiFi is not checked.
- District mode does not apply radius or show distances; the per-section limit applies.

Point mode supports the existing curated names plus Bostancı, Karaköy, Nişantaşı
and district-qualified Acıbadem. Bare Acıbadem returns `ambiguous_place`; specify
`Acıbadem, Kadıköy` or `Acıbadem, Üsküdar`. New points carry Wikidata CC0 source
revisions. These are area reference points, not full address geocoding, official
boundaries or exact user locations. Unrecognized addresses fail validation;
mentioning a district inside an address does not resolve it.

City-service source failures remain explicit: partial results have unknown
freshness; total failure returns `ok=false`, not a fresh empty result.
See [place resolution](place-resolution.md).

## Unified location search

`istanbul_nearby(lat?, lon?, types?, radius_m?, limit?, kind?, district?, bbox?)`

Choose one mode: both coordinates, a supported district search, or a
city-feature bounding box. Conflicting/unused arguments are rejected before
source access.

| kind | Scope | Default radius |
|---|---|---:|
| `city_feature` (default) | Parking, metro station, AQ station locations, public transport stops, WiFi, EV charging, taxi stands, weekly markets; filter with `types` | 1,000 m |
| `parking` | ISPark capacity/availability; coordinates **or district** | 1,000 m |
| `pharmacy` | Current on-duty İBB roster; coordinates **or district** | 1,000 m |
| `istanbulkart` | Official static filling-center locations | 2,000 m |
| `social_facility` | Official locations and verified detail/reservation links | 2,000 m |
| `metro_station` | Metro İstanbul station locations | 1,000 m |
| `air_quality` | Stations **and latest readings** | 5,000 m |
| `water_fault` | ISKI faults ordered by approximate geometry center | 1,000 m |

Global radius maximum: 5,000 m; default/max result limits: 20/100 (configurable).
An explicit `limit` must be a positive integer: `0` or a negative value is a
validation error, never treated as "not supplied". Omitting `limit` (or sending
`null`) selects the configured default. District lists never invent distances. `bbox` is
`[min_lon,min_lat,max_lon,max_lat]`, available only with `kind="city_feature"`.
`types` accepts `parking`, `metro_station`, `air_quality_station`,
`public_transport_stop`, `wifi`, `ev_charging`, `taxi_stand`, `market`; it does
not apply to dedicated kinds. EV/taxi/market rows are published static snapshots,
not live operating status; market rows also carry the weekly `day` property.
Cultural centres are address-only and are returned by
`istanbul_city_services_nearby` as `address_search` records, not radius points.
See [static city layers](city-static-layers.md) for source limits and provenance.

Coordinates produce `maps_url`. Address-only results may have
`maps_search_url` and `location_precision=address_search`, not a verified pin.

### GTFS stop locations

`types=["public_transport_stop"]` (nearby or bbox) and the mobility summary
use the official static `stops.csv`, even with DataStore inactive. Neither
`stop_times` descriptions nor ZIPs are used to discover stop coordinates.
The source-specific parser handles BOM/semicolon CSV and the observed grouped
coordinate format; it never guesses shifted fields or arbitrary integer scaling.

Default ingestion bounds are 5 MiB, 50,000 raw rows and a 20 s source-load
deadline; metadata is separately capped at 512 KiB. Failed/partial/empty/all-invalid
captures do not replace the prior geo layer. Successful responses retain
dataset/resource IDs, source time and received/accepted/skipped counts.
A valid snapshot with no nearby matches is checked-empty; an unavailable source
is not.

Fresh TTL is 24 h, with at most 7 additional days of stale-if-error. Stale
responses retain the successful snapshot time and warn explicitly; expired or
unverified persisted rows cannot appear as fresh success. GTFS-only failure
returns `ok=false`/`broken`; partial mobility remains `unknown` with unavailable
stop coverage. These are **static locations, not arrivals or operating status**.
See [GTFS bounds, provenance and verification](gtfs-stops.md).

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
  `measured_at` and `freshness.source_updated_at` use timezone-aware ISO 8601.
  Naive source timestamps are interpreted as `Europe/Istanbul`; existing offsets
  are preserved. Missing/invalid timestamps are null and produce a warning.
- `istanbul_mobility_nearby(place?,lat?,lon?,radius_m?,limit?)`: parking, metro,
  stops, station locations and traffic summary. Curated reference places such as
  Kadıköy Rıhtım/Taksim/Levent are accepted. District names yield district-wide
  parking without synthetic proximity.
- `istanbul_city_services_nearby(place?,lat?,lon?,radius_m?,limit?)`: WiFi plus
  district-level library and cultural-centre addresses/hours. Libraries without
  coordinates are marked as district-level and can have map-search links.
  Cultural-centre source counts distinguish usable snapshot records
  (`accepted_total`), invalid records (`skipped_total`), district matches before
  the result limit (`matched_total`), and returned records (`returned_total`).
  Records in other districts are not invalid. Zero district matches produce an
  explicit warning; absence in this dataset is not proof no centre exists.

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
Display names and `source_names` repair the known Turkish source-encoding variants
(`CAFERAÐA` → `CAFERAĞA`). `raw_source_names` retains the original source spellings
for provenance; numeric indicators and source record IDs are unchanged.

The building-stock and earthquake-scenario resources store district names in the
same legacy encoding (`ŞİŞLİ` → `ÞÝÞLÝ`) and Eyüpsultan under its former name `EYÜP`.
CKAN filters are exact, so every resource is queried with the correct spelling, the
legacy spelling and known former names. Neighborhood matching also ignores spaces and
a trailing `Mahallesi`/`Mah.` (`RUMELİHİSARI` = `RUMELİ HİSARI`). A source that returns
no rows for the district, or has no row for the selected neighborhood, adds an explicit
warning: `coverage:false` means "not matched", never "the source has no data".

## Transit

`istanbul_transit_line(line_code,action="info"|"stops"|"departures",limit?)`

- `info`: IETT line information.
- `stops`: ordered stops with directions/maps links.
- `departures`: planned **main-terminal** departures, not intermediate-stop ETA.
  Only this action accepts limit (20/100 by default).

An empty `info` result is a checked-empty answer with a “line code not found”
warning.

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
unavailable, not checked-empty. With configured `MARMARAY_API_BASIC_TOKEN`, Marmaray
can fall back to the existing official frontend API when its page is an Angular
shell, has unrecognized markup, returns HTTP 404/410/5xx, or has a transport
failure. HTTP 401/403/429 do not trigger this fallback. API failures still become
unavailable, not checked-empty; no token or new endpoint is inferred.

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
