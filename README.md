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

İstanbul'da otopark, ulaşım, trafik, kütüphane, WiFi, müze, mahalle profili ve açık veri gibi konularda çok sayıda kamusal veri var. Bu veriler portallarda ve farklı servislerde duruyor; ancak yapay zekâ destekli araçlar veya ajanlar içinden doğrudan kullanmak çoğu zaman pratik değil.

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

Sonra yeni bir oturum açıp örnek bir soru sorun:

```text
Taksim'e arabayla gideceğim. Yakındaki otoparkları boş kapasite, çalışma saati ve harita linkiyle göster.
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
Taksim'e arabayla gideceğim. Yakındaki otoparkları boş kapasite, çalışma saati ve harita linkiyle göster.
Levent yakınındaki metro istasyonları hangileri? Hat bilgisi ve harita linkleriyle listele.
500T hattı hangi duraklardan geçiyor? Durakları yönlerine göre sıralı ve harita linkleriyle göster.
İstanbul trafik yoğunluğu şu an hangi seviyede?
İBB açık veri kataloğunda müzelerle ilgili hangi veri setleri var?
Beşiktaş'ta hangi kütüphaneler var?
Kadıköy Rıhtım çevresinde ulaşım seçenekleri neler?
Kadıköy Caferağa mahalle profili nedir?
```

## Örnek Çıktılar

Taksim yakınındaki otopark sorusu; otopark adı, mesafe, kapasite, boş kapasite, çalışma saati, açık/kapalı durumu ve Google Maps linki döndürür.

500T hat sorusu; hat adı, tarife, hat uzunluğu, tahmini yolculuk süresi ve iki yöndeki durakları sıra numarasıyla döndürür.

Trafik sorusu; şehir geneli trafik indeksini, ölçüm zamanını ve bu kaynağın yol bazlı kaza/olay detayı sağlamadığını belirten sınır bilgisini döndürür.

## Veri Kaynakları

Istanbul MCP şu kaynaklardan gelen verileri kullanır:

- İBB Açık Veri Portalı (`data.ibb.gov.tr`)
- İBB City APIs (`api.ibb.gov.tr`)
- İSPARK otopark servisleri
- Metro İstanbul istasyon verileri
- İETT SOAP servisleri
- İBB WiFi, kütüphane, hava kalitesi ve mahalle profili kaynakları

Tüm araç sonuçları standart bir cevap modeliyle döner: `summary`, `data`, `freshness`, `sources`, `limits`, `warnings` ve gerektiğinde `next_queries`.

## MCP Araçları

Sunucu salt okunur MCP araçları sağlar:

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
istanbul_mobility_nearby
istanbul_city_services_nearby
istanbul_neighborhood_profile
istanbul_transit_line_info
istanbul_stops_for_line
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
| `istanbul_mobility_nearby` | Bilinen yer veya koordinat için otopark, metro, durak, hava kalitesi ve trafik özetini verir. | "Kadıköy Rıhtım çevresinde ulaşım seçenekleri neler?" |
| `istanbul_city_services_nearby` | Yakındaki WiFi noktalarını ve ilçe düzeyindeki kütüphane bilgilerini getirir. | "Beşiktaş'ta hangi kütüphaneler var?" |
| `istanbul_neighborhood_profile` | Mahalle profilini sosyal yardım, bina stoku ve deprem senaryosu verileriyle oluşturur. | "Kadıköy Caferağa mahalle profili nedir?" |
| `istanbul_transit_line_info` | İETT hat adı, tarife, uzunluk ve tahmini süre gibi temel hat bilgilerini getirir. | "500T hattının bilgileri nedir?" |
| `istanbul_stops_for_line` | İETT hattının duraklarını yönlerine göre sıralı ve harita linkleriyle döndürür. | "500T hattı hangi duraklardan geçiyor?" |

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

Herkese açık MCP koruma limitleri:

- `MCP_MAX_BODY_BYTES`
- `MCP_RATE_LIMIT_CAPACITY`
- `MCP_RATE_LIMIT_REFILL_PER_SECOND`
- `MCP_RATE_LIMIT_MAX_CLIENTS`
- `MCP_MAX_CONCURRENT_REQUESTS`

Örnek ortam değişkenleri için [.env.example](.env.example) dosyasına bakın.

## Dağıtım

Üretim ortamındaki servis Railway üzerinde çalışır. Railway dağıtım notları için [docs/deploy-railway.md](docs/deploy-railway.md) dosyasına bakın.

Temel komutlar:

```bash
railway status
railway up
```

## Proje Planı

Proje bağlamı, roadmap ve GSD faz çıktıları `.planning/` altında tutulur.
