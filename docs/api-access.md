# Erişim, kimlik ve sınırlar

## Varsayılan: public mod

Sunucu **anahtarsız** çalışır. İstemci yalnız URL'i ekler:

```bash
claude mcp add --transport http istanbul https://istanbulmcp-production.up.railway.app/mcp/
codex mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
```

Public modda koruma katmanları:

- İstemci başına token-bucket burst sınırı (varsayılan 60 kapasite, saniyede 1).
- İstek gövdesi üst sınırı (`MCP_MAX_BODY_BYTES`), eşzamanlılık sınırı.
- Kaynak başına back-pressure ve TTL cache (İBB, İETT, İSKİ).
- SQL aracı **kapalı**: `CKAN_SQL_ALLOWED_RESOURCE_IDS` boş olduğu sürece
  hiçbir resource sorgulanamaz.

### İstemci IP'si nereden gelir?

Public modda burst sınırı istemci IP'sine göre uygulanır. Railway/Cloudflare gibi
platformlarda bağlantı proxy'den gelir; bu yüzden ASGI sunucusu
`X-Forwarded-For`'u güvenilir proxy'lerden okur:

- Docker imajı `FORWARDED_ALLOW_IPS=*` ile gelir; container portu yalnız
  platform proxy'si üzerinden erişilebilir olduğu için bu doğrudur.
- Container'a doğrudan erişim varsa `FORWARDED_ALLOW_IPS` değerini proxy
  IP'leriyle daraltın. Varsayılan değer `127.0.0.1`'dir.
- Uygulama `X-Real-IP`, `CF-Connecting-IP` gibi başlıkları kendi başına
  güvenilir saymaz; tek karar noktası ASGI sunucusunun proxy ayarıdır.

Bu ayar yanlışsa iki uç sonuç olur: tüm istemciler tek kovayı paylaşır (çok sıkı)
veya istemci kendi IP'sini uydurabilir (çok gevşek).

## Anahtar istemek (opsiyonel)

Anahtar zorunlu değildir. İki env değişkeni yeterlidir:

```bash
# Anahtar tanımlamak auth'u tek başına açar:
export MCP_API_KEYS="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"

# İsteğe bağlı: anahtar yoksa sunucu hiç başlamasın (fail-closed)
export MCP_AUTH_REQUIRED=true
```

- Anahtarlar virgülle ayrılır; her biri 32–256 karakter, URL-safe
  (`A-Z a-z 0-9 . _ ~ -`), en fazla 100 adet ve benzersiz olmalı.
- `MCP_API_KEYS` doluyken doğrulama **her zaman** etkindir; bir anahtar
  sessizce yok sayılmaz.
- `MCP_AUTH_REQUIRED=true` + boş anahtar listesi = başlatma hatası.
- Geçersiz boolean (`MCP_AUTH_REQUIRED=maybe`) sessizce public moda düşmez;
  başlatma hatası verir.

İstemci her istekte `Authorization: Bearer <API_KEY>` gönderir. Query
parametresiyle anahtar kabul edilmez, çift `Authorization` başlığı reddedilir.
Anahtarlar `repr(Settings)`, HTTP logları ve `/status` içinde görünmez; kota
tablosunda yalnız SHA-256 fingerprint tutulur.

Bu **statik API-key** mekanizmasıdır; OAuth 2.1 sunucusu veya discovery değildir.
Yalnız otomatik OAuth destekleyen istemciler (ör. Claude.ai custom connector)
için ayrı entegrasyon gerekir.

## Anahtar başına günlük kota

Auth etkinken:

- `MCP_API_KEY_DAILY_QUOTA=10000`: anahtar başına UTC gününde kabul edilen
  kanonik `POST /mcp/` denemesi.
- Initialize/list/call/notification ve geçerli anahtarla yapılmış hatalı
  JSON/tool denemeleri sayılır. Auth, gövde-boyutu, burst ve eşzamanlılık
  reddi sayılmaz. Chunked gövde sonradan aşılırsa deneme düşülmüş olabilir.
- Kota dolunca **429** + `Retry-After`; UTC gece yarısı sıfırlanır.
- Yanıtlarda `X-RateLimit-Limit`, `X-RateLimit-Remaining`,
  `X-RateLimit-Reset` (Unix saniye) bulunur.
- Sayaç `DATABASE_PATH` SQLite dosyasındaki `api_daily_usage` tablosundadır;
  restart ile sıfırlanmaz. Aynı dosyayı paylaşan worker'lar kotayı paylaşır.
  Ayrı replica diskleri **global kota değildir**.
- Kota deposu okunamazsa **503**; istek kotasız ilerlemez.

Public modda günlük kota yoktur; yalnız burst sınırı ve kaynak back-pressure
geçerlidir.

## SQL aracını açarken

`CKAN_SQL_ALLOWED_RESOURCE_IDS` doldurulduğunda anonim istemciler bounded
DataStore kopyası indirebilir (istek başına en fazla 20 MiB). Public modda
allowlist'i boş tutun; açacaksanız `MCP_API_KEYS` ile birlikte açın. Sunucu bu
kombinasyonda başlangıçta uyarı loglar. Ayrıntı: [bounded SQL](datastore-sql.md).

## Uçlar

| Uç | Public mod | Auth etkinken |
|---|---|---|
| `/healthz`, `/readyz` | Açık | Açık |
| `/mcp/`, `/mcp` | Açık | Bearer zorunlu |
| `/status` | Açık | Bearer zorunlu |

`/status` yalnız yapılandırma metadatası döndürür: tool listesi, TTL'ler,
redakte edilmiş cache özeti ve `access` bloğu (`api_key_required`,
`daily_quota_per_key`). Anahtar, token veya veritabanı yolu içermez.

## Yerel doğrulama

```bash
pytest tests/test_api_auth.py tests/test_abuse_guard.py
python -m scripts.smoke_mcp          # public mod + auth modu ayrı ayrı
```

`scripts/smoke_mcp.py` gerçek `python -m app.main` sürecini başlatır, dış veri
kaynağına bağlanmaz, ürettiği anahtarı yazdırmaz ve geçici dizini siler.
