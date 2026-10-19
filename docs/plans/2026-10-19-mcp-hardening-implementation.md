# MCP yüzeyi ve erişim katmanı — uygulama notları

Tarih: 2026-10-19

Durum: Yerelde uygulandı ve doğrulandı; **commit/deploy yapılmadı**.

## Tamamlanan kapsam

1. **Ferry tarife kapısı:** `FERRY_SCHEDULES_ENABLED=false` varsayılan.
   Kaynak deploy ortamından doğrulanmadan tool keşfine eklenmez. İptal duyuruları
   birleşik aksaklık aracında kaldı. Mevcut relay yalnız iptal duyurularını taşır.
2. **Konsolidasyon ve eval:** 20 Türkçe senaryo önce eski yüzeyde çalıştırıldı,
   sonra yeni çağrılara eşlendi. Default yüzey 15 araçtır (14 konsolide + SQL).
   17 eski ad ayrıca açılabilir; böylece 32 tool, ferry de açılırsa 33 olur.
   Argüman çakışmaları/etkisiz filtreler sessizce yok sayılmaz. Kaynak servisleri
   ve freshness/warnings/envelope taşınır.
3. **API key + kota:** Varsayılan fail-closed başlangıç; statik Bearer
   doğrulaması; anahtar başına burst ve UTC günlük kota. Kota aynı SQLite
   dosyası korunduğunda restart'a dayanıklı ve aynı dosyayı paylaşan worker'larda
   atomiktir. Sahte proxy başlıkları kota kimliğini değiştirmez.
4. **Guarded DataStore SQL:** İBB'ye SQL gönderilmez. Operatör allowlist'i
   (varsayılan boş), tam/bounded sayfalama ve RAM SQLite `records` tablosu.
   SQLGlot AST + SQLite deny-by-default authorizer, query_only, satır/byte/
   süre/VM/çıktı sınırları. Eksik kopyadan toplam üretilmez.

İlave regression düzeltmeleri: SDK session manager her HTTP app için ayrı
kurulur; tek kullanımlık manager tekrar başlatılmaz. Rate-limit client tablosu
kapasiteye ulaştığında geri dönen mevcut istemcinin bucket'ı yanlışlıkla
evict edilip bütçesi sıfırlanmaz.

## Önceki değerlendirmeye düzeltmeler

- “15 tool idealdir / 25 üstü gateway gerekir” bir MCP standardı değildir.
  Burada yaklaşık 15, kullanıcı tarafından seçilen **ürün tasarımı hedefidir**.
- Tek datacenter çıkışındaki HTTP 403 bütün IP/ülkeler için kanıt değildir.
  Mevcut ferry servisi zaten hızlı structured `ok=false` döndürüyordu;
  HTTP retry listesi 403 içermiyor. Buradaki değişiklik, erişimi doğrulanmamış
  tarife yeteneğini varsayılan discovery'den kaldırmaktır.
- Statik API key, **OAuth 2.1/discovery değildir**. Header desteklemeyen,
  yalnız otomatik OAuth kullanan istemciler için ayrı entegrasyon gerekir.
- Mevcut filtreli `query_resource` desteklenen CKAN işidir; “sorgulayamıyor”
  değil, SQL agregasyonunu desteklemiyor demek doğrudur. Ayrı SQL aracı bunu
  bounded local capture üzerinden tamamlar.

## Doğrulama

Ortam: Python 3.12.3, MCP Python SDK **1.30.0** (proje v1 aralığında),
SQLGlot **30.23.0**. Yeni dependency: `sqlglot>=30.23,<31`.

```text
python -m pytest
580 passed, 23 skipped, 1 warning

python -m scripts.smoke_mcp
ok=true; 8 checks; external_data_api_calls=0

python -m pip check
No broken requirements found.

git diff --check
clean
```

23 skip, opt-in canlı MCP testleridir. Kalan uyarı mevcut
Starlette TestClient/httpx deprecation uyarısıdır; hata değildir.
SQL/transport regresyonları fixture tabanlıdır, canlı İBB erişimine dayanmaz.

Gerçek `python -m app.main` alt süreciyle smoke testi:
- Public health, anahtarsız status/MCP için 401.
- Anahtarlı initialize, tools/list ve tools/call.
- 15 varsayılan araç, ferry ve legacy adları görünmüyor.
- Geçersiz geo girdisi kaynağa gitmeden reddediliyor.
- SQL allowlist boşken kapalı kalıyor.
- Beş denemelik fixture kotası 429 oluyor; restart sonrası da korunuyor.

Ayrı HTTP testinde anahtar doğrulama + kota + MCP dispatch + gerçek SQL servisi +
fixture sayfaları + SQLite engine zinciri çalıştırıldı ve GROUP BY sonucu
doğrulandı. Canlı deploy/İBB SQL sorgusu denendi iddiası yoktur. Bu çalışma
tam bir pentest/AppSec değerlendirmesi değildir.

## Eval sınırları ve footprint

`tests/fixtures/evals/city_questions.json`: 20 soru × 3 freshness durumu ×
compact/legacy = **120 dispatch/envelope kontrolü**; ayrıca fixture bütünlük
kontrolü vardır. Servis yanıtları fixture'dır. Modelin Türkçe sorudan doğru
tool'u seçme başarısı **ölçülmedi**; skor artışı iddia edilmez.

`python -m scripts.eval_tools` ölçümü:

| Ölçü | Ferry kapısı sonrası baseline | Son yüzey (SQL dahil) |
|---|---:|---:|
| Tool sayısı | 29 | 15 |
| tools/list tanımlarının UTF-8 boyutu | 13.796 byte | 10.522 byte |

Tanım boyutu %23,7 küçüldü. Byte **token değildir**. Baseline/final ölçümler
`tests/fixtures/evals/{baseline,compact}_footprint.json` içinde kayıtlıdır.

## Üretime geçmeden

- Secret `MCP_API_KEYS` tanımlayın ve istemcilere Bearer header ekleyin.
  OAuth-only istemci uyumluluğunu ayrıca değerlendirin.
- `CKAN_SQL_ALLOWED_RESOURCE_IDS` için gerçekten etkin ve boyutu uygun
  DataStore resource'larını seçin; boşken hiçbir resource SQL'e açık değildir.
- Kalıcı kota için `DATABASE_PATH` kalıcı volume'da olmalıdır. Ephemeral
  container replacement dosyayı kaybeder; bağımsız replica diskleri global
  kota oluşturmaz. Bu çalışma volume veya replica oluşturmadı.
- SQL kopyaları RAM'dedir ve Python/SQLite gösterimi wire boyutundan büyüktür;
  küçük instance'larda SQL satır/byte sınırlarını düşürün.
- İstemciler tool listesini yeniden keşfetsin; geçişte gerekirse legacy flag.
- Üretim kaynağı erişimini ayrı, opt-in UAT ile ölçün. Railway durumu/oturumu
  deploy öncesinde tekrar kontrol edilmeli; bu çalışmada deploy yapılmadı.

## Kontrol edilen birincil teknik kaynaklar

Context7 üzerinden current docs kontrol edildi; v2 FastMCP/MCPServer örnekleri
v1 projeye doğrudan kopyalanmadı.

- [MCP Python SDK v1.12.4 README](https://github.com/modelcontextprotocol/python-sdk/blob/v1.12.4/README.md):
  FastMCP tools, structured response, Streamable HTTP, OAuth resource-server modeli.
  Yerelde kurulu v1.30.0 `add_tool/list_tools` API'si ayrıca kontrol edildi.
- [Starlette pure ASGI middleware](https://www.starlette.io/middleware/#pure-asgi-middleware):
  per-request state, streaming'i kesmeden middleware ve short-circuit yanıtlar.
- [HTTPX async streaming](https://www.python-httpx.org/async/#streaming-responses):
  stream context manager ve bounded byte okuma.
- [CKAN DataStore](https://docs.ckan.org/en/latest/maintaining/datastore.html):
  datastore_search, metadata, total, sıralama/sayfalama.
- [SQLGlot AST](https://github.com/tobymao/sqlglot/blob/main/posts/ast_primer.md):
  parse, Select/Table düğümleri ve AST traversal; kurulu 30.23.0'da
  `max_nodes` parser parametresi doğrulandı.
- SQLite: [authorizer](https://www.sqlite.org/c3ref/set_authorizer.html),
  [action codes](https://www.sqlite.org/c3ref/c_alter_table.html),
  [progress handler](https://www.sqlite.org/c3ref/progress_handler.html),
  [runtime limits](https://www.sqlite.org/c3ref/limit.html),
  [trusted schema](https://www.sqlite.org/c3ref/c_dbconfig_defensive.html).

## Kullanım dokümanları

- [Tool geçiş tablosu](../tool-migration.md)
- [API key/kota](../api-access.md)
- [Bounded SQL](../datastore-sql.md)
- [Tool referansı](../tool-reference.md)
- [Railway geçiş notu](../deploy-railway.md)
