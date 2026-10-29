# Istanbul MCP

Istanbul MCP, İstanbul'a dair açık verileri Claude, ChatGPT, Codex, Cursor gibi MCP destekleyen yapay zekâ araçlarına bağlayan, salt okunur ve uzak bir Model Context Protocol sunucusudur.

```text
https://istanbulmcp-production.up.railway.app/mcp/
```

## İçindekiler

- [Kurulum](#kurulum)
- [Ne yapabilir?](#ne-yapabilir)
- [Örnek sorular](#örnek-sorular)
- [MCP araçları](#mcp-araçları)
- [Bilinen sınırlar](#bilinen-sınırlar)
- [Geliştirme](#geliştirme)
- [Lisans](#lisans-ve-sorumluluk-reddi)

## Neden Var?

İstanbul'da otopark, ulaşım, trafik, su kesintisi, baraj doluluğu, nöbetçi eczane, kütüphane ve mahalle profili gibi konularda çok sayıda kamusal veri var. Bu veriler farklı portallarda ve servislerde duruyor; yapay zekâ araçları veya ajanlar içinden doğrudan kullanmak çoğu zaman pratik değil.

Istanbul MCP bu boşluğu kapatır: MCP destekleyen her sohbet uygulaması, kod yazan ajan, araştırma iş akışı veya kendi otomasyonunuz tek bir endpoint üzerinden İstanbul verisiyle çalışabilir.

## Kurulum

Kurulum anahtar gerektirmez: endpoint'i istemcinize ekleyin, çalışır. İstemci başına hız sınırı uygulanır; isteğe bağlı anahtar ve kota için [erişim rehberine](docs/api-access.md) bakın.

Endpoint'i sondaki `/mcp/` ile kullanın. Genel yapılandırma:

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbulmcp-production.up.railway.app/mcp/"
    }
  }
}
```

Bazı istemciler `url` yerine `serverUrl` ya da ek olarak `"type": "http"`, `"type": "remote"` veya `"transport": "http"` ister. Kendi istemcinizin MCP ekranını esas alın.

### Codex CLI

```bash
codex mcp add istanbul --url https://istanbulmcp-production.up.railway.app/mcp/
codex mcp list
```

Manuel yapılandırma için `~/.codex/config.toml` dosyasına `[mcp_servers.istanbul]` başlığı altında `url = "https://istanbulmcp-production.up.railway.app/mcp/"` ekleyin.

### Claude Code

```bash
claude mcp add --transport http istanbul https://istanbulmcp-production.up.railway.app/mcp/
claude mcp list
```

### Claude Desktop ve Claude.ai

Claude Desktop ile kullanım için ücretli abonelik gerekir.

1. **Settings → Connectors → Add custom connector** yolunu izleyin.
2. **Name:** `İstanbul MCP`, **URL:** `https://istanbulmcp-production.up.railway.app/mcp/`
3. **Add** butonuna tıklayın.

### ChatGPT

ChatGPT'de salt okunur custom MCP sunucusu **Plus, Pro, Business, Enterprise ve Edu**
planlarında kullanılabilir; Free planda yoktur. Business, Enterprise ve Edu
çalışma alanlarında yönetici izni gerekebilir. Kurulum için web veya desktop
uygulamasını kullanın.

Business, Enterprise ve Edu için güncel **Plugins** ekranı Developer mode
gerektirmez. Plus veya Pro kullanıyorsanız Developer mode gerekebilir:

1. [ChatGPT Plugins](https://chatgpt.com/plugins) sayfasını açın. Bazı hesaplarda bu ekran **Settings → Apps & Connectors** altındadır.
2. **+** düğmesine, ardından **Add custom MCP server** seçeneğine tıklayın.
3. Bilgileri girin:
   - **Name:** `İstanbul MCP`
   - **Description:** isteğe bağlı
   - **Connection → Server URL:** `https://istanbulmcp-production.up.railway.app/mcp/`
4. **Authentication:** `No authentication` seçin. Sunucu public modda anahtarsız çalışır.
5. Risk uyarısını okuyun, **I understand and want to continue** kutusunu işaretleyin ve **Create as a plugin** düğmesine tıklayın.
6. Keşfedilen araçları ve metadata'yı kontrol edin. Plugin'i kurun.
7. Yeni bir sohbet açın, istem kutusuna `@` yazın ve `İstanbul MCP` plugin'ini seçin. Sonra soruyu sorun.

Notlar:

- Tüm Istanbul MCP araçları salt okunurdur ve `readOnlyHint` taşır.
- `MCP_API_KEYS` veya `MCP_AUTH_REQUIRED=true` açıksa ChatGPT web bağlanamaz. Bu ekran statik Bearer anahtarı kabul etmez; sunucuda OAuth desteği yoktur. Public modu kullanın.
- Araç listesi değiştiğinde plugin ayarlarından araçları yenileyin.
- Business, Enterprise ve Edu planlarında yönetici **Create plugins with MCPs** iznini vermeli ve plugin'i yayımlamalıdır.
- **Add custom MCP server** seçeneği görünmüyorsa **Settings → Apps → Advanced settings** yolundan Developer mode'u açın. Plus ve Pro planlarında bu adım gerekebilir.

ChatGPT desktop uygulaması ayrı bir MCP yolu sunar:

1. **Settings → MCP servers → Add server** yolunu izleyin.
2. **Streamable HTTP** seçin ve URL olarak aynı endpoint'i girin.
3. Kaydedin ve **Restart** seçin. İstem kutusunda `/mcp` ile bağlantıyı kontrol edin.

### Cursor

Global kurulum için `~/.cursor/mcp.json`, proje bazlı kurulum için `.cursor/mcp.json` dosyasına genel yapılandırmayı ekleyin.

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

### Windsurf

`~/.codeium/windsurf/mcp_config.json` dosyasında genel yapılandırmayı kullanın; Windsurf `url` yanında `serverUrl` alanını da kabul eder.

### Devin CLI

```bash
devin mcp add istanbul --transport http --url https://istanbulmcp-production.up.railway.app/mcp/
devin mcp list
```

Config dosyası kullanıyorsanız (`.devin/config.json`, `.devin/config.local.json` veya `~/.config/devin/config.json`) genel yapılandırmaya `"transport": "http"` ekleyin.

Kontrol edilen resmî kaynaklar:
[Codex](https://developers.openai.com/codex/mcp) ·
[ChatGPT custom MCP](https://developers.openai.com/api/docs/guides/custom-mcp-server) ·
[ChatGPT MCP](https://learn.chatgpt.com/docs/extend/mcp) ·
[ChatGPT bağlantıları](https://help.openai.com/en/articles/12584461-connecting-custom-mcp-servers-in-chatgpt) ·
[Claude Code](https://code.claude.com/docs/en/mcp) ·
[Cursor](https://cursor.com/docs/mcp) ·
[OpenCode](https://opencode.ai/docs/mcp-servers/) ·
[Windsurf](https://docs.windsurf.com/windsurf/cascade/mcp.md) ·
[Devin CLI](https://cli.devin.ai/docs/extensibility/mcp/configuration) ·
[Devin](https://docs.devin.ai/work-with-devin/devin-mcp)

### İlk soru

Kurulumdan sonra yeni bir oturum açıp deneyin:

```text
Taksim'e arabayla gideceğim. Yakındaki otoparkların boş yer sayısını, çalışma saatini ve haritadaki yerlerini gösterir misin?
```

## Ne Yapabilir?

**Ulaşım**

- İETT hat bilgisi, yönlerine göre sıralı duraklar ve ana duraktan planlı kalkış saatleri.
- Durak adıyla arama ve seçilen duraktan geçen hatların tarifeli kalkışları (İETT GTFS).
- İETT, Metro İstanbul, Şehir Hatları ve Marmaray'ın güncel aksaklık ve duyuruları.
- Metro İstanbul asansör, yürüyen merdiven ve diğer ekipmanların çalışma ve arıza durumu.
- Yakındaki metro istasyonları ve toplu taşıma durakları; `Kadıköy Rıhtım`, `Taksim`, `Levent` gibi yerler için ulaşım özeti.
- Şehir geneli trafik yoğunluğu indeksi.

**Şehir hizmetleri**

- Konuma veya ilçeye göre nöbetçi eczaneler: adres, telefon ve harita linki.
- İSPARK otoparkları: kapasite, boş yer, açık/kapalı durumu ve çalışma saati.
- İstanbulkart dolum merkezleri ve İBB sosyal tesisleri.
- WiFi noktaları, kütüphaneler ve kültür merkezleri.
- EV şarj istasyonları, taksi durakları ve ilçe ile güne göre haftalık semt pazarları.
- Yakındaki hava kalitesi ölçümleri.

**Su**

- Aktif İSKİ su arızaları (ilçe, arıza numarası veya konuma göre) ve baraj doluluk oranları.

**Mahalle ve açık veri**

- Sosyal yardım, bina stoku ve deprem senaryosu verileriyle mahalle profili.
- İBB Açık Veri kataloğunda veri seti arama, şema inceleme ve güvenli filtrelerle kayıt sorgulama.

Koordinatı olan kayıtlarda harita linki (`maps_url`) döner. Yalnız adresi bilinen kayıtlarda adres araması linki (`maps_search_url`) verilir; bu kayıtlar kesin konum gibi sunulmaz.

## Örnek Sorular

```text
Üsküdar'da şu an nöbetçi eczane var mı?
Kadıköy'deki duraklardan bir sonraki planlı otobüs kalkışları ne zaman?
500T hattı hangi duraklardan geçiyor? Durakları yönlerine göre sıralı göster.
Bugün Marmaray'da veya metroda aksaklık var mı?
Taksim metro istasyonunda arızalı asansör veya yürüyen merdiven var mı?
Şişli civarında aktif su kesintisi veya İSKİ arızası var mı?
Baraj doluluk oranları şu an nasıl? En dolu 5 barajı listele.
Kadıköy'de yarın hangi pazar kuruluyor?
Levent yakınındaki EV şarj istasyonlarını listele.
Beşiktaş iskelesine en yakın İstanbulkart dolum noktası nerede?
Kadıköy Caferağa mahalle profili nedir?
İstanbul trafik yoğunluğu şu an hangi seviyede?
İBB açık veri kataloğunda müzelerle ilgili hangi veri setleri var?
```

## Veri Kaynakları

- İBB Açık Veri Portalı (`data.ibb.gov.tr`): katalog, İETT GTFS tarifesi, İstanbulkart, pazar, EV şarj, taksi durağı, kültür merkezi ve mahalle verileri
- İBB şehir API'leri (`api.ibb.gov.tr`): İSPARK, trafik, hava kalitesi, Metro İstanbul ve İETT
- İBB Şehir Haritası nöbetçi eczane listesi ve İBB Sosyal Tesisler kataloğu
- Metro İstanbul arıza ve duyuru sayfaları
- İSKİ arıza ve baraj kaynakları
- Şehir Hatları ve TCDD Taşımacılık (Marmaray) resmî duyuruları
- Wikidata yer referansları (CC0)

Her sonuç standart bir yapıyla döner: `ok`, `summary`, `data`, `freshness`, `sources`, `limits`, `warnings` ve gerektiğinde `next_queries`. Sunucu salt okunurdur: rezervasyon yapmaz, kamu verisini değiştirmez, acil durum yönlendirmesi vermez ve kaynakta olmayan alanları üretmez.

## MCP Araçları

Production yüzeyi **18 salt okunur araçtır**: aşağıdaki 16 araç ve GTFS tarifesi açıkken eklenen 2 araç. Daha önce yayımlanmış araç adları listede görünmese de çağrılabilir kalır; eski → yeni karşılıklar için [geçiş tablosuna](docs/tool-migration.md) bakın.

| Araç | İşlev |
|---|---|
| `istanbul_health` | Servis hazırlığı. |
| `istanbul_search_datasets` | Konuya göre İBB katalog araması. |
| `istanbul_get_dataset` | Veri seti metadata'sı ve kaynakları. |
| `istanbul_get_resource_schema` | Resource kolonları. |
| `istanbul_query_resource` | CKAN kayıtlarını güvenli filtre ve limitle getirir. |
| `istanbul_datastore_query` | Operatörün izin verdiği resource'larda sınırlı SQL; izin listesi varsayılan boştur. [SQL rehberi](docs/datastore-sql.md) |
| `istanbul_nearby` | Otopark, nöbetçi eczane, İstanbulkart, sosyal tesis, metro istasyonu, hava kalitesi, su arızası ve şehir katmanları için konum, ilçe veya harita alanı araması. |
| `istanbul_market_schedule` | İlçe ve güne göre haftalık pazar takvimi; canlı açılış durumu değildir. |
| `istanbul_traffic_status` | Şehir geneli trafik indeksi; yol bazlı değildir. |
| `istanbul_water_status` | İSKİ arızaları (ilçe veya arıza numarası) ve baraj dolulukları. |
| `istanbul_mobility_nearby` | Yer veya koordinat için ulaşım özeti; 39 ilçede ilçe geneli otopark listesi. |
| `istanbul_city_services_nearby` | Nokta çevresinde WiFi; 39 ilçede kütüphane ve kültür merkezi adresleri. |
| `istanbul_neighborhood_profile` | Sosyal yardım, bina stoku ve deprem **senaryosu**; anlık risk değildir. |
| `istanbul_transit_line` | İETT hat bilgisi, durakları ve ana duraktan planlı kalkışlar; ETA değildir. |
| `istanbul_transport_disruptions` | İETT, Metro İstanbul, Şehir Hatları ve Marmaray aksaklık ve duyuruları. |
| `istanbul_metro_accessibility_status` | Metro ekipman toplamları ve arıza ayrıntıları; yolculuk erişilebilirliği garantisi değildir. |
| `istanbul_next_departures` | Durak adı arama veya seçilen durağın planlı GTFS kalkışları; canlı ETA değildir. |
| `istanbul_gtfs_snapshot_status` | Yerel tarife verisinin yaşı ve takvim geçerliliği. |

Sunucu hem eski (`initialize`) hem yeni (`2026-07-28`, `server/discover`) MCP protokolüyle çalışır. Ayrıca üç bilgi kaynağı (`istanbul://coverage`, `istanbul://sources`, `istanbul://schema/catalog`) ve dört Türkçe prompt (`gunun_ozeti`, `mahalle_ozeti`, `veri_kesfi`, `yolculuk_plani`) sunar.

Parametreler ve davranışlar: [araç referansı](docs/tool-reference.md) · Protokol, prompt ve output schema ayrıntıları: [MCP arayüzü](docs/mcp-interface.md) · Durak ve tarife: [GTFS durakları](docs/gtfs-stops.md), [GTFS planlı kalkışlar](docs/gtfs-schedule.md) · [Yer ve ilçe çözümleme](docs/place-resolution.md) · [Statik şehir katmanları](docs/city-static-layers.md) · [Yanıt sözleşmesi](docs/response-contract.md)

## Bilinen Sınırlar

- Trafik aracı şehir geneli indeks döndürür; yol bazlı yoğunluk, kaza veya olay detayı sağlamaz.
- Kalkış saatleri yayımlanmış tarifelerdir; canlı varış tahmini (ETA), gecikme bilgisi veya rota planlama yoktur.
- İstanbulkart, sosyal tesis, EV şarj, taksi durağı ve pazar verileri yayımlanmış konumlardır; canlı açık/kapalı durumu değildir.
- Yer çözümleme 39 ilçe ve seçili statik referans noktalarıyla çalışır; tam sokak/bina adresi çözümlenmez.
- Hava kalitesi kaynağı bazı istasyonlarda son okuma zamanı verdiği halde değeri boş döndürebilir.
- İETT servisleri bakım saatlerinde geçici olarak yanıt vermeyebilir.
- İSKİ arıza mesafeleri adres noktasına değil, arıza alanının yaklaşık merkezine göre hesaplanır.
- Kütüphane gibi bazı kayıtlar yalnız adres içerir; bu durumda harita arama linki döner.
- İBB, Metro İstanbul, İSKİ, Şehir Hatları ve Marmaray kaynakları Türkiye dışından gelen bağlantıları kabul etmediği için üretimde İstanbul'daki bir relay kullanılır. Bir kaynağa erişilemezse sonuç `unavailable` veya `stale` olarak işaretlenir; bu "veri yok" anlamına gelmez. [Ayrıntılar](docs/deploy-railway.md)
- Vapur tarifesi aracı varsayılan olarak kapalıdır. İDO, Turyol, Dentur, minibüs ve taksi-dolmuş kapsam dışıdır.
- Tüm İBB veri setleri normalize edilmez; özel araçlar seçili alanlara odaklanır.

## Geliştirme

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
python -m app.main
docker build -t istanbul-mcp:local .
```

Yerel sunucu `GET /healthz`, `GET /readyz`, `GET /status` ve `POST /mcp/` uçlarını sunar. Odaklı test komutları, conformance ve opt-in canlı testler için [geliştirme rehberine](docs/development.md); ortam değişkenleri için [.env.example](.env.example) dosyasına ve [konfigürasyon](docs/configuration.md) sayfasına bakın.

## Dağıtım ve İzleme

Production servisi Railway üzerinde çalışır ([dağıtım notları](docs/deploy-railway.md)).

```bash
curl -fsS https://istanbulmcp-production.up.railway.app/healthz
curl -fsS https://istanbulmcp-production.up.railway.app/readyz
curl -fsS https://istanbulmcp-production.up.railway.app/status
```

Canlı endpoint 10 dakikada bir otomatik kontrol edilir; ulaşılamazsa repo sahibine issue açılır ([izleme](docs/monitoring.md)). Sunucu [MCP Registry](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.Batu1-1an%2Fistanbul-mcp&version=latest)'de `io.github.Batu1-1an/istanbul-mcp` adıyla yayımlıdır ([yayın rehberi](docs/registry.md)).

[Sürüm geçmişi](CHANGELOG.md) ·
[Veri işleme/gizlilik](docs/privacy.md) ·
[Tarayıcıdan bağlantı](docs/browser-cors.md) ·
[Destek / sorun bildirimi](https://github.com/Batu1-1an/istanbulmcp/issues)

## Lisans ve Sorumluluk Reddi

Kod [MIT Lisansı](LICENSE) ile lisanslanmıştır. Bu lisans yalnızca kodu kapsar; veriler yayıncı kurumlara aittir. İBB Açık Veri Portalı verileri [İBB Açık Veri Lisansı](https://data.ibb.gov.tr/license) ile, diğer kaynaklar kendi kullanım koşullarıyla yayımlanır.

Istanbul MCP resmî olmayan, bağımsız bir projedir; İBB, İSKİ, İETT, Metro İstanbul, Şehir Hatları veya TCDD ile bağlantılı değildir.

Veriler gecikmeli, eksik veya hatalı olabilir. Nöbetçi eczane, su arızası ve ulaşım gibi kritik bilgileri resmî kaynaktan teyit edin.
