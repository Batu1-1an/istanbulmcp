# Changelog

0.2.4 ve önceki kayıtlar Git geçmişinden geriye dönük hazırlanmıştır. Tarihler, sürüm numarasının
depoda değiştiği tarihlerdir; GitHub Release veya Registry yayını yapıldığını
göstermez. Registry yayın bilgisi için [yayın rehberine](docs/registry.md) bakın.

## [Unreleased]

### Changed
- `sources[].url` yalnız kullanıcının açabileceği web sayfalarını taşır. API uçları
  (`api.ibb.gov.tr` vb.), proxy adresleri ve ham veri dosyaları (JSON, CSV, ZIP, XLSX)
  `null` döner; yayıncı, dataset/resource ID ve tazelik bilgisi korunur.
- Sunucu talimatı, cevapta kaynağı yayıncı adıyla belirtmeyi ve yalnız dolu
  `sources[].url` alanını link olarak vermeyi ister.
- `istanbul_nearby(kind=social_facility)` kaynak farkı uyarılarını yalnız yanıtta dönen
  tesisler için verir; önceden tüm katalog için basılıyordu. Canlı katalog ile Açık Veri
  koordinat farkı 50 m altındaysa uyarı sayılmaz (önceden ~1 m; eşleşen 16 tesisin 15'i
  3–22 m farkla uyarı üretiyordu). Uyarı tesis başına tektir ve farkı metre olarak verir.
- `istanbul_next_departures` üst düzey `freshness.source_updated_at` alanında yalnız
  işletmeci bilgisi taşıyan `agency.txt` tarihini hesaba katmaz; tarife dosyalarının en
  eskisini verir (2024 yerine 2026-03-17). Dosya bazlı tarihler `sources[]` içinde kalır.

### Security
- İSKİ relay adresi artık tool sonucunda kaynak URL'i olarak görünmez.

### Fixed
- `istanbul_nearby(kind=air_quality)` her istasyon için `AQI`/`Concentration` değerini
  `null` döndürüyordu. `GetAQIByStationId` tarih aralığı olmadan çağrılınca kaynak saatlik
  dilimleri istek anından (ör. `21:47:47.89`) üretiyor; ölçümler `HH:00:00`'da tutulduğu
  için hiçbir dilim eşleşmiyordu. İstek artık İstanbul saatine hizalı son 24 saatlik
  `StartDate`/`EndDate` gönderir; canlı kontrolde 28 istasyonun 27'si değer döndürdü.
  `latest_reading_quality.has_reading` artık yalnız AQI veya konsantrasyon değeri varsa
  `true` olur; tamamen boş satır ölçüm sayılmaz.
- Kaynak önbelleği, TTL'i dolan her girdiyi başka bir kaynak yazıldığı anda siliyordu;
  `*_STALE_IF_ERROR_SECONDS` pencereleri bu yüzden production'da pratikte çalışmıyordu.
  Girdi artık stale penceresi bitene kadar tutulur; kaynak hata verirse son başarılı
  veri `freshness=stale` ile sunulur.
- GTFS tarifesi TTL'i (24 saat) dolunca önbellekten düşüyordu: `istanbul_gtfs_snapshot_status`
  "snapshot yok" diyor, günün ilk `istanbul_next_departures` çağrısı 1,5–2,5 dakikalık
  soğuk yüklemeyi bekliyordu. Tarife artık TTL dolmadan arka planda yenilenir; yenileme
  sırasında çağrılar mevcut snapshot'ı kullanır.
- `istanbul_neighborhood_profile`, adında Ş/İ/Ğ geçen 19 ilçe ve Eyüpsultan için bina
  stoku ve deprem senaryosunu hiç bulamıyordu (ör. Şişli/Gülbahar). Bu iki kaynak ilçe
  adını eski kodlamayla (`ÞÝÞLÝ`), Eyüpsultan'ı eski adıyla (`EYÜP`) tutuyor. CKAN
  sorgusu artık doğru yazımı, eski yazımı ve eski adı birlikte ister. Üç kaynağı birden
  eşleşen mahalle sayısı 448'den 912'ye çıktı.
- Mahalle eşleştirmesi boşluk farkını (`RUMELİHİSARI` / `RUMELİ HİSARI`) ve
  `Mahallesi`/`Mah.` ekini tolere eder; ad içermeyen `0.0` satırı listelenmez.
- Kaynak ilçe için hiç satır döndürmezse veya seçilen mahalle bir kaynakta
  eşleşmezse cevap açık uyarı taşır; `coverage:false` "veri yok" diye sunulmaz.

### Tests
- Testlerdeki sahte CKAN, filtreleri gerçek CKAN gibi birebir uygular. Gülbahar
  (deprem kaydı 846) ve 39 ilçenin her biri için canlı regresyon testleri eklendi.
- Canlı `istanbul_transport_disruptions` hat testi yanlış parametre adı (`line_code`)
  yerine aracın gerçek parametresi `line` ile çağrılır.

## [0.8.1] - 2026-11-09

- Verify a bounded set of named Biletinial search matches on demand, so a cold
  catalogue does not bypass published admission restrictions until background
  detail enrichment. The existing three-series/12-second limits remain.
- Add a cold-catalogue regression test; retain explicit partial coverage warnings.

## [0.8.0] - 2026-11-09

### Fixed
- Published admission ranges and last-entry clocks are flexible-entry metadata,
  never scheduled starts. Preserve admission_window opening/last-entry/closing
  observations without inventing a visit time or duration.
- Explicit general source weekday exclusions populate excluded_weekdays.
  Restricted dates are excluded from discovery, timed/flexible plans and
  calendars; detail retains entry_date_restricted for inspection.
- Multi-stop options cannot combine mutually exclusive published age ranges.
  checks exposes the common published range and unknown/partial evidence;
  age_incompatible_combinations counts rejected candidate combinations.

### Tests
- Admission ranges, weekday deny rules, restricted-date inspection/selection,
  incompatible ages, unknown ages and open-ended age ranges use bounded fixtures.

## [0.7.0] - 2026-11-08

### Fixed
- Withhold unmatched JSON-LD times when the same venue/date has visible HTML
  sessions. The HTML date can use an explicit source year even when JSON's clock
  differs; unconfirmed_json_sessions and partial-coverage warnings explain gaps.
- Parse explicitly flexible-entry tickets without inventing a visit start.
  Cards expose timing_kind, event_date and source_start_at; start_at is null for
  flexible entries. Clock filters exclude them with excluded_unverified_time.
- Keep flexible tickets in bounded plan flexible_entries with rejection/repair
  guidance; never place source date timestamps in timed plans or calendars.
- Prevent catalogue-only Biletinial timestamps from being scheduled before
  detail verification establishes a fixed session or flexible entry.
- Live QA consumers handle nullable visit starts and preserve timing semantics.

### Tests
- Source fixtures reproduce unconfirmed extra times and date-only admission;
  date/clock search, midnight deduplication, selection and calendar guards tested.

## [0.6.1] - 2026-11-08

### Fixed
- A conflicting Biletinial JSON-LD timezone offset no longer produces an extra
  next-day session alongside the explicitly published HTML session. Exact UTC
  instants that match an HTML session and JSON-only sessions retain normal
  timezone conversion. Conflicting JSON end times are not reused.
- Event cards expose start_time_basis, source_time_conflict and per-event
  warnings; search and plan options disclose source-time conflicts and
  conditional ticket prices instead of implying general per-person prices.
- Custom ChatGPT connection guidance consistently uses Refresh and a new chat,
  without treating it as a published-plugin review flow.

### Tests
- Source-time fixtures cover the duplicate, missing catalogue dates, genuine
  midnight UTC sessions, same-venue alternatives, venue/year ambiguity, calendar
  time, and rejection of a retired phantom performance ID after detail refresh.

## [0.6.0] - 2026-11-08

### Added
- include_past search control for retained active sessions; default searches
  consistently exclude already-started sessions, including explicit past ranges.
- result_info.filter_counts explains time, availability and price exclusions,
  expired price evidence, bounded detail checks, matched and returned counts.
- Event detail distinguishes retained retired sessions (catalogue_retired),
  unusable source snapshots (source_unavailable) and unknown local ID history.

### Fixed
- Free searches explicitly disclose partial/expired price coverage and excluded
  started sessions. The price predicate still runs before the public result limit.

## [0.5.3] - 2026-11-08

### Fixed
- An available offer no longer inherits the ticket type/eligibility label of a
  sold-out offer with the same price.

### Tests
- Combined-filter oracles, bounded radius/limit relations, concurrent refresh
  deduplication, budget/window checks and source-timezone boundaries.

## [0.5.2] - 2026-11-08

### Fixed
- The source genre Müzikli Oyun also maps to theatre rather than concert;
  explicit child/family labels keep their precedence.

## [0.5.1] - 2026-11-08

### Fixed
- Published Musical/Müzikal genres map to theatre (or explicitly labelled family
  content), rather than matching the music/muzik substring as concerts.
- Reusing a persisted event snapshot retains only its remaining catalogue TTL;
  a cold/evicted process cache no longer postpones refresh by another full TTL.

## [0.5.0] - 2026-11-08

### Fixed
- Biletinial dedicated genres are mapped beyond family/stand-up. Explicit type
  words in otherwise generic event titles carry category_source=title_marker;
  absent category observations no longer imply complete category coverage.
- Event searches use whole normalized words by default; match_mode=prefix opts
  into stems. Empty optional query text now behaves like an omitted filter.
- Failed source refreshes preserve usable snapshots and mark them stale, including
  failures within TTL. Sources expose refresh_status and serving_stale.
- Selected sessions outside a plan's date/time window get explicit repair guidance.
- Trimming a selected performance ID no longer expands it into all series sessions.
- Plan alternatives reduce repeated event sets and prefer known observed totals;
  total_observed_minimum_try is null when the existing subtotal is incomplete.

### Added
- Persistent 100-scenario UAT fixture/runner with relative dates, recorded runtime
  version, expected error codes, corrected title tokenization and actual plan counts.
- Regression coverage and a finding-by-finding review of the 2026-11-08 QA report.

## [0.4.1] - 2026-11-08

### Fixed
- Event search, detail and planning guidance now asks clients to show a clickable
  event/ticket-page link beside every presented event title, using the existing
  ticket_url or ticket_links[].url. Missing links stay explicit; calendar links
  do not replace event links. Source citation guidance no longer obscures these links.

## [0.4.0] - 2026-11-07

### Fixed
- Daily plans restrict interests before sampling and preserve selected performance
  identities instead of substituting another session from the same series.
- Planning samples the bounded day index across hours and series, avoiding the
  first search page bias. Diverse requested categories receive an explicit score.
- Background detail work prioritizes upcoming sessions and records retry times;
  failing/past series no longer repeatedly consume the detail batch.
- Event schema initialization is serialized once per SQLite file, reducing
  concurrent first-load DDL contention. Storage schema version is now 3.

### Added
- Source-published child genre, age ranges and durations; child_age filtering and
  require_known_end planning for explicit finish deadlines.
- Bounded relevant detail refresh for budget/free/family searches, strict known-price
  filtering, ticket type context, Turkish category aliases and title-scoped search.
- Repeatable persona UAT questions, semantic checks and new user-intent regressions.
- Event workflow prompt guidance for child ages, firm finish deadlines and exact
  session selection; privacy documentation describes request-only age filtering.

### Changed
- Explicit sold-out sessions are excluded from event search by default;
  include_sold_out opts in. Nearby cards identify distances as straight-line.

## [0.3.1] - 2026-11-07

### Fixed
- Event HTTP requests share a per-host one-request-per-second limiter across
  catalogue warm-up and concurrent detail requests. HTTP 429 applies a bounded
  Retry-After cooldown without repeated upstream requests.

## [0.3.0] - 2026-11-07

### Added
- Optional event search, event detail and daily planning MCP tools with source
  observations, explicit unknown prices/availability, bounded calendar exports.
- Official Ticketmaster TR feed and opt-in Biletinial list/detail connectors.
- Transactional SQLite event snapshots, normalized Turkish FTS5 and RTree.
- Event fixtures, protocol/behavior tests and [event guide](docs/events.md).

### Changed
- SQLite foreign key enforcement now applies on every application connection.
- New published names remain callable when the event feature is disabled.

## [0.2.6] - 2026-10-25

### Added
- Araç bazında çağrı, devam eden işlem, süre (toplam/ortalama/en uzun), yavaş çağrı,
  hata türü, stale/kısmi cevap ve ortak önbellek olay sayaçları.
- `istanbul_mcp.tools` JSON günlüğü ve mevcut `/status` içinde `tool_metrics`.
  Argüman, koordinat, sorgu, anahtar, yanıt metni ve exception mesajı kaydedilmez.
- Sabitlenmiş resmî `@modelcontextprotocol/conformance@0.1.16` paketiyle gerçek
  yerel sunucuya karşı beş uygulanabilir senaryo; CI'da zorunlu ayrı job.
  Rapor ve günlükler başarısızlıkta da 14 gün saklanır.

### Notes
- Sayaçlar süreç içidir, yeniden başlatmada sıfırlanır. Önbellek gözlemi yalnız
  ortak `SourceTTLCache` içindir. p95 veya upstream/CDN cache ölçümü değildir.
- Resmî profil yalnız seçilen 2025 dönemi senaryolarını kapsar; tam paket,
  sertifika veya 2026 protokol doğrulaması değildir. Üretime test aracı eklenmedi.
- MCP araç isimleri, SQL aracı ve allowlist değiştirilmedi.

## [0.2.5] - 2026-10-25

### Added
- `MCP_CORS_ALLOWED_ORIGINS` ile yalnız belirlenen sitelerden tarayıcı bağlantısı.
  Boş liste hiçbir browser origin'ine izin vermez; wildcard ve `null` kabul edilmez.
- MCP uçlarında yerel OPTIONS/preflight yanıtı; MCP ve Authorization başlıkları,
  JavaScript'ten okunabilen oturum, tekrar deneme ve kota başlıkları.
- İzinli origin'ler için 401/413/429/500 yanıtlarında da CORS başlıkları.
- İzin verilmeyen veya yinelenen Origin başlıklarının MCP çalışmadan reddedilmesi.

### Notes
- Preflight API anahtarı veya kota tüketmez; gerçek isteklerde mevcut anahtar,
  gövde, hız, eşzamanlılık ve kota kontrolleri korunur. Cookie credentials açılmaz.
- Origin göndermeyen mevcut istemciler değişmez. Yeni araç veya SQL değişikliği yoktur.

### Tests
- GTFS stale testlerinde süre, makinenin çalışma süresinden bağımsız olacak şekilde
  güncel monoton saate göre ayarlanır. Üretim önbellek süreleri değiştirilmedi.
- Gerçek süreç smoke testinin açılış bütçesi paylaşılan CI makineleri için 45 saniye;
  başarısız açılışta sunucu günlüğü hata çıktısına eklenir.

## [0.2.4] - 2026-10-25

### Publication
- Sürüm değişikliklerini kaydeden bu CHANGELOG.
- Resmî MCP Registry'de 0.2.4 için ilk remote-only kayıt ve yayın/doğrulama adımları
  (2026-10-25). Bu kayıt yeni bir uygulama sürümü veya directory kabulü değildir.
- Kod lisansı henüz seçilmedi. LICENSE dosyası eklenmedi. Veri kaynaklarının
  kullanım koşulları ve lisansları ayrı değerlendirilir.

### Added
- Her GTFS ve planlı terminal kalkışında `realtime:false`,
  `schedule_relationship:STATIC` ve veri kaynağı alanı.
- GTFS durak adayları ve kalkışlarında `stop_code`, `stop_desc`,
  `platform_direction_text` ve `location_type`.
- İndirme başlatmadan yerel tarife yaşı, takvim, kayıt ve atlama sayılarını
  gösteren `istanbul_gtfs_snapshot_status` aracı.
- Ortak `error` sözleşmesi: hata kodu, geçicilik, tekrar deneme gecikmesi ve
  uygun olduğunda bir sonraki araç çağrısı.
- Ortak `result_info` sözleşmesi: döndürülen/eşleşen kayıt sayısı, kesilme,
  sayım kapsamı ve devam önerisi. Bilinmeyen tamamlık açıkça belirtilir.

### Fixed
- İsteğe bağlı bozuk `location_type` alanları tüm tarifeyi reddetmez;
  `null`, sayaç ve uyarıyla bildirilir.
- Eski durak şeması, yeni snapshot ile aynı transaction içinde yükseltilir;
  başarısız yayın eski şema ve satırları korur.
- GTFS araçları kapatıldığında listeden gizlenir, eski istemciler için
  çağrılabilir kalır.

### Notes
- SQL aracı, sorgu motoru ve allowlist değiştirilmedi.
- Canlı ETA, gecikme veya o gün sefer işletildiği garantisi eklenmedi.

## [0.2.3] - 2026-10-25

### Added
- `istanbul_next_departures` üzerinde isteğe bağlı `stop_query` ile Türkçe/ASCII
  durak adı araması, sıralı adaylar ve açıkça etiketlenmiş yazım önerileri.
- Aynı adlı durakların ayrı tutulması; toplam, kesilme ve arama bütçesi bilgisi.

### Notes
- Ad araması kalkış döndürmez; yalnız `limit` ile kullanılır. Durak, ilçe veya
  yön otomatik seçilmez. Yeni bir araç adı eklenmedi.

## [0.2.2] - 2026-10-25

### Fixed
- Çelişen `(trip_id, stop_sequence)` kayıtları, batch sınırları arasında da
  yakalanarak yeni GTFS snapshot'ının yayınlanması engellenir.
- Sefer saatlerinin durak sırasına göre geriye gitmesi reddedilir.
  Saatsiz ara duraklar, geceyarısı sonrası saatler ve önceki snapshot korunur.

## [0.2.1] - 2026-10-25

### Added
- 39 ilçede koordinat veya mesafe uydurmadan ilçe geneli hizmet özetleri.
- Kaynak ve lisans bilgili statik yer referansları; belirsiz Acıbadem için
  Kadıköy/Üsküdar ayrımı.

### Notes
- İlçe hareketlilik özeti otoparkla; ilçe şehir-hizmeti özeti kütüphane/kültür
  adresleriyle sınırlıdır. Tam adres çözümleme değildir.

## [0.2.0] - 2026-10-24

### Changed
- Yayımlanmış araç adları, kompakt listede görünmeseler de gizli alias olarak
  çağrılabilir tutuldu.

### Included from earlier 0.1.0 development
- Python MCP SDK 2.3'e geçiş; eski ve yeni MCP protokolleri, yerel keşif
  kaynakları, prompt'lar ve yapılandırılmış yanıt şemaları.
- Kompakt salt okunur araç yüzeyi, isteğe bağlı erişim/kota kontrolleri ve
  sınırlı DataStore sorguları.

### Added while the version remained 0.2.0
- Tam GTFS ZIP üzerinden planlı kalkışlar, açılış ön ısıtması ve açık
  `warming_up` / `outside_calendar` yanıtları (2026-10-25).
- Kaynak bütünlüğü, tazelik ve kaynak hatalarını boş sonuçtan ayıran düzeltmeler.

## [0.1.0] - 2026-06-12

### Added
- Python MCP sunucusu, temel şehir-verisi konektörleri, SQLite depolama ve test
  altyapısıyla projenin ilk temeli.

[Unreleased]: https://github.com/Batu1-1an/istanbulmcp/commits/main
[0.2.6]: https://github.com/Batu1-1an/istanbulmcp/compare/59e2118...main
[0.2.5]: https://github.com/Batu1-1an/istanbulmcp/compare/9010d75...main
[0.2.4]: https://github.com/Batu1-1an/istanbulmcp/commit/1736725
[0.2.3]: https://github.com/Batu1-1an/istanbulmcp/commit/ccc3864
[0.2.2]: https://github.com/Batu1-1an/istanbulmcp/commit/e76a46f
[0.2.1]: https://github.com/Batu1-1an/istanbulmcp/commit/952fa5e
[0.2.0]: https://github.com/Batu1-1an/istanbulmcp/commit/0e7ff31
[0.1.0]: https://github.com/Batu1-1an/istanbulmcp/commit/553a065
