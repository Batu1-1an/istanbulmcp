# GTFS planlı durak kalkışları — P0 uygulaması

Tarih: 2026-10-23; canlı kabul **2026-10-25**.

Durum: canlı kabul geçti; production'da açık ve açılışta arka plan ön ısıtma çalışır.
Kaynak varsayılanı `GTFS_SCHEDULE_ENABLED=false`; canlı deployment `true` kullanır.
`istanbul_next_departures` canlıda 17. tool'dur. İlk yükleme yaklaşık iki dakika
sürer; ısınma sırasında araç `warming_up` döndürür ve bloklamaz.

## Araştırma düzeltmesi: CSV tam tarife değil

[Resmî CKAN metadata](https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi)
Exa üzerinden tekrar okundu. `23778613-16fe-4d30-b8b8-8ca934ed2978` resource'undaki
`stop_times.csv` açıklaması açıkça **önizleme** olduğunu söylüyor. Yaklaşık 26 MB
CSV veya onun 1.048.575 satırlık DataStore tablosu tam tarife olarak kullanılamaz.

Tam `stop_times.zip` resource'u `80401c1c-c240-4a32-8f40-ef697100a681`; metadata
boyutu **22.753.052 byte**, kaynak güncellemesi **2026-03-17**. Resolver UUID'leri
sabitlemez; canonical dosya adını ve o metadata'daki resource kimliğini doğrular.
Bu ZIP'in açılmış boyutu, kayıt sayısı ve içerik biçimi **bu ortamdan canlı
indirilemedi** (`ConnectTimeout`). Önceki 2026-10-21/23 araştırmasındaki “34 MB
CSV seti yeterli” varsayımı bu bulguyla düzeltilmiştir.

## Sözleşme

```text
istanbul_next_departures(
  stop_query? | stop_id? | lat/lon?, line?, at?, radius_m=500, limit?
)
```

- `stop_id`, kaynak GTFS kimliğidir; İETT SOAP durak koduyla otomatik eşleştirilmez.
- `stop_id` ve koordinatlar birlikte verilmez. Koordinat modu yarıçap içindeki
  en yakın en fazla **5** durağı seçer. Yarıçap üst sınırı mevcut `MAX_RADIUS_M`
  (varsayılan 5000 m), sonuç sınırı `DEFAULT_LIMIT`/`MAX_LIMIT` (20/100).
- `line`, `route_short_name` ile tam, büyük/küçük harften bağımsız eşleşir.
- `at`, UTC offset'i bulunan ISO datetime'dır; verilmezse Europe/Istanbul'da şimdi.
- Sorgu sonraki **24 saat** içindir; sonuçlar planlı kalkışa göre sıralanır.
  Sonuç listesinin tamamı İstanbul'un tüm seferleri veya tüm yakın durakları değildir.
- `calendar` servis günü, isteğe bağlı `calendar_dates` ekleme/çıkarma istisnaları
  ve geceyarısı sonrası **25:xx / 48:xx** saatleri işlenir. Desteklenen üst GTFS
  saati **71:59:59**; önceki iki servis günü de kontrol edilir.
- Takvim geçerliliği dışı sorgu `ok=false`, `error_code=outside_calendar`,
  `field=at` döner; “sefer yok” denmez.
- `timepoint=0` yayımlanmış yaklaşık saattir; `scheduled_approximate` etiketi taşır.
  Eksik saat interpolasyonu yapılmaz. Saati olmayan ara durak kayıtları saklanır
  ama kalkış listesine alınmaz. `pickup_type=1` (biniş yok) elenir; 2/3 koşulları
  ham `pickup_type` ile korunur.
- Çıktıda `service_date`, offset'li `scheduled_departure`, özgün GTFS saati,
  trip/route/service kimlikleri, hat, yön/headsign ve varsa harita/mesafe bulunur.
- Her yanıt kaynak, tazelik, limit ve uyarı zarfındadır; tool açıkken canonical
  `ResponseEnvelope` output schema da yayınlanır. JSON text ve structured çıktı
  eşittir. **Canlı ETA, gecikme, iptal veya o gün işletilme garantisi değildir.**

Örnek (aracı açmadan önce canlı kabul gerekir):

```json
{"stop_id":"292235","at":"2026-10-23T09:00:00+03:00","limit":5}
```

Örnek tarih tarife geçerliliğine tabidir; bugünün tarifesi olduğu iddia edilmez.

### Durak adı arama — 0.2.3

```json
{"stop_query":"kadikoy","limit":10}
```

- Yeni araç yoktur; mevcut `istanbul_next_departures` şemasına isteğe bağlı
  `stop_query` eklendi. Önceki `stop_id` ve koordinat çağrıları değişmedi.
- Ad araması **durak adayı** döndürür, kalkış saati döndürmez. Kullanıcı ad ve
  haritadan seçim yaptıktan sonra dönen GTFS `stop_id` ile kalkış sorgulanır.
- Büyük/küçük harf, Türkçe/ASCII (`Kadıköy/kadikoy`, `Şişli/SISLI`), Unicode
  birleşik/ayrık harfler, noktalama ve boşluklar normalize edilir. Tüm sorgu
  kelimeleri ad içinde bulunmalıdır; kelime sırası önemli değildir.
- Sıralama: normalize tam ad, adın başlangıcı, diğer parça eşleşmeleri;
  eşitlikte normalize ad ve `stop_id`. Aynı adlı duraklar **birleştirilmez**.
- Eşleşme yoksa en az dört karakterli sorgularda en fazla beş benzer ada ait
  duraklar önerilebilir. Bunlar `match_kind=suggestion`, `matched_total=0`
  ve açık uyarı taşır. Kısa/ilgisiz sorgu için boş sonuç dönebilir. Benzerlik
  eşiği 0,72'dir; öneri, kullanıcının istediği durağın bulunduğu anlamına gelmez.
- Adaylarda `stop_id`, özgün `stop_name`, `lat`, `lon`, `maps_url`,
  `result_kind=stop_candidate` ve `match_kind=exact|prefix|contains|suggestion`
  bulunur. Eksik koordinat ve harita `null` kalır; konum üretilmez.
- Kaynakta ilçe/yön/platform metadata'sı yoktur; bunlar türetilmez. İlçe adı
  eklemek yalnız yayımlanmış durak adında o kelime varsa eşleşir. Adres çözümleme
  veya ilçeye göre coğrafi filtre değildir.
- `stop_query` yalnız `limit` ile kullanılır; `stop_id`, koordinatlar, `line`,
  `at` veya varsayılandan farklı `radius_m` ile karıştırılırsa kaynak okunmadan
  validation hatası döner. Ad 2–200 karakterdir; normalize hali en az iki harf
  veya rakam içermelidir. Varsayılan/üst sonuç sınırı 20/100'dür.
- Sonuç sınırı eşleşmeleri keserse toplam ve uyarı korunur. `pagination` yalnız
  ilk sayfanın sınırını/sayısını bildirir; bu modda offset parametresi yoktur.
  `suggested_total` yalnız seçilen en fazla beş benzer adın duraklarını sayar.
- Mevcut tam GTFS snapshot'ı kullanılır; yeni dış servis veya indirme yoktur.
  Ancak açılıştaki tam tarife ön ısıtması bitmeden bu mod da `warming_up` döner.
  Snapshot'ın kaynak/profil kontrolü, TTL ve sınırlı stale penceresi değişmez.
  Arama yalnız `stops` kaynağının güncelleme zamanını ve sayaçlarını bildirir.
- Takvim yalnız kalkış sorgusunda uygulanır. Ad araması, tarife takvimi sona
  ermiş olsa da statik aday döndürebilir; bu, bugün sefer olduğu anlamına gelmez.
- En fazla 100.000 yayımlanmış durak taranır. SQL metnine kullanıcı girdisi
  eklenmez. Ad normalizasyonu ve benzerlik hesabı dahil sorgu bütçesi bir saniyedir;
  bütçe aşılırsa kısmi/boş başarı değil unavailable döner. SQL aracı ve allowlist
  değişmedi.

Doğrulama: `tests/test_stop_search.py` sentetik GTFS fixture'larıyla Türkçe/ASCII,
aynı ad/yön belirsizliği, sıralama, kesilme, öneri/boş sonuç, eksik koordinat,
validation, timeout, stale/expiry, snapshot değişimi, seçilen kimlikle kalkış ve
iki MCP protokolündeki gerçek ASGI çağrısını kapsar.

Bu ekleme için [Python MCP SDK v2 tool input şeması](https://py.sdk.modelcontextprotocol.io/v2/servers/tools/)
Context7 üzerinden kontrol edildi: parametre türü input şemasını, varsayılan
`None` değeri isteğe bağlılığı, docstring araç açıklamasını belirler.

## Yükleme ve snapshot güvenliği

1. Sınırlı CKAN package metadata'sı okunur (512 KiB). `agency`, `calendar`,
   `routes`, `stops`, `trips` CSV/TXT ve **tam stop_times ZIP** zorunludur.
   `calendar_dates` varsa işlenir. CSV-only önizlemeye veya DataStore'a fallback yok.
2. Yalnız canonical HTTPS `data.ibb.gov.tr/dataset/.../resource/<id>/download/<table>`
   URL'leri kabul edilir. Redirect, farklı host, kullanıcı bilgisi, query/fragment,
   HTTP-compressed body, partial HTTP yanıt ve HTML reddedilir.
3. Dosyalar RAM'e tümüyle alınmadan yapılandırılmış DB'nin dizinindeki geçici
   dosyalara stream edilir. HTTP byte bütçesi dosyalar arasında toplamsaldır.
   Pozitif katalog boyutu ve Content-Length varsa tamamlık denetlenir.
4. ZIP diske extract edilmez; tam olarak tek `stop_times.csv` veya
   `stop_times.txt` üyesi kabul edilir. Nested/yabancı/çoklu üye reddedilir.
   Açılmış ZIP boyutu ve düz CSV boyutları için ayrı toplamsal bütçe vardır.
5. BOM, virgül/noktalı virgül, quoting ve kaynağın sondaki adsız kolonu işlenir.
   Satırlar 1000'lik sınırlı batch'lerle geçici SQLite'a yazılır; kaynak satırların
   tamamı Python listesine alınmaz. Batch aralarında cancellation/deadline işlenir.
6. Eksik şema, tutarsız trip/stop/route/service bağlantıları, boş tablolar veya
   hiç saati olmayan tarife başarısızdır. Kaynakta `route_id` boş olan kullanılabilir
   route satırları ve güvenle atlanabilen yinelenen `(trip_id, stop_sequence)`
   stop-time satırları sayılarak dışlanır; `sources[].received_total`, `accepted_total` ve
   `skipped_total` bu farkı gösterir. Boş route satırlarına hiçbir trip referans
   vermiyorsa devam edilir. Diğer duplicate kimlikler hata verir. Agency timezone
   yalnız Europe/Istanbul'dur; frequencies genişletmesi desteklenmez.
7. İndirme/parsing/ilişki doğrulaması bitmeden uygulama DB'sine dokunulmaz.
   Son adımda yalnız `gtfs_schedule_*` tabloları **tek transaction** ile değiştirilir;
   geo/RTree indeksinden bağımsızdır. SQLite hatasında eski snapshot geri alınır.
   Geçici dosyalar başarı/hata/cancel durumlarında temizlenir.

### Saat tutarlılığı — 0.2.2

- Aynı `(trip_id, stop_sequence)` için varış, kalkış, saat kesinliği, biniş
  koşulu veya saatli durak kimliği çelişirse **yeni snapshot reddedilir**.
  Kaynak satır sırasına göre bir saat seçilmez. Kontrol batch sınırları arasında
  da çalışır. Birebir aynı normalize kayıtlar sayılarak atlanabilir.
- Canlı kaynaktaki özel durum korunur: iki kayıtta da varış/kalkış tamamen boş,
  `timepoint=0` ve biniş koşulları aynıysa saatsiz tekrar sayılarak dışlanır.
  İlk satır tutulur; bundan bir kalkış saati üretilmez. Saatli/saatsiz karışık
  çakışmalar kabul edilmez.
- Her seferde bilinen saatler `stop_sequence` sırasıyla kontrol edilir.
  Sonraki varış, önceki bilinen kalkıştan erken olamaz. Varış veya kalkıştan
  yalnız biri varsa o saat kullanılır. Saatsiz ara duraklar önceki bilinen saati
  unutturmaz; eşit saatler ve `25:xx`/`49:xx` geçerlidir.
- Varış saniyeleri yalnız geçici doğrulama veritabanında tutulur. Yayımlanan
  veritabanının altı kolonlu departure şeması değişmez; migration gerekmez.
- Hatalı güncelleme önceki başarılı snapshot'ı değiştirmez. Eski veri yalnız
  mevcut stale penceresi içinde, `freshness=stale` uyarısıyla sunulabilir.

Kaynak kuralı: [GTFS Schedule Reference](https://gtfs.org/documentation/schedule/reference/).
SQLite trigger/UPSERT ve pencere fonksiyonları için güncel belgeler Context7
`/websites/sqlite_docs` üzerinden kontrol edildi.

Kaynak indirme/parsing için deadline vardır; son SQLite publish transaction'ı
senkrondur ve yarıda async-cancel edilmez. **Soğuk yükleme gecikmesi ve transaction
süresi tam ZIP ile ölçülmeden düşük gecikme garantisi verilmez.** Yükleme sırasında
staging dosyaları, eski/yeni SQLite sayfaları ve WAL birlikte diskte yer kaplayabilir;
yeterli volume alanı olmadan açmayın. Kaynak dosyalarının birden fazla HTTP istekte
birlikte değişmeyeceğine dair yayıncı versiyon manifesti yoktur; ilişki doğrulaması
tüm anlamsal sürüm tutarsızlıklarını kanıtlayamaz.

## Cache ve hata davranışı

- Aynı süreç/DB/limit profilindeki çağrılar tek başarılı yüklemeyi paylaşır.
  Cache'te satır koleksiyonu değil snapshot kimliği ve provenance tutulur.
- TTL, son başarılı yüklemenin yaşını ölçer; kaynak dosyasının güncel olduğu
  anlamına gelmez. Her dosyanın kaynak güncelleme zamanı ayrı `sources[]` kaydıdır.
- Refresh hatasında yalnız TTL + stale penceresindeki önceki snapshot sunulabilir;
  `freshness=stale`, `coverage_status=unavailable`, özgün alınma zamanı korunur.
  Hata stale süresini uzatmaz.
- Restart/cache kaybında DB'deki eski tablolar tek başına başarı yetkisi vermez.
  Başarılı cache provenance'ı yoksa yeniden kaynak yükleme gerekir.
- DB snapshot kimliği ve profil her okuma transaction'ında kontrol edilir. Başka
  worker/profil değiştirirse yanlış provenance ile sunmak yerine unavailable olur.
  Çoklu süreçte single-flight/dağıtık koordinasyon **sağlanmış değildir**.
- Sıcak SQLite sorgusunda 1 saniyelik progress guard vardır; kapsamlı rota motoru
  veya sınırsız tarama yoktur. İndirme/şema/hata ayrıntılarından gizli URL/path/SQL
  kullanıcı yanıtına kopyalanmaz.

## Açılış ön ısıtması

`GTFS_SCHEDULE_ENABLED=true` iken uygulama açılışında arka plan görevi tam tarifeyi
yükler. `/healthz` bu görevi beklemez. Isınma sırasında `istanbul_next_departures`
`ok=false`, `error_code=warming_up`, `retry_after_seconds=60` döndürür; çağrı
bloklanmaz. Isınma başarılıysa sonraki çağrılar sıcak snapshot'ı kullanır. Isınma
başarısız olursa araç istek üzerine yeniden yüklemeyi dener ve hatayı yapılandırılmış
zarf içinde bildirir. Bu davranış çoklu worker için dağıtık koordinasyon sağlamaz.

## Konfigürasyon

| Değişken | Varsayılan | Sert üst sınır |
|---|---:|---:|
| `GTFS_SCHEDULE_ENABLED` | false | production'da true; canlı kabul geçti |
| `GTFS_SCHEDULE_MAX_BYTES` | 64 MiB | 128 MiB; toplamsal HTTP dosyaları |
| `GTFS_SCHEDULE_MAX_UNCOMPRESSED_BYTES` | 512 MiB | 1 GiB; açılmış toplam |
| `GTFS_SCHEDULE_MAX_ROWS` | 8.000.000 | 10.000.000; tablolar toplamı |
| `GTFS_SCHEDULE_LOAD_TIMEOUT_SECONDS` | 180 | 300; sonlu ve pozitif |
| `GTFS_SCHEDULE_CACHE_TTL_SECONDS` | 86400 | 86400 |
| `GTFS_SCHEDULE_STALE_IF_ERROR_SECONDS` | 604800 | 604800; 0 ile kapatılır |

Ek tablo başına row cap: agency 100, calendar 1000, calendar_dates 10000,
routes 20000, stops 100000, trips 500000, stop_times 10000000.
Geçersiz ayarlar başlangıçta reddedilir. Ayarlar `.env.example` ve `/status`
`limits.gtfs_schedule` altında görülebilir. Bunlar üretim kapasite ölçümü değil,
başlangıç koruma bütçeleridir; tam ZIP beklenen boyutu aşarsa bütçeyi körlemesine
büyütmek yerine kaynak/ortam incelenmelidir.

## Doğrulama

Offline:

```bash
pytest tests/test_stop_search.py tests/test_gtfs_schedule.py tests/test_registry_metadata.py
pytest
python -m scripts.smoke_mcp
```

Synthetic fixture'lar: [tests/fixtures/gtfs_schedule](../tests/fixtures/gtfs_schedule/README.md).
Üç durak × üç hat, hafta içi/sonu/istisna, önceki servis günü, UTC dönüşümü,
0 limit, şema/ID/bütçe, URL/redirect/ZIP, stream cancel, rollback, stale son tarihi,
restart ve snapshot uyumu; iki MCP protokolünde gerçek ASGI çağrısı kapsanır.
Warm fixture p95 kontrolü **üretim benchmark'ı değildir**.

2026-10-25 canlı kabul (Railway production relay'i, geçici SQLite):

| Ölçüm | Sonuç |
|---|---:|
| İndirilen byte | 30.903.169 |
| Açılmış byte | 158.132.138 |
| SQLite dosyası | 417.157.120 byte |
| `stop_times` | 6.155.647 kabul; 45 duplicate dışlandı |
| `routes` | 9.274 kabul; 5 boş `route_id` dışlandı |
| `stops` / `trips` | 15.390 / 135.625 |
| Soğuk yükleme | 125,2 s |
| Sıcak p95 | **0,0098 s** |
| Doğrulanan kaynak satırı | 6 (3 hat) |

Boş `route_id` satırlarına hiçbir trip referans vermiyordu. 45 duplicate
`(trip_id, stop_sequence)` satırı untimed/çakışan ara duraktı; ilk satır korundu
ve kaynak sayacında `skipped_total` olarak görünür. Sıcak p95 hedefi (<300 ms)
geçti. Soğuk yükleme 125 s olduğu için açılışta arka plan ön ısıtma eklendi;
varsayılan yükleme sınırı 180 s'dir.

Yerel doğrulama: Python 3.12 ortamında **992 passed, 25 skipped**; skip'ler opt-in
canlı testlerdir. `git diff --check` temiz.

0.2.2 düzeltmesinin tam ZIP ile tekrar kabulü: aynı **6.155.647** stop-time ve
45 saatsiz tekrar; yeni çelişki ve kronoloji kontrolleri geçti. Soğuk yükleme
**159,1 s**, sıcak sorgu p95 **8,0 ms**, yayımlanan SQLite **451.862.528 byte**.
Üç hat için altı kaynak satırı tekrar sorgulandı. Kaynakta eksik saatler
tamamlanmadı; yaklaşık %95,6 saatsiz stop-time satırı sınırı devam ediyor.
Yerel tam paket: **1217 geçti, 25 atlandı**; 83 GTFS testi ve gerçek sunucu
süreciyle MCP smoke testi geçti. Yeni hata testleri düzeltmeden önce başarısız
oldu; düzeltmeden sonra geçti.

0.2.3 durak araması kabulü (2026-10-25): **15.390** yayımlanmış durak üzerinde
12 gerçek kaynak sorgusu geçti. Türkçe/ASCII çiftleri aynı kimlik listesini verdi:
Kadıköy 27, Üsküdar 29, Şişli 12, Beşiktaş 16, Eminönü 27 ad eşleşmesi.
Yazım önerisi ve ilgisiz ad da kontrol edildi. Ad araması p95 **185,4 ms**;
aynı koşumda altı yayımlanmış kalkış satırı doğrulandı, kalkış p95 **10,4 ms**.
Bu ad eşleşmeleri ilçe içindeki bütün durakların sayısı değildir. Yerel tam paket
**1256 geçti, 25 atlandı**; gerçek sunucu süreciyle MCP smoke testi de geçti.

Canlı kabul betiği (relay değişkenlerini Railway'den alır; production DB'sine
dokunmaz):

```bash
railway run --service istanbulmcp --environment production -- \
  python scripts/live_gtfs_schedule_acceptance.py
```

### Yayın kapısı (geçildi)

1. Tam ZIP bounded istemciyle indirildi; tek `stop_times.txt`, şema, satır ve
   trip kapsamı doğrulandı.
2. Soğuk yükleme, sıcak p95 ve DB boyutu ölçüldü. Peak RSS ve volume/WAL tepesi
   bu koşumda ayrıca ölçülmedi; 417 MB DB ve geçici staging için yeterli disk
   varsayıldı.
3. Üç hat ve altı yayımlanmış kalkış satırı resmî tarife ile karşılaştırıldı.
4. Production'da `GTFS_SCHEDULE_ENABLED=true` ve startup warm-up etkinleştirildi;
   yüzey 17 tool oldu.

Kalan sınır: canlı ETA, gecikme, iptal veya o gün işletilme garantisi yoktur.
Çoklu worker için dağıtık single-flight yoktur.

## Kontrol edilen belgeler

- [GTFS Schedule Reference](https://gtfs.org/documentation/schedule/reference/) —
  servis günü, HH>24, timepoint, pickup_type, calendar_dates; 2026-10-23'te okundu.
- [HTTPX async streaming](https://www.python-httpx.org/async/#streaming-responses) —
  Context7 `/encode/httpx`: aiter_bytes, close/cancel, redirect davranışı.
- [Python MCP SDK v2.3 tools](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/servers/tools.md) —
  Context7 `/modelcontextprotocol/python-sdk/v2.3.0`: title/annotation/input schema.
- [Resmî İETT GTFS dataset](https://data.ibb.gov.tr/dataset/iett-gtfs-verisi).
