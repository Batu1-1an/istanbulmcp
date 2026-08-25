# Istanbul MCP

## İçindekiler

- [Başlangıç](#hızlı-başlangıç)
- [Kullanım](#ne-yapabilir)
- [Kurulum](#i̇stemci-kurulumları)
- [Geliştirme](#geliştirme)
- [Dağıtım](#dağıtım)

---

Istanbul MCP, İstanbul'a dair açık verileri MCP destekleyen yapay zekâ araçları, geliştirici ortamları ve ajan tabanlı iş akışları için erişilebilir hale getiren uzak bir Model Context Protocol sunucusudur.

Herkese açık endpoint:

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

## Neden Var?

İstanbul'da otopark, ulaşım, trafik, su kesintisi, baraj doluluğu, kütüphane, WiFi, müze, mahalle profili ve açık veri gibi konularda çok sayıda kamusal veri var. Bu veriler portallarda ve farklı servislerde duruyor; ancak yapay zekâ destekli araçlar veya ajanlar içinden doğrudan kullanmak çoğu zaman pratik değil.

Istanbul MCP bu boşluğu kapatır. Codex, Claude, Cursor, OpenCode, Windsurf, Antigravity gibi araçlar veya MCP destekleyen farklı ajan sistemleri tek bir endpoint üzerinden İstanbul verisiyle çalışabilir.

Kullanım alanı yalnızca sohbet arayüzleri değildir. Kod yazan bir ajan, araştırma yapan bir iş akışı, veri analizi çıkaran bir sistem veya kendi otomasyonunuz da aynı endpoint'i kullanabilir.

## Hızlı Başlangıç

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
- İBB WiFi, kütüphane, hava kalitesi ve mahalle profili kaynakları

Tüm araç sonuçları standart bir cevap modeliyle döner: `summary`, `data`, `freshness`, `sources`, `limits`, `warnings` ve gerektiğinde `next_queries`.

## MCP Araçları

Sunucu 24 salt okunur MCP aracı sağlar:

```text
istanbul_health
istanbul_search_datasets
istanbul_get_dataset
istanbul_get_resource_schema
istanbul_query_resource
istanbul_nearby
istanbul_bbox_search
istanbul_parking_nearby
istanbul_parking_by_district
istanbul_metro_stations_nearby
istanbul_air_quality_nearby
istanbul_traffic_status
istanbul_iski_active_faults
istanbul_iski_fault_by_number
istanbul_iski_nearby_faults
istanbul_iski_dam_occupancy
istanbul_mobility_nearby
istanbul_city_services_nearby
istanbul_neighborhood_profile
istanbul_transit_line_info
istanbul_stops_for_line
istanbul_transit_disruptions
istanbul_transport_disruptions
istanbul_planned_departures
```

| Araç | Ne işe yarar? | Örnek soru |
|------|---------------|------------|
| `istanbul_health` | Servis ve lokal SQLite hazırlık durumunu kontrol eder. | "Servis sağlıklı mı?" |
| `istanbul_search_datasets` | İBB Açık Veri kataloğunda konuya göre veri seti arar. | "Müzelerle ilgili hangi veri setleri var?" |
| `istanbul_get_dataset` | Belirli bir veri setinin metadata ve resource bilgilerini getirir. | "Bu dataset içinde hangi kaynaklar var?" |
| `istanbul_get_resource_schema` | Bir CKAN DataStore resource'unun alan/kolon şemasını döndürür. | "Bu resource hangi alanları içeriyor?" |
| `istanbul_query_resource` | Seçili CKAN DataStore resource'unu filtre ve limitlerle sorgular. | "Bu resource'tan 5 örnek kayıt getir." |
| `istanbul_nearby` | Koordinata yakın şehir noktalarını tür, mesafe ve harita linkiyle bulur. | "Bu konumun yakınında hangi şehir noktaları var?" |
| `istanbul_bbox_search` | Verilen harita kutusu içinde kalan şehir noktalarını arar. | "Kadıköy çevresindeki WiFi noktalarını bul." |
| `istanbul_parking_nearby` | Koordinata yakın İSPARK otoparklarını kapasite, boş yer ve harita linkiyle listeler. | "Taksim yakınındaki otoparkları göster." |
| `istanbul_parking_by_district` | İlçedeki İSPARK otoparklarını mesafe uydurmadan listeler. | "Başakşehir'de hangi otoparklar var?" |
| `istanbul_metro_stations_nearby` | Koordinata yakın Metro İstanbul istasyonlarını hat bilgisiyle getirir. | "Levent yakınındaki metro istasyonları hangileri?" |
| `istanbul_air_quality_nearby` | Koordinata yakın hava kalitesi istasyonlarını ve varsa son okumaları döndürür. | "Kadıköy çevresindeki hava kalitesi istasyonları nerede?" |
| `istanbul_traffic_status` | İstanbul geneli trafik yoğunluğu indeksini döndürür. | "İstanbul trafik yoğunluğu şu an hangi seviyede?" |
| `istanbul_iski_active_faults` | Aktif İSKİ su arızalarını listeler; ilçe filtresi ve limit destekler. | "Şişli'de aktif su kesintisi var mı?" |
| `istanbul_iski_fault_by_number` | Aktif İSKİ arızasını arıza numarasıyla bulur. | "10000511943 numaralı İSKİ arızasının detayını göster." |
| `istanbul_iski_nearby_faults` | Koordinata yakın aktif İSKİ arızalarını yaklaşık geometri merkezine göre sıralar. | "Taksim'e yakın aktif su arızaları var mı?" |
| `istanbul_iski_dam_occupancy` | İSKİ baraj doluluk kayıtlarını döndürür; baraj adı ve minimum doluluk filtresi destekler. | "Baraj doluluk oranları şu an nasıl?" |
| `istanbul_mobility_nearby` | Bilinen yer veya koordinat için otopark, metro, durak, hava kalitesi ve trafik özetini verir. | "Kadıköy Rıhtım çevresinde ulaşım seçenekleri neler?" |
| `istanbul_city_services_nearby` | Yakındaki WiFi noktalarını ve ilçe düzeyindeki kütüphane bilgilerini getirir. | "Beşiktaş'ta hangi kütüphaneler var?" |
| `istanbul_neighborhood_profile` | Mahalle profilini sosyal yardım, bina stoku ve deprem senaryosu verileriyle oluşturur. | "Kadıköy Caferağa mahalle profili nedir?" |
| `istanbul_transit_line_info` | İETT hat adı, tarife, uzunluk ve tahmini süre gibi temel hat bilgilerini getirir. | "500T hattının bilgileri nedir?" |
| `istanbul_stops_for_line` | İETT hattının duraklarını yönlerine göre sıralı ve harita linkleriyle döndürür. | "500T hattı hangi duraklardan geçiyor?" |
| `istanbul_transit_disruptions` | Güncel İETT duyurularını listeler; isteğe bağlı tam hat kodu filtresi ve limit destekler. | "34A için güncel bir duyuru var mı?" |
| `istanbul_transport_disruptions` | İETT, Metro İstanbul, Şehir Hatları ve Marmaray'ın doğrulanmış resmî arıza/sefer duyurularını tek sonuçta birleştirir; ulaşım türü, işletme, hat etiketi ve limit filtresi destekler. | "Metro ve vapurlarda güncel aksaklık var mı?" |
| `istanbul_planned_departures` | Bir hattın planlanan ana durak kalkışlarını gün ve yön bilgisiyle listeler. Bu veri ara durak ETA'sı değildir. | "34A'nın bugün planlanan kalkışları neler?" |

`istanbul_transport_disruptions` yalnızca dört doğrulanmış resmî kapsamı kontrol eder: İETT ve Metro İstanbul canlı hizmet durumları; Şehir Hatları iptal seferleri; Marmaray resmî son dakika duyuruları. `mode`, `operator`, `line` ve `limit` isteğe bağlıdır. `line`, `line_code` veya `route_label` üzerinde büyük/küçük harften bağımsız tam eşleşir. Kaynaklar 120 saniye önbelleklenir; kısmi kaynak hataları `sources[].coverage_status=unavailable`, `freshness=unknown` ve `warnings` ile görünür. İDO, Turyol, Dentur, minibüs ve taksi-dolmuş canlı kapsama dahil değildir ve cevap `limits[]` içinde belirtilir. Metro ekipman arızası, rota motoru, ETA ve GTFS `stop_times` arşivi bu aracın kapsamı değildir.

Parametreler, davranışlar ve sınırlar için [docs/tool-reference.md](docs/tool-reference.md) dosyasına bakın.

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
curl -i --max-time 5 -H "Accept: application/json, text/event-stream" https://istanbulmcp-production.up.railway.app/mcp/
```

`/mcp` path'i `/mcp/` adresine yönlenir. MCP istemci yapılandırmalarında doğrudan `/mcp/` kullanın. MCP GET çağrısı stream açar; `200` ve `content-type: text/event-stream` görmek yeterlidir.

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
pytest
python -m app.main
```

Lokal server şunları sunar:

- `GET /healthz`
- `GET /readyz`
- `GET /status`
- `POST /mcp/`

Canlı MCP regresyon testleri opt-in çalışır:

```bash
RUN_LIVE_MCP_TESTS=1 pytest tests/live
python scripts/live_mcp_uat.py
```

## Konfigürasyon

Önemli önbellek TTL değişkenleri:

- `CKAN_CATALOG_CACHE_TTL_SECONDS`
- `CKAN_RESOURCE_CACHE_TTL_SECONDS`
- `IETT_LINE_CACHE_TTL_SECONDS`
- `IETT_STOPS_CACHE_TTL_SECONDS`
- `SOURCE_CACHE_MAX_ENTRIES`
- `AIR_QUALITY_RATE_CAPACITY`
- `AIR_QUALITY_RATE_REFILL_PER_SECOND`
- `AIR_QUALITY_RATE_MAX_WAIT_SECONDS`
- `ISKI_FAULTS_CACHE_TTL_SECONDS`
- `ISKI_DAMS_CACHE_TTL_SECONDS`
- `ISKI_FAULTS_STALE_IF_ERROR_SECONDS`
- `ISKI_DAMS_STALE_IF_ERROR_SECONDS`

Herkese açık MCP koruma limitleri:

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
