# GTFS planlı durak kalkışları — P0 uygulaması

Tarih: 2026-10-23. Durum: **offline uygulandı, canlı kabul bekliyor**.
Varsayılan `GTFS_SCHEDULE_ENABLED=false`; mevcut 16 araçlık yüzey korunur.
Açılırsa `istanbul_next_departures` 17. tool olur. Railway deploy veya registry
publish bu çalışmada yapılmadı.

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
  stop_id? | lat/lon?, line?, at?, radius_m=500, limit?
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
- Takvim geçerliliği dışı sorgu `ok=false`, unavailable döner; “sefer yok” denmez.
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
6. Duplicate kimlikler, eksik şema, tutarsız trip/stop/route/service bağlantıları,
   boş tablolar veya hiç saati olmayan tarife başarısızdır. Agency timezone yalnız
   Europe/Istanbul'dur; frequencies genişletmesi desteklenmez.
7. İndirme/parsing/ilişki doğrulaması bitmeden uygulama DB'sine dokunulmaz.
   Son adımda yalnız `gtfs_schedule_*` tabloları **tek transaction** ile değiştirilir;
   geo/RTree indeksinden bağımsızdır. SQLite hatasında eski snapshot geri alınır.
   Geçici dosyalar başarı/hata/cancel durumlarında temizlenir.

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

## Konfigürasyon

| Değişken | Varsayılan | Sert üst sınır |
|---|---:|---:|
| `GTFS_SCHEDULE_ENABLED` | false | canlı kabul öncesi açmayın |
| `GTFS_SCHEDULE_MAX_BYTES` | 64 MiB | 128 MiB; toplamsal HTTP dosyaları |
| `GTFS_SCHEDULE_MAX_UNCOMPRESSED_BYTES` | 512 MiB | 1 GiB; açılmış toplam |
| `GTFS_SCHEDULE_MAX_ROWS` | 8.000.000 | 10.000.000; tablolar toplamı |
| `GTFS_SCHEDULE_LOAD_TIMEOUT_SECONDS` | 120 | 300; sonlu ve pozitif |
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
pytest tests/test_gtfs_schedule.py tests/test_registry_metadata.py
pytest
python -m scripts.smoke_mcp
```

Synthetic fixture'lar: [tests/fixtures/gtfs_schedule](../tests/fixtures/gtfs_schedule/README.md).
Üç durak × üç hat, hafta içi/sonu/istisna, önceki servis günü, UTC dönüşümü,
0 limit, şema/ID/bütçe, URL/redirect/ZIP, stream cancel, rollback, stale son tarihi,
restart ve snapshot uyumu; iki MCP protokolünde gerçek ASGI çağrısı kapsanır.
Warm fixture p95 kontrolü **üretim benchmark'ı değildir**.

2026-10-23 son yerel doğrulama: Python 3.12 ortamında **902 passed, 25 skipped**
(69,51 saniye); skip'ler opt-in canlı testlerdir. Gerçek `python -m app.main`
subprocess smoke'u **13 kontrolü** geçti; dış veri API çağrısı yapmadı.
`pip check`, Python compile kontrolü, yerel doküman linkleri ve `git diff --check`
başarılı. Tam ZIP canlı testi, container build ve Railway deploy bu koşumun
parçası değildir.

Opt-in canlı test (tam ZIP indirir; production DB/endpoint/deploy kullanmaz):

```bash
RUN_LIVE_GTFS_SCHEDULE_TESTS=1 pytest -s tests/live/test_gtfs_schedule_source_live.py
```

Bu test tam ZIP → geçici SQLite → dokuz kaynak satırı / üç hat → sıcak sorgu
p95 zincirini sınar. Tarihleri yayımlanmış takvimden seçer; bugünün servis
geçerliliğini kanıtlamaz. Açılmış/indirilen byte, tablo sayıları, DB boyutu ve
süreleri raporlar. Bu ortamda kaynak timeout verdiği için **çalıştırılmadı**.
Peak RSS, volume/WAL tepe kullanımı ve deploy gözlemleri ayrıca gerekir.

### Yayın kapısı (henüz geçilmedi)

1. Erişebilen bir ortamdan tam ZIP'i bounded istemciyle indirin. ZIP üye adını,
   şemayı, açılmış byte/satır sayılarını ve trip kapsamını doğrulayın.
2. Soğuk yükleme süresi, peak RSS, disk/WAL kullanımı ve event-loop etkisini ölçün;
   en az üç gerçek durak/hat kombinasyonunu resmî tarife satırlarıyla karşılaştırın.
3. Gerçek indeks üzerinde sıcak sorgu p95 <300 ms hedefini test edin. Boş, takvim
   dışı, geçici kesinti ve stale süre sonunu ayrıca kontrol edin.
4. Deploy kaynağına erişim, tek/çoklu worker ayarı ve volume bütçesini kontrol
   edin. Ondan sonra `GTFS_SCHEDULE_ENABLED=true` ile 16-tool yüzeyini açın.

Bu belge canlı ZIP kabulünü veya Railway'de çalışmayı doğrulamış sayılmaz.

## Kontrol edilen belgeler

- [GTFS Schedule Reference](https://gtfs.org/documentation/schedule/reference/) —
  servis günü, HH>24, timepoint, pickup_type, calendar_dates; 2026-10-23'te okundu.
- [HTTPX async streaming](https://www.python-httpx.org/async/#streaming-responses) —
  Context7 `/encode/httpx`: aiter_bytes, close/cancel, redirect davranışı.
- [Python MCP SDK v2.3 tools](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/servers/tools.md) —
  Context7 `/modelcontextprotocol/python-sdk/v2.3.0`: title/annotation/input schema.
- [Resmî İETT GTFS dataset](https://data.ibb.gov.tr/dataset/iett-gtfs-verisi).
