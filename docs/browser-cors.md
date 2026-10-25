# Tarayıcıdan MCP bağlantısı — 0.2.5

Bu destek, bir web sayfasının JavaScript ile `/mcp/` adresine doğrudan istek
göndermesi içindir. ChatGPT gibi sunucu üzerinden bağlanan istemcilerin buna
ihtiyacı yoktur. Yeni şehir verisi veya yeni MCP aracı eklemez.

## İzin verilen siteyi ayarlama

`MCP_CORS_ALLOWED_ORIGINS`, virgülle ayrılmış tam origin listesidir. Origin,
sayfanın protokolü + alan adı + varsa portudur; path veya sondaki `/` dahil değildir.

```dotenv
MCP_CORS_ALLOWED_ORIGINS=https://uygulamaniz.example,http://localhost:5173
```

Örnekteki adresi kendi sitenizle değiştirin; production'a örnek adres eklemeyin.
Henüz bir site belirlenmediği için varsayılan liste **boştur**. Bu durumda Origin
gönderen MCP istekleri 403 alır; Origin göndermeyen mevcut istemciler çalışır.
Değişkeni ayarlayıp uygulamayı yeniden başlatmak gerekir; `.env.example` yüklenmez.

- En fazla 32 farklı origin; tam eşleşme kullanılır. Alt alanlar/portlar ayrı eklenir.
- HTTPS gerekir. Yalnız geliştirme için `localhost`, `127.0.0.1`, `[::1]` HTTP olabilir.
- `*`, `null`, regex, kullanıcı/parola, path, query ve fragment kabul edilmez.
- Alan adları küçük harfli ASCII/punycode olarak verilmelidir. Tarayıcının gönderdiği
  `Origin` değerini kullanın; tarayıcı varsayılan 443/80 portunu yazmayabilir.
- Hatalı yapılandırma uygulama açılışını durdurur; içerdiği gizli değerleri hataya kopyalamaz.

## İstek ve yanıt davranışı

- Yalnız `/mcp` ve `/mcp/` için uygulanır; `/status`, sağlık uçları veya başka
  yollar için CORS açılmaz. İstemci doğrudan canonical `/mcp/` adresini kullanmalıdır.
- İzinli preflight (`OPTIONS` + `Origin` + `Access-Control-Request-Method`) 200 alır;
  gövde veya MCP verisi çalıştırılmaz. Bilinmeyen method/header 400 alır.
- Origin içermeyen sade `OPTIONS`, 204 ve `Allow: GET, POST, DELETE, OPTIONS` döndürür.
  Bu yanıt CORS izni vermez. İzin verilmeyen/yinelenen Origin 403 alır.
- Tarayıcıya izin verilen method'lar: GET, POST, DELETE. Mevcut stateless MCP
  davranışı korunur; CORS bir SDK session/stream özelliği eklemez.
- İstek başlıkları: Accept, Content-Type, Authorization, Mcp-Session-Id,
  Mcp-Protocol-Version, Mcp-Method, Mcp-Name, Last-Event-ID.
- JavaScript'in okuyabildiği yanıt başlıkları: Mcp-Session-Id, Mcp-Protocol-Version,
  WWW-Authenticate, Retry-After, X-RateLimit-Limit/Remaining/Reset.
- Preflight önbellek süresi 600 saniyedir. İzinli yanıtlarda `Vary: Origin` korunur.
  401/413/429 ve yakalanmamış 500 yanıtları da izinli site tarafından okunabilir.
- Yerel SDK Host denetimi açık kalır; SDK Origin listesi CORS listesiyle eşleştirilir.
  Public deploy'un mevcut Host/proxy politikası değiştirilmez.
- `/status` yalnız etkinlik ve izin verilen origin sayısını gösterir; site listesini yayımlamaz.

## Güvenlik sınırları

CORS kimlik doğrulama değildir. Tarayıcı dışı bir istemci Origin göndermeyebilir
veya taklit edebilir. Gerçek MCP isteği mevcut API anahtarı, gövde, hız, eşzamanlılık
ve günlük kota kontrollerinden geçmeye devam eder. Preflight bu kontrolleri
tüketmez; veri döndürmeyen bir bağlantı izni kontrolüdür.

Cookie credentials açılmaz. Ortak, uzun ömürlü `MCP_API_KEYS` değerini JavaScript'e
veya herkese açık site dosyalarına gömmeyin. Anahtarlı bir servise genel bir web
arayüzü bağlayacaksanız, anahtarı koruyan bir backend üzerinden bağlanın.

## Yerel doğrulama

```bash
pytest tests/test_cors.py tests/test_api_auth.py tests/test_abuse_guard.py
python -m scripts.smoke_mcp
```

2026-10-25 gerçek Chrome kontrolü: farklı bir portta çalışan izinli yerel web
sayfası, otomatik preflight sonrasında modern MCP `tools/list` çağrısından 200 ve
16 varsayılan araç aldı. İzin listesinde olmayan ikinci sayfanın isteği tarayıcı
tarafından engellendi. Production'a örnek/test origin'i eklenmedi. Birim testleri
anahtar/kota, hız/gövde sınırı, 500, Origin taklidi ve yerel SDK Host denetimini kapsar.

Tam yerel paket: **1352 geçti, 25 atlandı**. Gerçek MCP süreç smoke testi,
bağımlılık kontrolü ve resmî Registry manifest doğrulaması geçti. İlk smoke
koşumundaki açılış bütçesi hatası sonrası tanı çıktısı korundu ve yalnız test
açılış bütçesi düzeltildi; üretim kaynak/sorgu süreleri değiştirilmedi.

Kontrol edilen belgeler (2026-10-25): Context7 `/kludex/starlette`,
[CORSMiddleware global enforcement](https://www.starlette.io/middleware/#corsmiddleware)
ve `/modelcontextprotocol/python-sdk/v2.3.0`,
[MCP browser CORS ve transport security](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/run/asgi.md).
