# API anahtarı ve kota

## Başlangıç ve istemci

Üretim varsayılanı fail-closed'dur: `MCP_AUTH_REQUIRED=true` iken geçerli
`MCP_API_KEYS` yoksa sunucu başlamaz. Anahtarlar virgülle ayrılır; her biri
32–256 karakterlik, URL-safe (`A-Z a-z 0-9 . _ ~ -`) rastgele bir değer olmalı.
Aynı anahtar iki kez tanımlanamaz; üst sınır 100 anahtardır.

```bash
# Değeri terminale yazdırmadan yeni anahtar oluşturur:
export MCP_API_KEYS="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
python -m app.main
```

İstemci her HTTP isteğinde `Authorization: Bearer <API_KEY>` göndermelidir.
URL/query parametresi üzerinden anahtar kabul edilmez. Birden fazla Authorization
başlığı da reddedilir. Anahtarı istemci secret/env mekanizmasında tutun;
README'ye, repoya veya paylaşılacak çıktılara koymayın. İnternette HTTPS kullanın.

Bu **statik API-key** mekanizmasıdır; OAuth 2.1 sunucusu, yetkilendirme ekranı veya
otomatik OAuth discovery sağlamaz. Özel Bearer header yapılandırabilen istemci
gerekir. Yalnız OAuth discovery destekleyen istemciler için ayrı OAuth
entegrasyonu gerekir. Yanıttaki `WWW-Authenticate: Bearer` bunu OAuth'a dönüştürmez.

- `/mcp`, `/mcp/*`, `/status`: anahtar zorunlu.
- `/healthz`, `/readyz`: minimal health kontrolleri anahtarsız.
- Hatalı/eksik anahtar: **401**, payload parse edilmeden.
- Anahtarlar `repr(Settings)`, HTTP logları ve `/status` içinde yayımlanmaz.
  Kota tablosunda yalnız SHA-256 fingerprint tutulur.

Kasıtlı yerel/public kullanım için:
```bash
# Anahtar da tanımlı olmamalı; anahtar varsa doğrulama yine etkinleşir.
MCP_AUTH_REQUIRED=false MCP_API_KEYS= python -m app.main
```

`.env.example` referanstır; uygulama `.env` dosyasını kendiliğinden yüklemez.
Değerleri process ortamına veya deploy secret yönetimine aktarın.

## Burst sınırı ve günlük kota

- Mevcut token-bucket burst sınırı doğrulanmış **anahtar başına** uygulanır
  (varsayılan kapasite 60, saniyede 1 token).
- `MCP_API_KEY_DAILY_QUOTA=10000`: anahtar başına UTC gününde kabul edilen
  kanonik `POST /mcp/` deneme sayısı. Initialize/list/call/notification ve
  geçerli anahtarla yapılmış hatalı JSON/tool denemeleri de sayılır.
- Auth, içerik-boyutu header, burst ve concurrency reddi günlük kotaya girmez.
  Chunked body sonradan aşılırsa deneme kotadan düşülmüş olabilir.
- GET/health/status ve `/mcp` → `/mcp/` yönlendirmesi günlük kotaya girmez.
- Kota dolunca **429** + `Retry-After`. UTC gece yarısında sıfırlanır.
- Başarılı doğrulanan POST yanıtları `X-RateLimit-Limit`,
  `X-RateLimit-Remaining`, `X-RateLimit-Reset` (Unix saniyesi) taşır.
- Günlük kullanım `DATABASE_PATH` SQLite dosyasındaki `api_daily_usage`
  tablosunda atomik transaction ile tutulur; restart ile sıfırlanmaz.
- Aynı DB/volume'u paylaşan worker'lar kotayı paylaşır. Ayrı replica diskleri
  **global kota değildir**; tek replica kullanın veya merkezi kota deposu ekleyin.
  Burst/concurrency sınırları ise process-local'dır.
- Kota DB'si kullanılamazsa **503** döner; istek kotasız ilerlemez.
- Anahtar rotasyonu kimliği değiştirir ve yeni günlük bütçe oluşturur. Tüm
  istemcilere aynı anahtarı vermek bağımsız kota sağlamaz.

Anonim/public modda mevcut ağ bazlı burst sınırı kalır. Ham
`X-Real-IP`, `CF-Connecting-IP`, `X-Forwarded-For` başlıkları uygulamada
güvenilir kimlik kabul edilmez. Proxy güvenini ASGI sunucusunda yalnız gerçekten
güvendiğiniz proxy'lere sınırlandırın; doğrulanmış anahtar kimliği her zaman
ağ adresinin önündedir.

## Yerel doğrulama

```bash
pytest tests/test_api_auth.py tests/test_abuse_guard.py
MCP_LIVE_API_KEY="<client-secret>" python -m scripts.live_mcp_uat --help
```

Live UAT helper anahtarı yalnız Authorization header'ına ekler; raporuna
yazmaz. `MCP_LIVE_API_KEY`, test sunucusunun `MCP_API_KEYS` yapılandırmasından
ayrı bir istemci değişkenidir. Canlı testler varsayılan kapalıdır.
