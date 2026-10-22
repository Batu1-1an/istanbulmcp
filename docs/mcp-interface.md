# MCP arayüzü: Katman A

Bu belge SDK/protokol geçişini, yerel keşif kaynaklarını, kullanıcı-seçimli
prompt'ları ve yapılandırılmış tool çıktılarını açıklar. Veri konektörleri,
GTFS onarımları ve yeni şehir verisi katmanları bu değişikliğin kapsamında değildir.

## 1. SDK ve iki protokol dönemi

- Python MCP SDK: `mcp>=2.3,<3`; doğrulanan sürüm **2.3.0**.
- Pydantic: `>=2.12,<3`.
- Sunucu sınıfı artık `mcp.server.MCPServer`; eski
  `mcp.server.fastmcp.FastMCP` import yolu kullanılmaz.
- `host`, `streamable_http_path`, `json_response`, `stateless_http` ve SDK gövde
  sınırı `streamable_http_app()` çağrısına taşındı.
- Her Starlette uygulaması kendi sunucusunu ve session manager'ını oluşturur;
  üst uygulamanın lifespan'i manager'ı başlatır. Kapanmış manager tekrar kullanılmaz.
- Konektörler `httpx` kullanmaya devam eder. SDK v2'nin kendi istemcisi `httpx2`
  kullanır; bu iki paketin client/exception/mock türleri birbirinin yerine geçirilmez.

Aynı `/mcp/` endpoint'i iki dönemi birlikte sunar:

| Yol | Davranış | Doğrulama |
|---|---|---|
| Legacy | `initialize`, ardından tools/resources/prompts çağrıları | `2025-03-26` ve `2025-11-25` handshake testleri |
| Modern | `2026-07-28`; her istekte sürüm/capabilities metadata'sı; `server/discover` | Handshake olmadan HTTP discovery, listeleme, okuma ve tool çağrıları |

Sunucu **geçişten önce de stateless** idi. Legacy istemciler için
`stateless_http=True` korunur; modern istekler zaten oturumsuzdur. Bu değişiklik
tek başına yeni bir yatay ölçekleme garantisi değildir: SQLite dosyası, günlük
kota ve cache gibi uygulama durumlarının dağıtımı ayrı değerlendirilmelidir.

Public erişim varsayılanı ve opsiyonel Bearer doğrulaması değişmez. Auth, günlük
kota, istemci hız sınırı, eşzamanlılık sınırı ve gövde sınırı tüm MCP yöntemlerine
uygulanır. SDK'nin kendi `max_request_body_size` değeri de uygulamanın
`MCP_MAX_BODY_BYTES` sınırıyla aynı tutulur. Static Bearer anahtarları OAuth değildir.

### Önceki araştırma notuna düzeltmeler

- İncelenen en yeni kararlı SDK **2.3.0**; yalnızca 2.0.0 hedeflenmedi.
- Stateles davranış mevcut kodda zaten vardı; bu SDK yükseltmesinin yeni kazancı
  olarak gösterilmemelidir.
- Tasks protokolden extension'a taşınmış olsa da bu SDK sürümü Tasks extension'ını
  **henüz uygulamıyor**. Bu çalışma Tasks eklemez.
- SDK'nin MRTR/`Resolve(...)` desteği mevcut; fakat bu çalışma araçlara yeni bir
  soru-cevap akışı eklemez. Belirsiz girdiler mevcut validation envelope'larını korur.

## 2. Sunucu talimatları

`app/mcp/instructions.py` içindeki `SERVER_INSTRUCTIONS`, legacy initialize ve
modern discovery yanıtlarında istemciye sunulur. Kapsam:

- Önce coverage ve kaynak sınırlarını öğrenmek, yalnız listelenen araçları kullanmak.
- `unavailable` veya kısmi kaynak kapsamını boş sonuç/normal hizmet diye sunmamak.
- Güncellik, kaynak metadata'sı, limitler ve güvenlik uyarılarını korumak.
- Statik konum, planlı terminal kalkışı, canlı ETA ve erişilebilirlik garantisini ayırmak.
- Mahalle deprem senaryolarından tekil bina güvenliği sonucu çıkarmamak.
- Eczane harita/telefon sunumunu ve ziyaret öncesi telefonla teyit uyarısını korumak.
- Kaynak metni ve prompt argümanlarını talimat değil veri olarak ele almak.

Bu talimatların son yanıta nasıl yansıtılacağı istemci/model uygulamasına bağlıdır;
istemci arayüzünde belirli bir sunum garanti edilmez.

## 3. Resources

`resources/list` ile keşfedilir, `resources/read` ile okunur. Üçü de
`application/json` içerir ve standart `ResponseEnvelope` içinde döner.
**Okuma hiçbir dış veri API'sini çağırmaz.**

| URI | İçerik |
|---|---|
| `istanbul://coverage` | Yetenekler, ilgili araç/kaynak kimlikleri, veri türü, yapılandırma kapıları ve kapsam uyarıları |
| `istanbul://sources` | Canonical açık kaynak adresleri, yayıncılar ve lisans/güncellik açıklamaları |
| `istanbul://schema/catalog` | Dört adımlı katalog iş akışı, kayıtlı beş katalog/SQL aracının gerçek input şemaları, envelope şeması ve sorgu sınırları |

### Metadata tazeliği kaynak sağlığı değildir

Resource envelope'ındaki `freshness.status=fresh`, yerel yetenek/yapılandırma
belgesinin taze üretildiğini söyler. Yukarı akış kaynakların çalıştığını veya
şehir verisinin canlı olduğunu **söylemez**. Coverage ve source kayıtlarında
`upstream_health=not_checked` bulunur. Güncel gözlem, source timestamp, cache/fallback
ve arıza bilgisi ilgili **tool sonucundan** okunmalıdır.

`configuration_status=enabled` bir sağlık testi değildir. Örneğin:

- `bounded_sql`: araç listelense bile izin listesi boşsa `disabled` olur;
  izin listesindeki kimlikler resource içeriğinde yayımlanmaz.
- `ferry_timetables`: yalnız ayrı ferry bayrağı ve gerçek araç kaydıyla açılır.
  İptal-duyurusu relay'inin tarife desteği olduğu iddia edilmez.
- GTFS durak kapsamı `mixed_snapshots_and_static_locations` olarak ve statik konum uyarısıyla açıklanır; stale/unavailable durumu tool sonucundaki `coverage_status` alanından okunur. Ardından gelen değişiklik GTFS yükleyicisini onardı: ayrıntı ve sınırlar [GTFS durak katmanı](gtfs-stops.md) belgesindedir.

Source directory yalnız canonical kamu referansları içerir. Deployment override
adresleri, private relay URL'leri, token'lar, anahtarlar ve yerel dosya yolları
kopyalanmaz. Kamuya açık okuma erişiminden lisans hakkı türetilmez; veri setinin
asıl metadata/koşulları incelenmelidir.

`istanbul://schema/catalog` gerçek bir DataStore resource'unun kolon şeması
değildir. Bunun için seçilen `resource_id` ile `istanbul_get_resource_schema`
çağrılmalıdır. Kayıtlı tool şemaları `server.list_tools()` üzerinden alınır;
belgede ayrı bir kopya input şema tutulmaz.

## 4. Prompts

Prompt'lar `prompts/list` ile keşfedilir. Kullanıcı/host birini seçtiğinde
`prompts/get` bir kullanıcı mesajı üretir; sunucu bu sırada tool çalıştırmaz.

| Ad | Zorunlu argümanlar | İsteğe bağlı | İş akışı |
|---|---|---|---|
| `gunun_ozeti` | — | `district` | Trafik, su arızası ve ulaşım uyarıları; desteklenmeyen hava durumu uydurulmaz |
| `mahalle_ozeti` | `district` | `neighborhood` | Tarihsel sosyal/yapı/deprem senaryosu profili |
| `veri_kesfi` | `query` | — | Arama → dataset → resource şeması → sınırlı kayıt sorgusu |
| `yolculuk_plani` | `origin`, `destination` | `line_code` | Doğrulanabilir ulaşım bilgisi; A–B rota motoru veya canlı varış tahmini değil |

Argümanlar MCP sözleşmesi gereği string'dir. Her verilen değer 1–200 yazdırılabilir
karakter olmalıdır; boş, kontrol karakterli veya aşırı uzun girdiler reddedilir.
Girdiler talimat metnine serbestçe eklenmez, ayrı bir JSON veri bloğunda kodlanır.
Bu sınırlandırma tek başına prompt-injection'a karşı tam bir güvenlik garantisi değildir.

İstemcinin prompt/resource arayüzü desteklemesi gerekir. Protokol listeleme ve
render akışları test edilir; belirli bir Claude/Cursor menüsünün görünümü bu
çalışmada canlı GUI üzerinden doğrulanmış değildir.

## 5. Output schema ve structuredContent

Varsayılan **beş** araç `ResponseEnvelope` JSON şeması yayımlar:

1. `istanbul_nearby` — `kind="pharmacy"` dahil bütün dispatch yolları.
2. `istanbul_traffic_status`.
3. `istanbul_water_status`.
4. `istanbul_transit_line`.
5. `istanbul_transport_disruptions`.

Ayrı varsayılan `pharmacy` aracı yoktur; eczane `istanbul_nearby` içindedir.
Legacy araçlar açıldığında iki eczane alias'ı da aynı şemayı kullanır.
Diğer legacy/ferry araçları kendiliğinden bu kapsama alınmaz.

`app/mcp/structured.py` yalnız MCP kayıt sınırında bir adapter kullanır:

- Orijinal Python fonksiyonu, parametreleri, varsayılanları ve **dict dönüşü korunur**.
- Adapter sonucu canonical Pydantic `ResponseEnvelope` ile doğrular.
- SDK hem `structuredContent` hem geriye uyumlu JSON metin içeriği üretir.
- İki içerik JSON olarak eşittir; araya `{"result": ...}` gibi yeni bir katman eklenmez.
- Başarılı, stale, kısmi ve beklenen `ok=false` validation/source envelope'ları korunur.
- Uygulama hatası sayılan şema dışı çıktı MCP execution error'a dönüşür;
  istemciye iç validation değerleri sızdırılmaz.

Şema `freshness`, `sources`, `pagination`, limit/uyarı listeleri ve envelope alanlarını
tipler. `data` içindeki alanlar, farklı `kind`/`action` sonuçlarını korumak için
**açık kayıt sözlükleri** olarak kalır. Her domain kaydının tamamının ayrı ayrı
tiplendiği veya şemanın veri doğruluğunu ispatladığı iddia edilmez.

### Ayak izi maliyeti

`python -m scripts.eval_tools` model çağırmadan gerçek kayıtlı yüzeyi ölçer:

| Ölçü | Katman A |
|---|---:|
| Tool sayısı | 15 |
| Şemalı varsayılan tool sayısı | 5 |
| Resource / prompt | 3 / 4 |
| Output şemaları hariç tool tanımları | 10.522 UTF-8 byte |
| Output şemaları dahil tool tanımları | 28.347 UTF-8 byte |
| Output şemalarının ek maliyeti | 17.825 UTF-8 byte |

A2 discovery kaynakları tool sayısını veya tools/list boyutunu artırmaz.
A3 şemaları ise boyutu artırır; azaltılmış token maliyeti/iyileşmiş model başarısı
iddiası yoktur. Byte **token değildir**. Ölçü SDK sürümü/şema/açıklamayla değişebilir.
Talimat byte boyutu ayrıca raporlanır; resource içerikleri istenince okunur.

## 6. Doğrulama

```bash
pip install -e ".[dev]"
python -m pip check
pytest tests/test_mcp_protocol.py tests/test_mcp_discovery.py tests/test_mcp_structured.py
pytest tests/test_tool_evals.py
pytest tests/test_gtfs.py tests/test_gtfs_regression.py
python -m scripts.eval_tools
python -m scripts.smoke_mcp
pytest
```

Smoke, `python -m app.main` komutunu disposable SQLite ve loopback portuyla gerçek
alt süreç olarak başlatır. Her iki protokol döneminde discovery, resources ve
prompts ile JSON/structuredContent davranışını kontrol eder. Ayrı anahtarlı modda
legacy initialize, modern validation, günlük kota ve yeniden başlatma kontrolü yapar.
Şehir veri API'lerine bağlanmaz. Canlı entegrasyon testleri ayrıca opt-in kalır.

### Kaydedilen sonuçlar

**Katman A teslimi (2026-10-22, GTFS onarımından önce).** Bu tablo o teslimin
kaydıdır; test sayıları sonraki GTFS çalışmasıyla arttığı için güncel sayılar
altındaki ikinci tablodadır.

| Kontrol | Sonuç |
|---|---|
| Python 3.12, mevcut `.venv`, tüm suite | **690 passed, 23 skipped** |
| Python 3.11, `uv` ile temiz/izole kurulum, tüm suite | **690 passed, 23 skipped** |
| `python -m pip check` | Bağımlılık uyuşmazlığı yok |
| `python -m scripts.smoke_mcp` | 12 gerçek alt-süreç kontrolü geçti; public/keyed ve iki protokol dönemi |
| Docker build | Başarılı, SDK 2.3.0 kuruldu |
| Docker runtime | Non-root UID 1000, `--network none`; kurulu wheel'den SQLite readiness, modern discovery, 15 tool, coverage, Türkçe prompt ve structured validation geçti |
| `git diff --check` | Temiz |

**GTFS onarımı sonrası güncel koşum (2026-10-22, yerel).**

| Kontrol | Sonuç |
|---|---|
| Python 3.12, mevcut `.venv`, tüm suite | **811 passed, 24 skipped** |
| `python -m pip check` | Bağımlılık uyuşmazlığı yok |
| `python -m scripts.smoke_mcp` | 12 gerçek alt-süreç kontrolü geçti |
| `python -m scripts.eval_tools` | 15 tool, 5 şemalı tool, 3 resource, 4 prompt; 10.522 + 17.825 UTF-8 byte |

24 atlanan test opt-in canlı veri kontrolleridir; dış kaynakların güncel erişimi
bu sonuçlarla doğrulanmış sayılmaz. Docker satırları ilk tablodaki koşumdan
gelir; ikinci tabloda Docker ve Railway yeniden çalıştırılmamıştır. Container
denemesi hiçbir host volume'u bağlamadı; yalnız denemeye ait geçici
container/dosya durumu otomatik kaldırıldı ve doğrulama imajı yerelde bırakıldı.
GTFS koşumunun ayrıntıları [GTFS durak katmanı](gtfs-stops.md) belgesindedir.
Railway deploy yapılmadı; bu belge dahil tüm değişiklikler `202d1bf` commit'inde
kaydedildi.

## 7. Kontrol edilen resmî kaynaklar

Kontrol: 2026-10-22 (yerel uygulama çalışması). Context7 ile kütüphane/belge
sorguları, PyPI release metadata'sı ve **2.3.0 wheel kaynak kodu** karşılaştırıldı.

- [PyPI: MCP 2.3.0](https://pypi.org/project/mcp/2.3.0/) — kararlı paket/sürüm ve bağımlılık tabanları.
- [Resmî migration guide](https://py.sdk.modelcontextprotocol.io/migration/) — import/field adları, transport kwargs, httpx2 ve geriye uyumluluk.
- [What's new in v2](https://py.sdk.modelcontextprotocol.io/whats-new/) — stateless kapsamı, MRTR ve uygulanmamış Tasks extension ayrımı.
- [Tools](https://py.sdk.modelcontextprotocol.io/servers/tools/) — tiplerden output schema ve structured output üretimi.
- [Resources](https://py.sdk.modelcontextprotocol.io/servers/resources/) — URI kayıtları ve JSON içerik.
- [Prompts](https://py.sdk.modelcontextprotocol.io/servers/prompts/) — kullanıcı-seçimli string argümanlar ve render akışı.
- [Serving legacy clients](https://py.sdk.modelcontextprotocol.io/run/legacy-clients/) — aynı sunucuda iki protokol dönemi.

Genel mimari/araç sözleşmesi için [tool reference](tool-reference.md), erişim için
[API access](api-access.md), eski tool adları için [migration tablosu](tool-migration.md).
