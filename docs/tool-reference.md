# Istanbul MCP Tool Reference

All tools are read-only and return a standard envelope with `summary`, `data`, `freshness`, `sources`, `limits`, and `warnings`.

When local source back-pressure is active, affected tools return `ok=false` with `retry_after_seconds` in `data[0]`.
Expected validation and source failures return `ok=false` envelopes with `error_code`, field/source context, and actionable limits where available.

Repeated CKAN catalog/resource, IETT line/stop, air-quality and IEO pharmacy requests use local back-pressure or TTL caches to reduce pressure on source systems. `/status` exposes TTL settings and redacted cache metadata with source labels and short key hashes, not raw user query/filter values.

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
- `istanbul_nobetci_eczane_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_nobetci_eczane_by_district(district, limit?)`
- `istanbul_istanbulkart_centers_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_sosyal_tesis_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_metro_stations_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_air_quality_nearby(lat, lon, radius_m?, limit?)`
- `istanbul_traffic_status()`
- `istanbul_mobility_nearby(place?, lat?, lon?, radius_m?, limit?)`
- `istanbul_city_services_nearby(place?, lat?, lon?, radius_m?, limit?)`

Air quality results include `latest_reading_quality` because the upstream source can return station records with missing AQI values. Traffic status is citywide only and explicitly lists unsupported road-level or incident detail.

Coordinate-bearing location results include `maps_url`, a Google Maps search URL built from the source `lat`/`lon`. Address-only records can include `maps_search_url` and `location_precision=address_search`; this is a map search link, not a claimed exact coordinate.

`istanbul_parking_by_district` lists ISPark records by the source `district` field and does not calculate or return synthetic distances. It is the right tool for questions such as "Başakşehir'de hangi otoparklar var, doluluk oranı nedir?"

## On-duty Pharmacies

- `istanbul_nobetci_eczane_nearby(lat, lon, radius_m?, limit?)` returns İstanbul-only records from the official İEO marker roster, sorted by straight-line distance. The default radius is 1,000 meters, the maximum is 5,000 meters, and the default/max limits are 20/100.
- `istanbul_nobetci_eczane_by_district(district, limit?)` applies Turkish-character-tolerant exact district matching over the same complete roster. Unknown districts return an empty successful result.

Both tools share a 5-minute fresh cache and may serve the last successful roster for up to 30 minutes as `freshness.status=stale` after a source failure. Responses expose source totals, İstanbul accepted/skipped counts, freshness, limits and warnings. The roster is a current on-duty source list only; it is not a general pharmacy catalog, working-hours directory or guarantee of a duty end time. Missing `nobet_bitis` values remain null.

`istanbul_mobility_nearby` is for practical questions such as nearby parking, metro, public transport stops, air quality, and the citywide traffic index. It accepts explicit `lat`/`lon` or curated reference points such as `Kadıköy Rıhtım`, `Taksim`, or `Levent`. If a district name is supplied instead, it returns district-wide parking records without distances and asks for an exact place only when distance matters.

`istanbul_city_services_nearby` returns nearby WiFi points and district-level library address/hour records where available. Library records do not have coordinates, so those results are marked as district-level rather than radius-precise, but include `maps_search_url` when name/address data is available.

## İstanbulkart Dolum Merkezleri

`istanbul_istanbulkart_centers_nearby` resmi [İBB İstanbulkart Dolum Merkezi Bilgileri](https://data.ibb.gov.tr/en/dataset/istanbulkart-dolum-merkezi-bilgileri) paketinin en yeni etkin DataStore kaynağını seçer ve `radius_m` (varsayılan 2.000, üst sınır 5.000) içinde Haversine mesafesine göre sıralar. `limit` varsayılanı 20, üst sınırı 100'dür. Yanıt kayıtları `source_id`, kaynakta varsa `terminal_type` ve `district`, `latitude`, `longitude`, `source_inserted_at`, `distance_m` ve `maps_url` alanlarını içerir.

Bu kaynak yıllık/statik konum listesidir; anlık açık/kapalı durumu, bakiye yükleme başarısı, kart stoğu, kuyruk veya çalışma saati üretilmez. Cevap `sources[]` içinde dataset/resource kimliklerini, CKAN toplam ve kabul/atlanan kayıt sayılarını, kaynak yayınlanma zamanını ve önbellek yenileme zamanını taşır. Normal başarılı yenileme 24 saat önbelleklenir; kaynak hatasında son başarılı snapshot en fazla 7 gün `freshness.status=stale` olarak kullanılabilir. Bu pencere de aşılırsa `ok=false`, `freshness.status=broken` ve yapılandırılmış kaynak hatası döner. Geçersiz koordinat/yarıçap/limit girdileri kaynağa istek atmadan reddedilir.

## Sosyal Tesis Konumları

`istanbul_sosyal_tesis_nearby` resmi İBB sosyal tesis kataloğundaki konumları Haversine mesafesine göre listeler (varsayılan yarıçap 2.000 m, üst sınır 5.000 m; limit 20/100). Her kayıtta ad, koordinat, mesafe, `maps_url` ve kaynakta bulunuyorsa ayrı `source_id`, `detail_url`, `reservation_url`, ilçe ve adres alanları bulunur; eksik isteğe bağlı alanlar `null` kalır. Rezervasyon bağlantısı yalnızca güvenilir ad/adres eşleşmesiyle eklenir ve yazma/rezervasyon işlemi başlatılmaz.

Canlı katalog 24 saat önbelleklenir; hata durumunda son başarılı snapshot en fazla 7 gün `stale` olarak sunulabilir. Canlı kayıt eksikse resmi `sosyal-tesis-konumlari` XLSX kaynağı yalnızca eksik alanları dolduran fallback'tir; canlı kaynak tamamen yoksa cevap `fallback_only` uyarısı ve fallback metadata'sı taşır. Bu araç yalnızca konum rehberidir ve işletim durumu alanı üretmez.

## Neighborhood Profiles

- `istanbul_neighborhood_profile(district, neighborhood?, limit?)`

Returns a joined neighborhood profile from fixed IBB Open Data CKAN resources: 2023 social-assistance household counts, neighborhood building stock by age/floor band, and earthquake-scenario records. Pass `district` only to list covered neighborhoods; pass both `district` and `neighborhood` for one joined profile.

Neighborhood matching normalizes Turkish characters, source mojibake variants such as `CAFERAÐA`, and source abbreviations such as `19.May`. Earthquake scenario fields are returned as source scenario records only, not as real-time risk, incident, or guidance data.

## Transit

- `istanbul_transit_line_info(line_code)`
- `istanbul_stops_for_line(line_code)`
- `istanbul_transit_disruptions(line_code?, limit?)`
- `istanbul_transport_disruptions(mode?, operator?, line?, limit?)`
- `istanbul_ferry_schedules(route, limit?)`
- `istanbul_planned_departures(line_code, limit?)`

IETT SOAP services may be unavailable during nightly maintenance. Transit tools return structured warnings/errors rather than inventing missing data.

`istanbul_transit_disruptions` returns non-empty current IETT announcements, optionally filtered by an exact normalized `line_code`. `limit` defaults to 20 and is capped at 100. Empty announcement messages are omitted; an empty filtered result is still a successful envelope. Live IETT payloads may also provide a human-readable `route_label`; it is kept separate from the actual line code.

`istanbul_transport_disruptions` combines four official disruption scopes: IETT and Metro İstanbul live service statuses plus Metro official planned notices, Şehir Hatları cancellation/service-change announcements, and Marmaray official urgent notices. `mode` accepts `bus`, `metro`, `tram`, `funicular`, `cable_car`, `ferry`, or `suburban_rail`; `operator` accepts `iett`, `metro_istanbul`, `sehir_hatlari`, or `marmaray`. `line` is trimmed and matches either normalized `line_code` or `route_label` by exact case-insensitive equality, without moving a route label into the line-code field. The default limit is 20, the maximum is 100, and each source result is cached for 120 seconds. Source coverage is reported at the top level in `sources[]` using `coverage_status=checked|unavailable`; partial failures preserve successful data and report `freshness=unknown`. Şehir Hatları'nın güncel resmi sayfası bazen hat kodu içermeyen, yalnızca tarihli genel bir iptal duyurusu yayımlar; bu durumda tarih korunur ve hat alanları boş bırakılır. Relay ve doğrudan resmi erişim `403` verirse bu durum `unavailable` olarak görünür. Marmaray sayfası Angular kabuğu döndürürse yapılandırılmış `MARMARAY_API_BASIC_TOKEN` ile resmi frontend API fallback'i kullanılır; geçerli boş liste checked empty kabul edilir. Unsupported live operators (İDO, Turyol, Dentur, minibüs, and taksi-dolmuş) are listed in `limits[]`, not presented as checked sources. Metro equipment faults, ETA, route planning, and GTFS `stop_times` archiving are outside this tool.

`istanbul_ferry_schedules(route, limit?)` returns normal published Şehir Hatları timetable rows. `route` is required and is matched exactly after bounded Turkish-character/case normalization against the official `/tr/seferler` index; the user cannot supply a URL. The connector then requests only the selected canonical route detail and parses its HTML tables into `route_label`, `stop_name`, `direction`, `day_type`, `planned_departure_time`, and optional `stop_sequence`/`schedule_note`. The index and detail appear as `sources[]` with `coverage_kind=published_timetable`, and the response explicitly states that rows are static published plans—not live departures, delays, or ETA. The default limit is 50, the maximum is 100, and index/detail results are cached for 120 seconds. A route miss is a successful empty result without a detail request; unavailable or changed markup is a structured source error. The official [Şehir Hatları timetable index](https://sehirhatlari.istanbul/tr/seferler) and [route detail pages](https://sehirhatlari.istanbul/tr/seferler/ic-hatlar/istanbul-ici-hatlar/kadikoy-besiktas-165) are the only runtime sources.

`istanbul_planned_departures` requires a normalized `line_code` and uses the IETT planned-service schedule endpoint. `limit` defaults to 20 and is capped at 100. Results preserve direction, route, day type, and planned departure time, and include the explicit limits `main-terminal planned departures` and `not intermediate-stop ETA`. They are scheduled main-terminal departures, not live intermediate-stop arrival estimates.

`istanbul_metro_accessibility_status(line?, station?, equipment_type?, limit?)` returns official Metro İstanbul equipment/total counts and current equipment fault details. It reads two official sources independently:
1. The `GetFaultyEquipments` JSON service for category-based working/faulted equipment totals — an expected invalid value yields a non-destructive discrepancy warning, not fabricated records.
2. The official Metro İstanbul fault page (server-rendered HTML) for line, station, equipment location, reason, and raw planned-return text.

Each source is cached independently for 120 seconds, with a total stale cap of 900 seconds from the first successful observation. The tool returns a single composite record with `equipment_summary` + `faults`; filters apply only to `faults` and `limit` (default 50, max 100) truncates only the detail list. `line` is an exact normalized line code, `station` and `equipment_type` are bounded (100 chars) Turkish/case/whitespace-tolerant exact matches; a URL is rejected before any source call. Optional fault fields like `expected_return` are nullable and never guessed; `İnceleniyor` is preserved verbatim as an open-ended string. Exact duplicates are dropped, while the same physical fault under a different line context is kept. The response always includes `source`, `observed_at`, `fresh/stale/partial/broken` freshness, applied filter/limit, and explicit limits stating this is **not** an end-to-end accessibility guarantee, and does not infer an alternative route, backup equipment, or a repair date. A checked-empty source is a successful result; one unavailable source yields `ok=true` with `freshness=unknown` and a `partial_source` warning; two unavailable sources yield `ok=false`/`broken`.
