# Istanbul MCP

## İçindekiler

- [Başlangıç](#hızlı-başlangıç)
- [Kullanım](#ne-yapabilir)
- [MCP keşfi](#mcp-keşfi-ve-promptlar)
- [Kurulum](#i̇stemci-kurulumları)
- [Geliştirme](#geliştirme)
- [Dağıtım](#dağıtım)

---

Istanbul MCP, İstanbul'a dair açık verileri MCP destekleyen yapay zekâ araçları, geliştirici ortamları ve ajan tabanlı iş akışları için erişilebilir hale getiren uzak bir Model Context Protocol sunucusudur.

Uzak endpoint:

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

## Neden Var?

İstanbul'da otopark, ulaşım, trafik, su kesintisi, baraj doluluğu, kütüphane, WiFi, müze, mahalle profili ve açık veri gibi konularda çok sayıda kamusal veri var. Bu veriler portallarda ve farklı servislerde duruyor; ancak yapay zekâ destekli araçlar veya ajanlar içinden doğrudan kullanmak çoğu zaman pratik değil.

Istanbul MCP bu boşluğu kapatır. Codex, Claude, Cursor, OpenCode, Windsurf, Antigravity gibi araçlar veya MCP destekleyen farklı ajan sistemleri tek bir endpoint üzerinden İstanbul verisiyle çalışabilir.

Kullanım alanı yalnızca sohbet arayüzleri değildir. Kod yazan bir ajan, araştırma yapan bir iş akışı, veri analizi çıkaran bir sistem veya kendi otomasyonunuz da aynı endpoint'i kullanabilir.

## Hızlı Başlangıç

Kurulum anahtar gerektirmez: URL'i ekleyin, çalışır. İstemci başına burst
sınırı uygulanır; isteğe bağlı anahtar/kota ve SQL kısıtları için
[erişim rehberine](docs/api-access.md) bakın.

Codex CLI ile eklemek için:

```bash
codex mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
codex mcp list
```

Claude Code ile eklemek için:

```bash
claude mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
```

Claude Desktop ve Claude.ai (Settings > Connectors > Add custom connector):

```text
URL: https://istanbulmcp-production.up.railway.app/mcp/
```

Sonra yeni bir oturum açıp örnek bir soru sorun:

```text
Taksim'e arabayla gideceğim. Yakındaki otoparkların boş yer sayısını, çalışma saatini ve haritadaki yerlerini gösterir misin?
```

Genel MCP istemci yapılandırması:

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Bazı istemciler `url` yerine `serverUrl`, `"type": "remote"` veya `"transport": "http"` ister. Endpoint'i sondaki `/mcp/` ile kullanın.

## Ne Yapabilir?

- İBB Açık Veri kataloğunda veri seti arayabilir.
- Veri seti metadata bilgisi, resource listesi ve DataStore şeması döndürebilir.
- Seçili CKAN DataStore resource'larını güvenli filtreler ve limitlerle sorgulayabilir.
- İstanbul geneli trafik yoğunluğu indeksini döndürebilir.
- Aktif İSKİ su arızalarını ilçe, arıza numarası veya koordinata yakınlıkla sorgulayabilir.
- İSKİ baraj doluluk oranlarını ve baraj hacim bilgilerini listeleyebilir.
- Yakındaki İSPARK otoparklarını kapasite, boş kapasite, açık/kapalı durumu, çalışma saati ve harita linkiyle listeleyebilir.
- İlçe bazlı otopark sorularında sahte merkez mesafesi üretmeden ilçe kayıtlarını döndürebilir.
- Yakındaki Metro İstanbul istasyonlarını, toplu taşıma duraklarını, WiFi noktalarını ve hava kalitesi istasyonlarını bulabilir.
- `Kadıköy Rıhtım`, `Taksim`, `Levent` gibi bilinen yerler için mobilite özeti çıkarabilir.
- İETT hat bilgisi ve hat duraklarını yönlerine göre sıralı döndürebilir.
- Kütüphane kayıtlarında adres, telefon, çalışma saatleri ve harita arama linki verebilir.
- Mahalle profillerini sosyal yardım, bina stoku ve deprem senaryosu açık verileriyle oluşturabilir.

Konum bilgisi olan kayıtlarda `maps_url` döner. Yalnızca adres bilgisi olan kayıtlarda `maps_search_url` ve `location_precision=address_search` kullanılabilir; bu kayıtlar kesin koordinat gibi sunulmaz.

Nöbetçi eczane araçlarının yanıt talimatı, gösterilen her eczaneye tıklanabilir harita bağlantısı eklenmesini ister. Koordinat eksikse eczane adı ve adresiyle harita arama bağlantısı döner. İBB kaynak adı ve bağlantısı, kullanıcı özellikle kaynak istemedikçe son yanıtta gösterilmez; `sources` alanı teknik izlenebilirlik için korunur. Güncellik, sonuç sınırları ve telefonla teyit uyarıları yanıtta korunur. Son yanıtın biçimlendirilmesi MCP istemcisine bağlıdır.

## Veri Seti Keşfi

Veri seti araştırması projenin ana kullanım alanlarından biridir. Bir konu hakkında İBB Açık Veri kataloğunda hangi veri setleri var, formatları ne, DataStore üzerinden sorgulanabilir resource'ları var mı gibi sorular doğrudan sorulabilir.

Örnek:

```text
İBB açık veri kataloğunda müzelerle ilgili hangi veri setleri var?
```

Örnek sonuçlar:

- `Kültür ve Turizm Bakanlığına Bağlı Müze Ziyaretçi Sayısı`
- `Müzelerimiz ve Ziyaretçi Sayıları`
- `İBB Müzeleri Lokasyon Çalışma Gün ve Saatleri`

Bu resource'lar ayrıca sorgulanabilir. Örneğin müze lokasyon resource'u müze adı, ilçe, adres, telefon, çalışma saatleri ve çalışma günleri gibi alanlar döndürür.

## Örnek Sorular

```text
Taksim'e arabayla gideceğim. Yakındaki otoparkların boş yer sayısını, çalışma saatini ve haritadaki yerlerini gösterir misin?
Levent yakınındaki metro istasyonları hangileri? Hat bilgisi ve harita linkleriyle listele.
500T hattı hangi duraklardan geçiyor? Durakları yönlerine göre sıralı ve harita linkleriyle göster.
İstanbul trafik yoğunluğu şu an hangi seviyede?
Şişli civarında aktif su kesintisi veya İSKİ arızası var mı?
10000511943 numaralı İSKİ arızasının detayını gösterir misin?
Baraj doluluk oranları şu an nasıl? En dolu 5 barajı listele.
İBB açık veri kataloğunda müzelerle ilgili hangi veri setleri var?
Beşiktaş'ta hangi kütüphaneler var?
Kadıköy Rıhtım çevresinde ulaşım seçenekleri neler?
Kadıköy Caferağa mahalle profili nedir?
```

## Örnek Çıktılar

Taksim yakınındaki otopark sorusu; otopark adı, mesafe, kapasite, boş kapasite, çalışma saati, açık/kapalı durumu ve Google Maps linki döndürür.

500T hat sorusu; hat adı, tarife, hat uzunluğu, tahmini yolculuk süresi ve iki yöndeki durakları sıra numarasıyla döndürür.

Trafik sorusu; şehir geneli trafik indeksini, ölçüm zamanını ve bu kaynağın yol bazlı kaza/olay detayı sağlamadığını belirten sınır bilgisini döndürür.

İSKİ arıza sorusu; aktif arızanın ilçe, mahalle, açıklama, başlangıç zamanı, tahmini bitiş zamanı, yaklaşık geometri merkezi ve Google Maps linkini döndürür. Railway ortamından İSKİ canlı harita kaynağına erişilemediğinde yapılandırılmış snapshot fallback kullanılır ve sonuç `freshness.status=stale` olarak işaretlenir.

Baraj doluluk sorusu; baraj adı, doluluk oranı, mevcut su hacmi, kapasite ve maksimum su seviyesi alanlarını döndürür. Canlı kaynak erişilemezse resmi İSKİ API veya snapshot fallback devreye girer.

## Veri Kaynakları

Istanbul MCP şu kaynaklardan gelen verileri kullanır:

- İBB Açık Veri Portalı (`data.ibb.gov.tr`)
- İBB City APIs (`api.ibb.gov.tr`)
- İSPARK otopark servisleri
- Metro İstanbul istasyon verileri
- İETT SOAP servisleri
- İSKİ harita ve baraj kaynakları
- İBB Şehir Haritası nöbetçi eczane servisi (`cbsproxy.ibb.gov.tr/?eczanews&ilceID=all`)
- İBB Açık Veri Portalı İstanbulkart dolum merkezi DataStore kaynağı (yıllık konum verisi)
- İBB WiFi, kütüphane, hava kalitesi ve mahalle profili kaynakları

Tüm araç sonuçları standart bir cevap modeliyle döner: `summary`, `data`, `freshness`, `sources`, `limits`, `warnings` ve gerektiğinde `next_queries`.

## MCP Araçları

Varsayılan yüzey **15 salt okunur araçtır**; eski adlar
`MCP_LEGACY_TOOLS_ENABLED=true` ile ayrıca açılabilir. Yetenekler kaldırılmadı,
yakınlık/ilçe sorguları, su verileri ve İETT hat işlemleri birleştirildi.
[Geçiş tablosu](docs/tool-migration.md) eski → yeni çağrıları gösterir.

```text
istanbul_health
istanbul_search_datasets
istanbul_get_dataset
istanbul_get_resource_schema
istanbul_query_resource
istanbul_datastore_query
istanbul_nearby
istanbul_traffic_status
istanbul_water_status
istanbul_mobility_nearby
istanbul_city_services_nearby
istanbul_neighborhood_profile
istanbul_transit_line
istanbul_transport_disruptions
istanbul_metro_accessibility_status
```

| Araç | İşlev ve örnek |
|---|---|
| `istanbul_health` | Servis ve SQLite hazırlığı. |
| `istanbul_search_datasets` | Konuya göre İBB katalog araması. |
| `istanbul_get_dataset` | Veri seti metadata ve kaynakları. |
| `istanbul_get_resource_schema` | Resource kolonları. |
| `istanbul_query_resource` | CKAN kayıtlarını güvenli filtre ve limitle getirir. |
| `istanbul_datastore_query` | İzin verilen resource'un tam ve sınırlı kopyası üzerinde SELECT/GROUP BY. [SQL rehberi](docs/datastore-sql.md). |
| `istanbul_nearby` | `kind=parking,pharmacy,istanbulkart,social_facility,metro_station,air_quality,water_fault,city_feature`. Koordinatla yakınlık; parking/pharmacy için ilçe; city_feature için bbox. |
| `istanbul_traffic_status` | Şehir geneli trafik indeksi; yol bazlı değildir. |
| `istanbul_water_status` | `kind=faults`: ilçe veya arıza numarası; `kind=dams`: baraj dolulukları. |
| `istanbul_mobility_nearby` | Bilinen yer veya koordinata göre ulaşım özeti. |
| `istanbul_city_services_nearby` | WiFi ve ilçe düzeyinde kütüphaneler. |
| `istanbul_neighborhood_profile` | Sosyal yardım, bina stoku, deprem **senaryosu**; anlık risk değildir. |
| `istanbul_transit_line` | `action=info,stops,departures`; planlı kalkışlar ana durak içindir, ETA değildir. |
| `istanbul_transport_disruptions` | Desteklenen işletmelerin güncel durumları ve resmî duyuruları. |
| `istanbul_metro_accessibility_status` | Ekipman toplamları ve arıza ayrıntıları; yolculuk erişilebilirliği garantisi değildir. |

`istanbul_ferry_schedules` varsayılan kapalıdır (`FERRY_SCHEDULES_ENABLED=false`).
Kontrol edilen çıkıştan Şehir Hatları tarife kaynağı HTTP 403 challenge döndürdü.
Deploy ortamından erişim doğrulanmadan açmayın; mevcut iptal-duyurusu relay'i
tarifeyi taşımaz. İptal duyuruları aksaklık aracında kalır; kaynak hatası
`unavailable` olarak raporlanır.

`istanbul_transport_disruptions` yalnızca dört doğrulanmış resmî aksaklık kapsamını kontrol eder: İETT ve Metro İstanbul canlı durumları ile Metro resmî planlı duyuruları; Şehir Hatları iptal/sefer düzenlemesi duyuruları; Marmaray resmî son dakika duyuruları. Metro canlı durum ve planlı duyurular ayrı `sources[]` coverage kayıtlarıdır; biri okunamazsa genel “aksaklık yok” özeti verilmez. `istanbul_ferry_schedules` normal tarife için ayrı çalışır: önce resmî tarife indeksinden tam rota eşleşmesi yapar, sonra canonical rota HTML tablosunu parse eder. Bu sonuç `coverage_kind=published_timetable` ve statik tarife uyarısı taşır; canlı kalkış, gecikme veya ETA değildir. `mode`, `operator`, `line` ve `limit` isteğe bağlıdır. `line`, `line_code` veya `route_label` üzerinde büyük/küçük harften bağımsız tam eşleşir. Kaynaklar 120 saniye önbelleklenir; kısmi kaynak hataları `sources[].coverage_status=unavailable`, `freshness=unknown` ve `warnings` ile görünür. Şehir Hatları sayfası genel ve tarihli bir duyuru verirse sistem hat kodu uydurmaz; relay veya doğrudan resmi sayfa erişimi `403` ile engellenirse bunu açıkça `unavailable` bildirir. Marmaray Angular kabuğu döndürdüğünde, yapılandırılmış `MARMARAY_API_BASIC_TOKEN` ile resmi frontend API’si kullanılır; API boş liste döndürürse bu checked empty sonucudur. İDO, Turyol, Dentur, minibüs ve taksi-dolmuş canlı kapsama dahil değildir ve cevap `limits[]` içinde belirtilir. Metro ekipman arızası, rota motoru, ETA ve GTFS `stop_times` arşivi bu araçların kapsamı değildir.

`istanbul_metro_accessibility_status` resmî Metro İstanbul ekipman/tesis toplamlarını ve güncel ekipman arıza ayrıntılarını iki bağımsız resmî kaynaktan okur: (1) `GetFaultyEquipments` JSON servisinden kategori bazlı çalışan/arızalı toplamlar ve (2) resmî Metro İstanbul arıza sayfasından hat/istasyon/ekipman konumu, neden ve planlanan dönüş metni. Her kaynak ayrı önbelleklenir: 120 saniye güncel, ilk başarılı gözlemden itibaren toplam en fazla 15 dakika eski-veri. İsteğe bağlı `line` (tam hat kodu veya resmî hat etiketi), `station` ve `equipment_type` (canonical anahtar veya kaynak etiketi) filtreleri yalnız ayrıntı listesine uygulanır; `limit` (varsayılan 50, en fazla 100) yalnız filtrelenmiş ayrıntı listesini kırpar. Özet toplamları `limit`'ten etkilenmez. Bir kaynak başarısız olursa diğerinin doğrulanmış verisi `partial_source` uyarısıyla korunur; ikisi birden başarısız olursa `ok=false`/`broken` zarf döner. `İnceleniyor` gibi açık-uçlu dönüş metinleri olduğu gibi korunur; kesin dönüş tarihi üretilmez. Cevaplar `source`, `observed_at`, `fresh/stale/partial/broken` durumu ve şu açık sınırları taşır: tekil ekipman kaydı kesin istasyon/yolculuk erişilebilirliği, alternatif rota veya çalışan yedek ekipman sonucu üretmez.

Parametreler, davranışlar ve sınırlar için [docs/tool-reference.md](docs/tool-reference.md) dosyasına bakın.

### GTFS durak konumları

`istanbul_nearby(lat=...,lon=...,types=["public_transport_stop"])` ve
`istanbul_mobility_nearby`, resmî İBB `stops.csv` dosyasını kullanır;
`stop_times` durak konumu olarak taranmaz ve DataStore aktivasyonu gerekmez.
BOM/`;` ve bilinen nokta-gruplamalı koordinat biçimi kaynak-özel olarak işlenir.
Varsayılan bütçe **5 MiB / 50.000 satır / 20 saniye**; başarısız veya eksik
yükleme mevcut indeksi değiştirmez. Eski veri yalnız sınırlı stale penceresinde
uyarıyla sunulur; kaynağa erişilememesi “yakında durak yok” anlamına gelmez.

Bunlar **statik durak konumlarıdır**; canlı varış, işletilme durumu veya yeni bir
`next_departures` özelliği değildir. Kaynak zamanı, alınan/kabul edilen/atlanan
sayıları cevapta korunur. Ayrıntılar ve canlı kabul komutu:
[GTFS durak katmanı](docs/gtfs-stops.md).

## MCP Keşfi ve Promptlar

Python MCP SDK **2.3+** ile aynı `/mcp/` endpoint'i hem eski `initialize`
istemiyle hem `2026-07-28` sürümündeki `server/discover` akışıyla çalışır.
Varsayılan araç sayısı **15** olarak kalır. Sunucu talimatlarına ek olarak:

| Resource URI | İçerik |
|---|---|
| `istanbul://coverage` | Desteklenen yetenekler, yapılandırma kapıları ve kapsam sınırları |
| `istanbul://sources` | Canonical veri kaynakları, yayıncılar, lisans/güncellik açıklamaları |
| `istanbul://schema/catalog` | Katalog keşif akışı, araç input şemaları ve sorgu sınırları |

Bunlar yerel metadata'dır; okunmaları dış API çağırmaz ve **canlı kaynak sağlığını
kanıtlamaz**. Asıl güncellik ve kaynak hataları tool sonuçlarından okunmalıdır.

İstemci destekliyorsa `prompts/list` / `prompts/get` ile dört Türkçe iş akışı seçilebilir:

- `gunun_ozeti(district?)` — trafik, su ve ulaşım uyarıları.
- `mahalle_ozeti(district, neighborhood?)` — tarihsel mahalle profili ve sınırları.
- `veri_kesfi(query)` — veri seti → şema → sınırlı kayıt sorgusu.
- `yolculuk_plani(origin, destination, line_code?)` — ulaşım bilgisi; rota motoru veya canlı ETA değildir.

Prompt seçmek tool çalıştırmaz; yalnız iş akışı mesajını üretir.
`istanbul_nearby` (eczane dahil), `istanbul_traffic_status`, `istanbul_water_status`,
`istanbul_transit_line` ve `istanbul_transport_disruptions` ayrıca `outputSchema` ve
`structuredContent` sunar. Geriye uyumlu JSON metni ve Python dict dönüşleri korunur.

Protokol ayrıntıları, şema maliyeti ve doğrulama için [MCP arayüzü](docs/mcp-interface.md).

## İstemci Kurulumları

Istanbul MCP uzak bir Streamable HTTP MCP endpoint'i sunar:

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

Aşağıdaki örnekler resmi istemci dokümanlarıyla kontrol edilmiştir. İstemci farklı bir alan adı istiyorsa aynı endpoint'i kullanın; örneğin bazıları `url`, bazıları `serverUrl`, bazıları da CLI üzerinde `--transport http` ister.

### Codex CLI

```bash
codex mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
codex mcp list
```

Manuel `~/.codex/config.toml` örneği:

```toml
[mcp_servers.istanbul]
url = "https://istanbulmcp-production.up.railway.app/mcp/"
```

### Claude Code

```bash
claude mcp add --transport http istanbul https://istanbulmcp-production.up.railway.app/mcp/
claude mcp list
```

JSON yapılandırma örneği:

```json
{
  "mcpServers": {
    "istanbul": {
      "type": "http",
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

### Claude Desktop

Claude Desktop ile kullanım için ücretli abonelik gerekir.

1. Claude Desktop'ı açın.
2. **Settings → Connectors → Add Custom Connector** yolunu izleyin.
3. Bilgileri girin:
   - **Name:** `İstanbul MCP`
   - **URL:** `https://istanbulmcp-production.up.railway.app/mcp/`
4. **Add** butonuna tıklayın.
5. İstanbul MCP araçlarını kullanmaya başlayın.

### Cursor

Global kurulum için `~/.cursor/mcp.json`, proje bazlı kurulum için repo içinde `.cursor/mcp.json` kullanın. Cursor remote MCP sunucuları için `url` alanını destekler:

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

### OpenCode

`opencode.json`:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "istanbul": {
      "type": "remote",
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Kontrol:

```bash
opencode mcp list
```

### Windsurf

Windsurf/Cascade yapılandırması `~/.codeium/windsurf/mcp_config.json` dosyasındadır. HTTP MCP için `serverUrl` veya `url` alanı kullanılabilir:

```json
{
  "mcpServers": {
    "istanbul": {
      "serverUrl": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

### Devin / Devin CLI

Devin CLI, remote HTTP MCP sunucularını `devin mcp` komutlarıyla veya JSON config dosyalarıyla ekleyebilir. Istanbul MCP herkese açık olduğu için API key veya özel header gerekmez:

```bash
devin mcp add istanbul --transport http --url https://istanbulmcp-production.up.railway.app/mcp/
devin mcp list
devin mcp get istanbul
```

Devin CLI config dosyasında (`.devin/config.json`, `.devin/config.local.json` veya `~/.config/devin/config.json`) remote HTTP yapılandırması:

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/",
      "transport": "http"
    }
  }
}
```

Devin uygulamasında veya `serverUrl` isteyen MCP ekranlarında aynı endpoint şu şekilde verilebilir:

```json
{
  "mcpServers": {
    "istanbul": {
      "serverUrl": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Kurumsal Devin çalışma alanlarında MCP sunucuları veya tool kullanımı yönetici politikalarıyla sınırlandırılmış olabilir. Devin tool izni isterse Istanbul MCP araçlarını onaylayın.

### Google Antigravity

Google Antigravity'nin herkese açık resmi sitesinde bu kontrolde MCP için stabil bir JSON şeması veya dosya yolu doğrulanamadı. Antigravity kullanıyorsanız uygulamanın kendi **MCP / raw config** ekranını esas alın.

Uygulamadaki raw config `mcpServers` ve `serverUrl` biçimini istiyorsa şu yapılandırmayı kullanın; ekran farklı alan adı gösteriyorsa Antigravity'nin kendi şemasını takip edin:

```json
{
  "mcpServers": {
    "istanbul": {
      "serverUrl": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Kontrol edilen resmi kaynaklar:

- [Codex MCP dokümanı](https://developers.openai.com/codex/mcp)
- [Claude Code MCP dokümanı](https://code.claude.com/docs/en/mcp)
- [Cursor MCP dokümanı](https://cursor.com/docs/mcp)
- [OpenCode MCP servers dokümanı](https://opencode.ai/docs/mcp-servers/)
- [Windsurf/Cascade MCP dokümanı](https://docs.windsurf.com/windsurf/cascade/mcp.md)
- [Devin CLI MCP dokümanı](https://cli.devin.ai/docs/extensibility/mcp/configuration)
- [Devin MCP dokümanı](https://docs.devin.ai/work-with-devin/devin-mcp)

## HTTP Sağlık Kontrolleri

```bash
curl -fsS https://istanbulmcp-production.up.railway.app/healthz
curl -fsS https://istanbulmcp-production.up.railway.app/readyz
curl -fsS https://istanbulmcp-production.up.railway.app/status
```

`/mcp` path'i `/mcp/` adresine yönlenir. MCP istemci yapılandırmalarında doğrudan `/mcp/` kullanın. MCP işlemleri JSON-RPC POST çağrılarıdır; düz GET isteği genel bir sağlık testi değildir. Liveness/readiness için yukarıdaki HTTP sağlık uçlarını kullanın.

## Cevap Modeli

Araçlar standart envelope döndürür:

- `ok`
- `summary`
- `data`
- `freshness`
- `sources`
- `limits`
- `warnings`
- `next_queries`

Sunucu salt okunur çalışır. Otopark rezervasyonu yapmaz, kamu verisini değiştirmez, acil durum yönlendirmesi vermez ve kaynakta olmayan alanları üretmez.

## Bilinen Sınırlar

- Trafik aracı şehir geneli indeks döndürür; yol bazlı yoğunluk, kaza veya olay detayı sağlamaz.
- Hava kalitesi kaynağı bazı istasyonlarda son okuma zamanı verdiği halde AQI veya concentration değerini boş döndürebilir.
- İETT SOAP servisleri bakım saatlerinde veya kaynak kesintilerinde geçici olarak yanıt vermeyebilir.
- İSKİ canlı kaynakları bazı Railway çıkışlarından zaman aşımına düşebilir. Üretim kurulumu bu trafiği sabit hedefli ve kimlik doğrulamalı Cloudflare Worker relay üzerinden geçirir. Relay, resmi e-Devlet tablolarını ve İSKİ JSON kaynaklarını kullanır; başarılı yanıtları Workers KV'de global olarak paylaşır ve stale-while-revalidate ile yeniler. Relay ve doğrudan kaynaklar kullanılamazsa yalnızca capture zamanı bulunan ve azami yaş sınırını aşmamış snapshot döndürülebilir.
- İSKİ arıza mesafeleri adres noktası değil, kaynak geometrinin yaklaşık merkezi üzerinden hesaplanır.
- Tam rota planlama, gerçek zamanlı varış tahmini ve harita UI bu sürümün kapsamı dışındadır.
- Kütüphane gibi bazı kayıtlar koordinat değil adres içerir; bu durumda kesin koordinat yerine harita arama linki döner.
- Tüm İBB veri setleri normalize edilmez; katalog araması geniş, özel araçlar ise MVP kapsamındaki alanlara odaklıdır.

## Geliştirme

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
python -m pip check
pytest
# SDK/protokol, yerel discovery ve output schema sözleşmeleri
pytest tests/test_mcp_protocol.py tests/test_mcp_discovery.py tests/test_mcp_structured.py
# İsteğe bağlı anahtarlı mod; değeri terminale yazdırmadan üretin:
export MCP_API_KEYS="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# 20 soru × fresh/stale/broken × compact/legacy dispatch ve envelope sözleşmesi
pytest tests/test_tool_evals.py
# Tool tanımları, output schema ek maliyeti ve resource/prompt sayıları (byte, token değil)
python -m scripts.eval_tools
# GTFS kaynak/CSV/byte-row-timeout/stale ve gerçek registry regresyonları (offline)
pytest tests/test_gtfs.py tests/test_gtfs_regression.py tests/test_city_service.py tests/test_ckan_bounded.py
# SQL güvenlik/tamlık ve bounded HTTP testleri
pytest tests/test_guarded_sql.py tests/test_datastore_sql.py tests/test_ckan_bounded.py
# Dış kaynağa bağlanmadan gerçek yerel süreç + auth/kota/restart smoke testi
python -m scripts.smoke_mcp
python -m app.main
```

Minimum Python sürümünü temiz ortamda doğrulamak için (opsiyonel `uv`):

```bash
uv run --isolated --no-project --python 3.11 --with-editable '.[dev]' python -m pytest
```

Container kurulumunu doğrulamak için:

```bash
docker build -t istanbul-mcp:local .
```

Katman A'nın Python 3.11/3.12, gerçek süreç ve container doğrulama sonuçları
[MCP arayüzü belgesinde](docs/mcp-interface.md#6-doğrulama) kayıtlıdır.

Lokal server şunları sunar:

- `GET /healthz`
- `GET /readyz`
- `GET /status`
- `POST /mcp/`

Canlı MCP regresyon testleri opt-in çalışır:

```bash
RUN_LIVE_MCP_TESTS=1 pytest tests/live
python scripts/live_mcp_uat.py
# Ayrı opt-in: yerel ASGI MCP + gerçek GTFS kaynağı; geçici DB, deploy yok
RUN_LIVE_GTFS_TESTS=1 pytest -s tests/live/test_gtfs_source_live.py
```

## Konfigürasyon

Önemli önbellek TTL değişkenleri:

- `CKAN_CATALOG_CACHE_TTL_SECONDS`
- `CKAN_RESOURCE_CACHE_TTL_SECONDS`
- `IETT_LINE_CACHE_TTL_SECONDS`
- `IETT_STOPS_CACHE_TTL_SECONDS`
- `GTFS_STOPS_MAX_BYTES` (5 MiB), `GTFS_STOPS_MAX_ROWS` (50.000), `GTFS_STOPS_LOAD_TIMEOUT_SECONDS` (20)
- `GTFS_STOPS_CACHE_TTL_SECONDS` (86.400) ve `GTFS_STOPS_STALE_IF_ERROR_SECONDS` (604.800; 0 kapatır) — [sınırlar ve tazelik](docs/gtfs-stops.md)
- `SOURCE_CACHE_MAX_ENTRIES`
- `AIR_QUALITY_RATE_CAPACITY`
- `AIR_QUALITY_RATE_REFILL_PER_SECOND`
- `AIR_QUALITY_RATE_MAX_WAIT_SECONDS`
- `ISKI_FAULTS_CACHE_TTL_SECONDS`
- `ISKI_DAMS_CACHE_TTL_SECONDS`
- `ISKI_FAULTS_STALE_IF_ERROR_SECONDS`
- `ISKI_DAMS_STALE_IF_ERROR_SECONDS`
- `IBB_PHARMACY_BASE_URL` (canonical default: `https://cbsproxy.ibb.gov.tr/?eczanews`)
- `IBB_PHARMACY_REQUEST_TIMEOUT_SECONDS`, `IBB_PHARMACY_REQUEST_ATTEMPTS`
- `IBB_PHARMACY_CACHE_TTL_SECONDS` (300) and `IBB_PHARMACY_MAX_CACHE_AGE_SECONDS` (1800)
- `IBB_PHARMACY_STALE_IF_ERROR_SECONDS` and `IBB_PHARMACY_RATE_*`
- `MARMARAY_API_BASIC_TOKEN`
- `FERRY_SCHEDULES_ENABLED` — varsayılan `false`; yalnızca deploy ortamından tarife erişimi doğrulandıktan sonra açın. Mevcut iptal-duyurusu relay'i tarife desteği sağlamaz.
- `SEHIR_HATLARI_RELAY_URL`
- `SEHIR_HATLARI_RELAY_TOKEN`

Herkese açık MCP koruma limitleri:

- `CKAN_SQL_ALLOWED_RESOURCE_IDS` — SQL için operatör allowlist'i; varsayılan boş. Boyut/süre/satır ayarları ve hard cap'ler [SQL rehberinde](docs/datastore-sql.md).
- `MCP_AUTH_REQUIRED` — varsayılan `false` (public mod). `true` yaparsanız anahtar zorunlu olur ve anahtarsız sunucu başlamaz.
- `MCP_API_KEYS` — virgülle ayrılmış rastgele Bearer anahtarları; doldurulduğunda doğrulama tek başına etkinleşir.
- `MCP_API_KEY_DAILY_QUOTA` — auth etkinken anahtar başına UTC günlük kota; varsayılan `10000`, SQLite ile kalıcı.
- `FORWARDED_ALLOW_IPS` — istemci IP'sinin okunacağı güvenilir proxy'ler; imajda `*`, dışarıdan çalıştırırken varsayılan `127.0.0.1`.
- `MCP_LEGACY_TOOLS_ENABLED` — eski araç adlarını ayrıca yayımlar; varsayılan `false`.
- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`

İSKİ kaynak erişimi ve fallback değişkenleri:

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

Örnek ortam değişkenleri için [.env.example](.env.example) dosyasına bakın.

## Dağıtım

Üretim ortamındaki servis Railway üzerinde çalışır. Railway dağıtım notları için [docs/deploy-railway.md](docs/deploy-railway.md) dosyasına bakın.

Temel komutlar:

```bash
railway status
railway config plan --detailed-exit-code
```

Merge sonrası yerel testler ve `railway config plan --detailed-exit-code` başarılıysa kontrollü deploy için `railway up --detach --yes` kullanılabilir. `railway config apply` ayrı altyapı değişiklikleri için ayrıca onay gerektirir; geçiş ve geri alma sınırı için [docs/deploy-railway.md](docs/deploy-railway.md) dosyasına bakın.

## Proje Planı

Proje bağlamı, roadmap ve GSD faz çıktıları `.planning/` altında tutulur.
