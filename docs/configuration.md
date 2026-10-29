# Konfigürasyon

Tüm değişkenler ve örnek değerler [.env.example](../.env.example) dosyasındadır. Bu sayfa önemli değişkenleri gruplar.

## Önbellek ve kaynak değişkenleri

- `CKAN_CATALOG_CACHE_TTL_SECONDS`
- `CKAN_RESOURCE_CACHE_TTL_SECONDS`
- `IETT_LINE_CACHE_TTL_SECONDS`
- `IETT_STOPS_CACHE_TTL_SECONDS`
- `GTFS_STOPS_MAX_BYTES` (5 MiB), `GTFS_STOPS_MAX_ROWS` (50.000), `GTFS_STOPS_LOAD_TIMEOUT_SECONDS` (20)
- `GTFS_STOPS_CACHE_TTL_SECONDS` (86.400) ve `GTFS_STOPS_STALE_IF_ERROR_SECONDS` (604.800; 0 kapatır) — [sınırlar ve tazelik](gtfs-stops.md)
- `GTFS_SCHEDULE_ENABLED` ve diğer `GTFS_SCHEDULE_*` ayarları — [GTFS planlı kalkışlar](gtfs-schedule.md)
- `SOURCE_CACHE_MAX_ENTRIES`
- `AIR_QUALITY_RATE_CAPACITY`
- `AIR_QUALITY_RATE_REFILL_PER_SECOND`
- `AIR_QUALITY_RATE_MAX_WAIT_SECONDS`
- `ISKI_FAULTS_CACHE_TTL_SECONDS`
- `ISKI_DAMS_CACHE_TTL_SECONDS`
- `ISKI_FAULTS_STALE_IF_ERROR_SECONDS`
- `ISKI_DAMS_STALE_IF_ERROR_SECONDS`
- `IBB_PHARMACY_BASE_URL` (canonical varsayılan: `https://cbsproxy.ibb.gov.tr/?eczanews`)
- `IBB_PHARMACY_REQUEST_TIMEOUT_SECONDS`, `IBB_PHARMACY_REQUEST_ATTEMPTS`
- `IBB_PHARMACY_CACHE_TTL_SECONDS` (300) ve `IBB_PHARMACY_MAX_CACHE_AGE_SECONDS` (1800)
- `IBB_PHARMACY_STALE_IF_ERROR_SECONDS` ve `IBB_PHARMACY_RATE_*`
- `MARMARAY_API_BASIC_TOKEN`
- `FERRY_SCHEDULES_ENABLED` — varsayılan `false`; yalnızca deploy ortamından tarife erişimi doğrulandıktan sonra açın. Mevcut iptal-duyurusu relay'i tarife desteği sağlamaz.
- `SEHIR_HATLARI_RELAY_URL`
- `SEHIR_HATLARI_RELAY_TOKEN`
- `IBB_RELAY_BASE_URL`, `IBB_RELAY_TOKEN` — ikisi birlikte verilirse İBB, Metro İstanbul, İSKİ, Şehir Hatları ve TCDD Marmaray host'larına giden istekler Türkiye'deki relay üzerinden çıkar; URL `https` olmalı, token en az 32 karakter. Kurulum: [deploy-railway.md](deploy-railway.md) içindeki "İBB Relay" bölümü.

## Herkese açık MCP koruma limitleri

- `CKAN_SQL_ALLOWED_RESOURCE_IDS` — SQL için operatör allowlist'i; varsayılan boş. Boyut/süre/satır ayarları ve hard cap'ler [SQL rehberinde](datastore-sql.md).
- `MCP_AUTH_REQUIRED` — varsayılan `false` (public mod). `true` yaparsanız anahtar zorunlu olur ve anahtarsız sunucu başlamaz.
- `MCP_API_KEYS` — virgülle ayrılmış rastgele Bearer anahtarları; doldurulduğunda doğrulama tek başına etkinleşir.
- `MCP_API_KEY_DAILY_QUOTA` — auth etkinken anahtar başına UTC günlük kota; varsayılan `10000`, SQLite ile kalıcı.
- `FORWARDED_ALLOW_IPS` — istemci IP'sinin okunacağı güvenilir proxy'ler; imajda `*`, dışarıdan çalıştırırken varsayılan `127.0.0.1`.
- `MCP_LEGACY_TOOLS_ENABLED` — eski araç adlarını `tools/list` içinde de yayımlar; varsayılan `false`. Eski adlar bu ayardan bağımsız olarak her zaman çağrılabilir.
- `MCP_CORS_ALLOWED_ORIGINS` — tarayıcıdan bağlanabilecek siteler; varsayılan boş. [Tarayıcı bağlantısı](browser-cors.md).
- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`
- `MCP_MAX_LISTEN_STREAMS` — istemcilerin oturum boyunca açık tuttuğu bildirim akışları (yeni protokolde `subscriptions/listen`, eski protokolde `GET /mcp/`) için ayrı üst sınır; varsayılan `200`. Bu akışlar araç isteklerinin eşzamanlılık kotasını kullanmaz.
- `EVENT_LOOP_WATCHDOG_SECONDS` — event loop bu kadar saniye yanıt vermezse tüm thread stack'leri stderr'e yazılır ve süreç `70` koduyla çıkar; Railway `ON_FAILURE` politikası servisi yeniden başlatır. Varsayılan `60`, `0` kapatır.

## İSKİ kaynak erişimi ve fallback değişkenleri

- `ISKI_REQUEST_TIMEOUT_SECONDS`
- `ISKI_REQUEST_ATTEMPTS`
- `ISKI_API_BASE_URL`
- `ISKI_API_BEARER_TOKEN`
- `ISKI_RELAY_BASE_URL`
- `ISKI_RELAY_TOKEN`
- `ISKI_RELAY_TIMEOUT_SECONDS`
- `ISKI_DAMS_SNAPSHOT_JSON`
- `ISKI_FAULTS_SNAPSHOT_JSON`
- `ISKI_FAULTS_SNAPSHOT_JSON_PART_1`, `ISKI_FAULTS_SNAPSHOT_JSON_PART_2`, ...
- `ISKI_FAULTS_SNAPSHOT_CAPTURED_AT`
- `ISKI_DAMS_SNAPSHOT_CAPTURED_AT`
- `ISKI_FAULTS_SNAPSHOT_MAX_AGE_SECONDS`
- `ISKI_DAMS_SNAPSHOT_MAX_AGE_SECONDS`

`ISKI_RELAY_TOKEN`, Cloudflare Worker'daki `RELAY_TOKEN` secret değeriyle aynı olmalıdır. `ISKI_API_BEARER_TOKEN`, İSKİ'nin kendi web istemcisinin kullandığı resmi API fallback'i için gerekir. Snapshot JSON tercihen `{"captured_at":"...","payload":...}` zarfını kullanır; eski çıplak payload biçimi için ilgili `*_SNAPSHOT_CAPTURED_AT` değişkeni zorunludur. Süresi geçmiş veya tarihsiz snapshot aktif veri olarak sunulmaz.

İSKİ canlı kaynakları bazı Railway çıkışlarından zaman aşımına düşebilir. Üretim kurulumu bu trafiği sabit hedefli ve kimlik doğrulamalı Cloudflare Worker relay üzerinden geçirir. Relay, resmi e-Devlet tablolarını ve İSKİ JSON kaynaklarını kullanır; başarılı yanıtları Workers KV'de global olarak paylaşır ve stale-while-revalidate ile yeniler. Relay ve doğrudan kaynaklar kullanılamazsa yalnızca capture zamanı bulunan ve azami yaş sınırını aşmamış snapshot döndürülebilir.
