# İstanbul MCP — MVP Kapsamı

> **Dosya amacı:** İstanbul MCP için ilk çıkacak ürünün kapsamını netleştirmek.  
> **MVP hedefi:** Claude, ChatGPT, Cursor veya başka bir MCP client içine tek URL eklenerek kullanılabilen; İBB/İstanbul açık verilerini kaynak, tazelik ve limit bilgisiyle döndüren güvenilir bir şehir veri MCP server’ı çıkarmak.  
> **Tarih:** 2026-06-09

---

## 1. MVP’nin tek cümlelik tanımı

**İstanbul MCP MVP**, İBB açık veri kataloğunu arayabilen; yakındaki otopark, bisiklet istasyonu, hava kalitesi noktası, trafik durumu ve temel İETT hat/durak bilgilerini gerçek kaynaklardan çekip AI asistanlara standart MCP tool’ları üzerinden sunan, Railway üzerinde çalışan remote MCP server’dır.

MVP’nin odağı şu olmalı:

```txt
Az tool + yüksek güvenilirlik + net kaynak + veri tazeliği + hızlı demo edilebilir şehir senaryoları
```

MVP’nin odağı şu olmamalı:

```txt
542 veri setinin tamamını tek tek bağlamak, eksiksiz rota planlayıcı yapmak, mobil uygulama çıkarmak veya tüm belediye servislerini aynı anda kapsamak
```

---

## 2. MVP ürün hedefleri

MVP sonunda kullanıcı şunları yapabilmeli:

1. **İstanbul açık veri kataloğunu arayabilmeli.**  
   Örnek: “İBB’de trafik yoğunluğu ile ilgili hangi veri setleri var?”

2. **Bir veri setinin metadata ve kaynak bilgisini görebilmeli.**  
   Örnek: “Bu veri seti ne zaman güncellenmiş, formatı ne?”

3. **Yakındaki şehir servislerini sorgulayabilmeli.**  
   Örnek: “Bu koordinata en yakın İSPARK otoparkları hangileri?”

4. **Basit trafik, otopark, bisiklet ve hava kalitesi sorularına gerçek veriyle cevap alabilmeli.**  
   Örnek: “Kadıköy civarında trafik yoğun mu?”

5. **Temel İETT hat/durak bilgisi alabilmeli.**  
   Örnek: “34A hattının duraklarını göster.”

6. **Her cevabın veri tazeliğini ve kaynağını görebilmeli.**  
   Örnek: “Bu veri 2 dakika önce çekildi; kaynak İBB Açık Veri Portalı.”

---

## 3. MVP kullanıcı senaryoları

### 3.1 Son kullanıcı / şehir asistanı senaryosu

Kullanıcı şehirle ilgili pratik bir soru sorar:

```txt
Kadıköy Moda civarında bisiklet, otopark ve trafik durumu nasıl?
```

MCP şu akışla cevap üretir:

```txt
1. Konum varsa doğrudan kullanır, yoksa ilçe/mahalle yaklaşımı yapar.
2. Yakındaki İsbike istasyonlarını getirir.
3. Yakındaki İSPARK otoparklarını getirir.
4. Bölgesel trafik yoğunluğu bilgisini getirir.
5. Cevaba source + freshness + limitations ekler.
```

### 3.2 Veri keşfi senaryosu

Kullanıcı veri seti arar:

```txt
İstanbul’da otopark verisiyle ilgili hangi açık veri setleri var?
```

MCP şu bilgileri döndürür:

```txt
- Uygun veri setleri
- Formatlar
- Son güncelleme zamanı
- Kaynak linki
- Kullanım limiti veya dikkat edilmesi gereken notlar
```

### 3.3 Toplu taşıma senaryosu

Kullanıcı bir hat veya durak sorar:

```txt
34A hattının duraklarını sırayla göster.
```

MCP şu bilgileri döndürür:

```txt
- Hat adı/kodu
- Durak listesi
- Varsa koordinatlar
- Veri kaynağı
- Veri tazeliği
```

### 3.4 Yakınımdaki servisler senaryosu

Kullanıcı koordinat veya konum verir:

```txt
40.9909, 29.0303 koordinatına 750 metre içindeki otobüs duraklarını, bisiklet istasyonlarını ve otoparkları göster.
```

MCP şu bilgileri döndürür:

```txt
- Mesafeye göre sıralanmış sonuçlar
- Tür: bus_stop, bike_station, parking
- Ad, koordinat, mesafe
- Doluluk/kapasite gibi varsa anlık bilgiler
```

---

## 4. MVP kapsamı — P0 zorunlu özellikler

Aşağıdaki maddeler MVP’ye mutlaka girmeli.

### 4.1 Remote MCP endpoint

MVP public veya private beta olarak remote çalışmalı.

```txt
Endpoint örneği:
https://istanbul-mcp.example.com/mcp
```

Zorunlu endpoint’ler:

```txt
/mcp       -> MCP Streamable HTTP endpoint
/healthz   -> servis ayakta mı?
/readyz    -> database/cache hazır mı?
/metrics   -> basit metrikler, public olmayabilir
```

Minimum beklenti:

```txt
- Claude/Cursor/ChatGPT benzeri MCP client’a URL ile bağlanabilir.
- Server restart sonrası cache bozulmadan ayağa kalkar.
- Hata durumunda anlaşılır hata döner.
```

---

### 4.2 CKAN katalog tarayıcı

İBB açık veri kataloğu düzenli taranmalı ve yerel cache’e alınmalı.

Toplanacak alanlar:

```txt
- dataset id
- slug/name
- title
- description
- organization
- groups/categories
- tags
- license
- resources
- resource format
- resource URL
- datastore aktif mi?
- created_at / modified_at / metadata_modified
- retrieved_at
```

MVP’de yapılacaklar:

```txt
[ ] CKAN package_search entegrasyonu
[ ] Dataset snapshot tablosu
[ ] Resource snapshot tablosu
[ ] Basit format sınıflandırma: API, CSV, XLSX, GeoJSON, KML, GTFS, PDF, ZIP
[ ] Dataset arama için FTS index
```

---

### 4.3 Veri cache ve storage

MVP’de SQLite yeterli.

Zorunlu SQLite özellikleri:

```txt
- WAL mode açık
- FTS5 dataset arama
- RTree veya hesaplanmış index ile geo sorgu
- Raw response snapshot metadata
- TTL/freshness alanları
```

Minimum tablolar:

```sql
datasets
resources
source_endpoints
cache_entries
geo_features
freshness_checks
tool_calls
```

MVP’de Postgres/PostGIS şart değil. Ancak tablo ve repository yapısı ileride PostGIS’e taşınabilecek şekilde yazılmalı.

---

### 4.4 Standart response envelope

Her MCP tool aynı cevap standardını kullanmalı.

```json
{
  "ok": true,
  "summary": "Kısa insan-okur özet.",
  "data": [],
  "geojson": null,
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total_estimate": null
  },
  "freshness": {
    "status": "fresh",
    "retrieved_at": "2026-06-09T15:12:03+03:00",
    "source_updated_at": null,
    "ttl_seconds": 120
  },
  "sources": [
    {
      "name": "İBB Açık Veri Portalı",
      "publisher": "İstanbul Büyükşehir Belediyesi",
      "dataset_id": "",
      "resource_id": "",
      "license": "",
      "url": ""
    }
  ],
  "limits": [],
  "warnings": [],
  "next_queries": []
}
```

Hata cevabı:

```json
{
  "ok": false,
  "error": {
    "code": "SOURCE_UNAVAILABLE",
    "message": "Kaynak şu anda cevap vermiyor.",
    "retryable": true
  },
  "fallback": {
    "used_cache": true,
    "cached_at": "2026-06-09T14:58:00+03:00"
  },
  "sources": []
}
```

---

### 4.5 Freshness sistemi

MVP’nin ayırt edici özelliği “güncel veri” iddiasını ölçülü ve kaynaklı vermesidir.

Freshness durumları:

| Durum | Anlamı | Kullanıcıya nasıl söylenmeli? |
|---|---|---|
| `fresh` | TTL içinde canlı veya yeni veri | “Veri güncel görünüyor.” |
| `stale` | Son veri var ama TTL geçmiş | “Kaynak son çekimde güncellenemedi; cache kullanıldı.” |
| `unknown` | Kaynak güncelleme zamanı vermiyor | “Kaynak güncelleme zamanı sağlamıyor.” |
| `broken` | Kaynak hata veriyor | “Kaynak şu anda cevap vermiyor.” |

TTL önerileri:

| Veri tipi | TTL |
|---|---:|
| Trafik | 30–120 saniye |
| İsbike | 60–180 saniye |
| İSPARK | 60–300 saniye |
| Hava kalitesi | 5–15 dakika |
| İETT hat/durak | 6–24 saat |
| Dataset katalog | 6–24 saat |
| Statik geo layer | 24 saat – 7 gün |

---

### 4.6 Geo search

MVP’de coğrafi sorgu çok kritik. Şu iki sorgu tipi mutlaka olmalı:

```txt
1. radius search: koordinat + yarıçap
2. bbox search: harita kutusu içinde arama
```

Desteklenecek entity türleri:

```txt
- bus_stop
- metro_station, veri hızlı bulunursa
- bike_station
- parking
- air_quality_station
```

`geo_features` canonical modeli:

```sql
geo_features
- id
- source
- feature_type
- source_id
- name
- lat
- lon
- geometry_json
- district
- neighborhood
- properties_json
- valid_at
- retrieved_at
```

Minimum input validation:

```txt
lat: -90 ile 90 arası
lon: -180 ile 180 arası
radius_m: max 5000
limit: default 20, max 100
bbox: geçerli min_lon, min_lat, max_lon, max_lat
```

---

### 4.7 İSPARK nearby

İlk demo için en güçlü alanlardan biri.

Tool:

```txt
istanbul_parking_nearby
```

Input:

```json
{
  "lat": 40.9909,
  "lon": 29.0303,
  "radius_m": 1000,
  "limit": 10,
  "only_with_capacity": false
}
```

Output alanları:

```txt
- otopark adı
- koordinat
- mesafe
- kapasite, varsa
- boş/dolu bilgisi, varsa
- çalışma saati, varsa
- fiyat bilgisi, varsa kaynakta mevcutsa
- freshness
- source
```

MVP notu:

```txt
Kaynakta anlık doluluk yoksa sonuç açıkça “doluluk bilgisi bu kaynakta yok” demeli.
```

---

### 4.8 İsbike nearby

Tool:

```txt
istanbul_bike_stations_nearby
```

Input:

```json
{
  "lat": 40.9909,
  "lon": 29.0303,
  "radius_m": 1000,
  "limit": 10,
  "only_available_bikes": true
}
```

Output alanları:

```txt
- istasyon adı
- koordinat
- mesafe
- toplam park/dock kapasitesi, varsa
- müsait bisiklet sayısı, varsa
- boş park yeri, varsa
- freshness
- source
```

---

### 4.9 Hava kalitesi nearby

Tool:

```txt
istanbul_air_quality_nearby
```

Input:

```json
{
  "lat": 41.0422,
  "lon": 29.0083,
  "radius_m": 5000,
  "limit": 3
}
```

Output alanları:

```txt
- en yakın ölçüm istasyonu
- mesafe
- ölçüm zamanı
- AQI veya kaynakta bulunan hava kalitesi sınıfı
- PM10, PM2.5, NO2, SO2, O3 gibi varsa ölçümler
- freshness
- source
```

MVP notu:

```txt
Sağlık tavsiyesi gibi yüksek riskli iddialar verilmemeli. Sadece kaynak verisi ve genel sınıflandırma sunulmalı.
```

---

### 4.10 Trafik durumu

Tool:

```txt
istanbul_traffic_status
```

Input seçenekleri:

```json
{
  "district": "Kadıköy",
  "lat": 40.9909,
  "lon": 29.0303,
  "radius_m": 1500
}
```

veya:

```json
{
  "bbox": [29.00, 40.97, 29.08, 41.02]
}
```

Output alanları:

```txt
- trafik yoğunluğu skoru veya kaynak metriği
- düşük/orta/yüksek gibi sade yorum
- ölçüm zamanı
- kapsanan alan
- kaynak limiti
- freshness
```

MVP notu:

```txt
Trafik verisi yol/kaza/olay detayı sağlamıyorsa MCP bunu uydurmamalı. “Bu endpoint kaza detayı sağlamıyor” diye belirtmeli.
```

---

### 4.11 İETT temel hat/durak entegrasyonu

MVP’de tam rota planlama değil, temel hat/durak bilgisi hedeflenmeli.

Tool’lar:

```txt
istanbul_transit_line_info
istanbul_stops_for_line
```

`istanbul_transit_line_info` input:

```json
{
  "line_code": "34A"
}
```

`istanbul_stops_for_line` input:

```json
{
  "line_code": "34A",
  "direction": null
}
```

Output alanları:

```txt
- hat kodu
- hat adı
- yön, varsa
- durak adı
- durak kodu
- koordinat, varsa
- sıra numarası, varsa
- source
- freshness
```

SOAP adapter gereklilikleri:

```txt
[ ] SOAP response raw olarak snapshot’lanır.
[ ] XML parse hataları yakalanır.
[ ] Tip dönüşümleri merkezi yapılır.
[ ] Koordinatlar normalize edilir.
[ ] Bozuk endpoint için cache fallback uygulanır.
[ ] Adapter fixture testleri yazılır.
```

---

### 4.12 Güvenlik ve limitler

MVP public ise minimum güvenlik zorunlu.

```txt
[ ] Read-only tool’lar
[ ] Input validation
[ ] Default limit = 20
[ ] Hard max limit = 100
[ ] Radius max = 5000 m
[ ] Timeout = 10–15 sn
[ ] Source endpoint retry/backoff
[ ] Basic rate limit
[ ] Output sanitization
[ ] SQL guard veya SQL yerine filtreli query builder
```

Public beta için öneri:

```txt
- İlk demo private URL olabilir.
- Public olunca API key veya IP bazlı rate limit eklenmeli.
```

---

## 5. MVP dışı kalanlar

Aşağıdaki işler MVP’ye girmemeli. Sonraki fazlara bırakılmalı.

| Özellik | Neden MVP dışı? | Faz |
|---|---|---:|
| 542 datasetin tamamını normalize etmek | Çok geniş, kalite düşürür | v1+ |
| Tam rota planlama | GTFS/Realtime karmaşık | v0.2/v1 |
| Tahmini varış süresi | Kaynak doğrulama gerekir | v0.3 |
| Su kesintileri | Endpoint/kullanım koşulu doğrulanmalı | P1/P2 |
| Afet/deprem/uyarı sistemi | Kritik doğruluk ve sorumluluk ister | v1+ |
| Kullanıcı hesabı | MCP MVP için gereksiz | Public beta+ |
| Push notification / abonelik | MCP temel scope dışı | v1 |
| Harita web uygulaması | Ürün demosu olabilir ama MCP için şart değil | P2 |
| Vector tile servisleri | Geo ölçek büyüyünce gerekir | v1 |
| PostGIS | MVP için SQLite yeterli | v1 |
| Gelişmiş veri gazeteciliği analizleri | Önce temel catalog/query | v0.2 |
| OAuth tam entegrasyonu | İlk beta için API key yeterli olabilir | Public beta+ |
| Veri yazma/güncelleme tool’ları | Güvenlik riski | Kapsam dışı |

---

## 6. MVP tool listesi

### 6.1 Katalog tool’ları

| Tool | Zorunlu mu? | Açıklama |
|---|---:|---|
| `istanbul_search_datasets` | Evet | İBB açık veri kataloğunda arama yapar. |
| `istanbul_get_dataset` | Evet | Tek dataset metadata’sını döndürür. |
| `istanbul_get_resource_schema` | Evet | Resource kolon/format/schema bilgisini çıkarır. |
| `istanbul_query_resource` | Evet, sınırlı | CSV/DataStore kaynağını filtreli ve limitli sorgular. |

### 6.2 Geo tool’ları

| Tool | Zorunlu mu? | Açıklama |
|---|---:|---|
| `istanbul_nearby` | Evet | Koordinata yakın şehir nesnelerini döndürür. |
| `istanbul_bbox_search` | Evet | Harita alanı içinde nesne arar. |

### 6.3 Mobilite tool’ları

| Tool | Zorunlu mu? | Açıklama |
|---|---:|---|
| `istanbul_parking_nearby` | Evet | Yakındaki İSPARK otoparklarını döndürür. |
| `istanbul_bike_stations_nearby` | Evet | Yakındaki İsbike istasyonlarını döndürür. |
| `istanbul_air_quality_nearby` | Evet | Yakındaki hava kalitesi istasyonunu ve son ölçümü döndürür. |
| `istanbul_traffic_status` | Evet | Bölge/koordinat/bbox için trafik durumu döndürür. |

### 6.4 Transit tool’ları

| Tool | Zorunlu mu? | Açıklama |
|---|---:|---|
| `istanbul_transit_line_info` | Evet | Hat koduna göre temel hat bilgisi verir. |
| `istanbul_stops_for_line` | Evet | Hat koduna göre durakları döndürür. |
| `istanbul_lines_for_stop` | Hayır | v0.2’ye bırakılabilir. |
| `istanbul_arrivals` | Hayır | Endpoint doğrulaması gerektirir. |

---

## 7. MVP resource ve prompt listesi

MVP’de çok fazla resource/prompt açmaya gerek yok. Ancak üç resource ve iki prompt yararlı olur.

### 7.1 Resources

```txt
istanbul://catalog/summary
istanbul://status/freshness
istanbul://docs/usage-examples
```

Açıklama:

```txt
catalog/summary     -> indexlenen veri seti sayısı, format dağılımı, son tarama zamanı
status/freshness    -> kaynakların fresh/stale/broken durumu
docs/usage-examples -> örnek kullanıcı soruları ve tool kullanımı
```

### 7.2 Prompts

```txt
nearby_mobility_brief
istanbul_dataset_finder
```

Açıklama:

```txt
nearby_mobility_brief:
Koordinata göre bisiklet, otopark, hava kalitesi ve trafik özetini üretir.

istanbul_dataset_finder:
Kullanıcının veri ihtiyacına göre uygun İBB veri setlerini bulur.
```

---

## 8. MVP mimarisi

```mermaid
flowchart TD
    A[MCP Client: Claude / ChatGPT / Cursor] -->|Streamable HTTP| B[/mcp]

    B --> C[MCP Server]
    C --> D[Tools]
    C --> E[Resources]
    C --> F[Prompts]

    D --> G[Domain Services]

    G --> H1[Catalog Service]
    G --> H2[Geo Service]
    G --> H3[Mobility Service]
    G --> H4[Transit Service]
    G --> H5[Freshness Service]

    H1 --> I1[CKAN Connector]
    H3 --> I2[İSPARK Connector]
    H3 --> I3[İsbike Connector]
    H3 --> I4[Air Quality Connector]
    H3 --> I5[Traffic Connector]
    H4 --> I6[İETT SOAP Adapter]

    I1 --> J[(SQLite Cache)]
    I2 --> J
    I3 --> J
    I4 --> J
    I5 --> J
    I6 --> J

    J --> K[FTS5 + Geo Index]

    C --> L[Logs / Metrics / Health]
```

---

## 9. Önerilen MVP teknik stack

```txt
Dil:              Python 3.11+
MCP:              FastMCP veya resmi MCP Python SDK
HTTP runtime:     FastAPI / Starlette tabanı
Validation:       Pydantic
SOAP:             zeep + httpx
DB:               SQLite WAL
Search:           SQLite FTS5
Geo:              Haversine + RTree; gerekirse shapely
Jobs:             APScheduler veya basit startup/background task
Deploy:           Railway Docker
Testing:          pytest + fixture responses + MCP Inspector
Logging:          structlog veya standart JSON logs
```

MVP’de karmaşık stack’ten kaçın:

```txt
- Kubernetes yok
- Kafka yok
- Çok servisli microservice yok
- İlk sürümde PostGIS şart değil
- İlk sürümde ayrı frontend şart değil
```

---

## 10. Veri kaynakları — MVP öncelik sırası

| Öncelik | Kaynak sınıfı | Kullanım | MVP durumu |
|---:|---|---|---|
| 1 | CKAN katalog | Dataset search/metadata | Zorunlu |
| 2 | İSPARK | Otopark nearby | Zorunlu |
| 3 | İsbike | Bisiklet istasyonu nearby | Zorunlu |
| 4 | Hava kalitesi | Yakındaki ölçüm noktası | Zorunlu |
| 5 | Trafik yoğunluğu | Bölgesel trafik durumu | Zorunlu |
| 6 | İETT SOAP | Hat/durak bilgisi | Zorunlu ama dar kapsam |
| 7 | GTFS static | Transit derinleşme | Opsiyonel / v0.2 |
| 8 | İSKİ su kesintisi | Kesinti sorgusu | MVP dışı |

---

## 11. Veri modeli — MVP minimum

```sql
CREATE TABLE datasets (
  id TEXT PRIMARY KEY,
  ckan_id TEXT,
  slug TEXT,
  title TEXT,
  description TEXT,
  organization TEXT,
  groups_json TEXT,
  tags_json TEXT,
  license TEXT,
  source_url TEXT,
  metadata_json TEXT,
  last_modified TEXT,
  retrieved_at TEXT
);

CREATE TABLE resources (
  id TEXT PRIMARY KEY,
  dataset_id TEXT,
  ckan_resource_id TEXT,
  name TEXT,
  format TEXT,
  url TEXT,
  datastore_active INTEGER,
  schema_json TEXT,
  size_bytes INTEGER,
  hash TEXT,
  retrieved_at TEXT
);

CREATE TABLE geo_features (
  id TEXT PRIMARY KEY,
  source TEXT,
  feature_type TEXT,
  source_id TEXT,
  name TEXT,
  lat REAL,
  lon REAL,
  geometry_json TEXT,
  district TEXT,
  neighborhood TEXT,
  properties_json TEXT,
  valid_at TEXT,
  retrieved_at TEXT
);

CREATE TABLE cache_entries (
  key TEXT PRIMARY KEY,
  source_name TEXT,
  request_hash TEXT,
  response_hash TEXT,
  raw_body_path TEXT,
  retrieved_at TEXT,
  expires_at TEXT,
  status TEXT
);

CREATE TABLE freshness_checks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source_name TEXT,
  checked_at TEXT,
  status TEXT,
  latency_ms INTEGER,
  record_count INTEGER,
  error_message TEXT
);

CREATE TABLE tool_calls (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tool_name TEXT,
  input_hash TEXT,
  status TEXT,
  latency_ms INTEGER,
  result_count INTEGER,
  created_at TEXT
);
```

---

## 12. MVP dosya/repo yapısı

```txt
istanbul-mcp/
  app/
    main.py
    settings.py

    mcp/
      server.py
      tools/
        catalog.py
        geo.py
        mobility.py
        transit.py
      resources/
        catalog.py
        status.py
      prompts/
        nearby_mobility.py
        dataset_finder.py

    connectors/
      ckan.py
      ispark.py
      isbike.py
      air_quality.py
      traffic.py
      soap_base.py
      iett.py

    domain/
      models.py
      freshness.py
      geo.py
      normalization.py
      search.py

    storage/
      db.py
      migrations/
      repositories.py
      sqlite_geo.py
      snapshots.py

    jobs/
      refresh_catalog.py
      refresh_static_geo.py
      refresh_realtime.py

    security/
      validation.py
      rate_limit.py
      output_sanitizer.py
      sql_guard.py

  tests/
    fixtures/
      ckan/
      iett/
      ispark/
      isbike/
      traffic/
      air_quality/
    test_catalog_tools.py
    test_geo_tools.py
    test_mobility_tools.py
    test_transit_tools.py
    test_freshness.py
    test_validation.py

  docs/
    README.md
    TOOL_REFERENCE.md
    DATA_SOURCES.md
    DEPLOY_RAILWAY.md
    EXAMPLES.md

  Dockerfile
  railway.toml
  pyproject.toml
  .env.example
```

---

## 13. MVP kabul kriterleri

MVP tamamlandı sayılması için aşağıdaki kriterler karşılanmalı.

### 13.1 Fonksiyonel kriterler

```txt
[ ] Remote /mcp endpoint çalışıyor.
[ ] En az 10 MCP tool listeleniyor ve çağrılabiliyor.
[ ] Dataset arama çalışıyor.
[ ] Dataset metadata dönebiliyor.
[ ] Resource schema çıkarılabiliyor.
[ ] Yakındaki otoparklar bulunabiliyor.
[ ] Yakındaki bisiklet istasyonları bulunabiliyor.
[ ] Yakındaki hava kalitesi istasyonu bulunabiliyor.
[ ] Trafik durumu sorgulanabiliyor.
[ ] Hat koduna göre İETT hat bilgisi alınabiliyor.
[ ] Hat koduna göre durak listesi alınabiliyor.
[ ] Her cevap source ve freshness içeriyor.
```

### 13.2 Performans kriterleri

```txt
[ ] Cached P95 response < 2 saniye
[ ] Live P95 response < 8 saniye
[ ] Tool timeout max 15 saniye
[ ] Default result limit 20
[ ] Hard max result limit 100
[ ] Radius max 5000 m
```

### 13.3 Güvenilirlik kriterleri

```txt
[ ] Kaynak hata verirse cache fallback çalışıyor.
[ ] Hata cevabı structured dönüyor.
[ ] Tool success rate test ortamında > %95.
[ ] Bozuk SOAP/XML response test fixture ile yakalanıyor.
[ ] Fresh/stale/unknown/broken durumları test ediliyor.
```

### 13.4 Dokümantasyon kriterleri

```txt
[ ] README var.
[ ] Railway deploy dokümanı var.
[ ] Tool reference var.
[ ] Data source listesi var.
[ ] 20 örnek kullanıcı sorusu var.
[ ] .env.example var.
```

---

## 14. MVP demo soruları

MVP’yi test ve demo etmek için kullanılacak ana sorular:

```txt
1. İBB’de trafik yoğunluğu ile ilgili hangi veri setleri var?
2. İBB’de otoparkla ilgili hangi veri setleri var?
3. Kadıköy civarında trafik yoğun mu?
4. 40.9909, 29.0303 koordinatına en yakın İSPARK otoparkları hangileri?
5. Bu koordinata 1 km içindeki İsbike istasyonlarını göster.
6. Beşiktaş civarında en yakın hava kalitesi istasyonu ne ölçmüş?
7. 34A hattının duraklarını göster.
8. 500T hattı hakkında bilgi ver.
9. Bu veri ne kadar güncel?
10. Kaynak şu anda çalışmıyorsa son cache zamanını söyle.
11. Yakınımdaki şehir servislerini özetle.
12. Trafik verisi hangi kaynaktan geliyor?
13. Otopark sonucunda doluluk bilgisi var mı?
14. Bisiklet istasyonlarında müsait bisiklet var mı?
15. İBB açık veri kataloğunda metro istasyonlarıyla ilgili veri var mı?
16. Dataset kolonlarını açıkla.
17. Sadece GeoJSON formatındaki ulaşım veri setlerini göster.
18. Kadıköy için trafik ve bisiklet durumunu birlikte özetle.
19. 750 metre içindeki otobüs duraklarını ve otoparkları mesafeye göre sırala.
20. Bu sonuçta hangi limitler var?
```

---

## 15. İlk 4 haftalık MVP planı

### Hafta 1 — MCP iskeleti ve katalog

```txt
Gün 1:
[ ] Repo kurulumu
[ ] Python project setup
[ ] MCP server hello tool
[ ] /healthz ve /readyz
[ ] Railway hello deploy

Gün 2:
[ ] CKAN connector
[ ] package_search
[ ] package_show
[ ] dataset/resource modelleri

Gün 3:
[ ] SQLite schema
[ ] catalog snapshot job
[ ] dataset/resource repository

Gün 4:
[ ] istanbul_search_datasets
[ ] istanbul_get_dataset
[ ] FTS5 arama

Gün 5:
[ ] istanbul_get_resource_schema
[ ] response envelope
[ ] source/freshness alanları
```

### Hafta 2 — Geo ve mobilite

```txt
Gün 6:
[ ] geo_features tablosu
[ ] radius search
[ ] bbox search
[ ] istanbul_nearby

Gün 7:
[ ] İSPARK connector
[ ] parking normalization
[ ] istanbul_parking_nearby

Gün 8:
[ ] İsbike connector
[ ] bike station normalization
[ ] istanbul_bike_stations_nearby

Gün 9:
[ ] Hava kalitesi connector
[ ] station + reading model
[ ] istanbul_air_quality_nearby

Gün 10:
[ ] Trafik connector
[ ] istanbul_traffic_status
[ ] TTL cache
```

### Hafta 3 — İETT / SOAP ve dayanıklılık

```txt
Gün 11:
[ ] SOAP base adapter
[ ] raw XML snapshot
[ ] parse/error handling

Gün 12:
[ ] İETT line info adapter
[ ] istanbul_transit_line_info

Gün 13:
[ ] İETT stops for line adapter
[ ] istanbul_stops_for_line

Gün 14:
[ ] retry/backoff
[ ] circuit breaker
[ ] stale cache fallback

Gün 15:
[ ] fixture tests
[ ] validation tests
[ ] tool timeout tests
```

### Hafta 4 — Beta hazırlığı

```txt
Gün 16:
[ ] rate limit
[ ] output sanitization
[ ] SQL/query guard

Gün 17:
[ ] freshness status resource
[ ] catalog summary resource
[ ] usage examples resource

Gün 18:
[ ] nearby_mobility_brief prompt
[ ] istanbul_dataset_finder prompt

Gün 19:
[ ] README
[ ] TOOL_REFERENCE
[ ] DATA_SOURCES
[ ] DEPLOY_RAILWAY

Gün 20:
[ ] 20 golden prompt testi
[ ] Railway production deploy
[ ] public/private beta smoke test
```

---

## 16. MVP backlog — GitHub issue formatı

### Epic 1 — MCP Core

```txt
[ ] Initialize Python MCP server
[ ] Add Streamable HTTP endpoint
[ ] Add health/readiness endpoints
[ ] Add shared response envelope
[ ] Add structured error handling
[ ] Add tool call logging
```

### Epic 2 — Catalog

```txt
[ ] Build CKAN connector
[ ] Build catalog snapshot job
[ ] Store datasets/resources in SQLite
[ ] Add FTS5 search index
[ ] Implement istanbul_search_datasets
[ ] Implement istanbul_get_dataset
[ ] Implement istanbul_get_resource_schema
[ ] Implement limited istanbul_query_resource
```

### Epic 3 — Geo

```txt
[ ] Create geo_features model
[ ] Implement haversine distance
[ ] Implement radius search
[ ] Implement bbox search
[ ] Implement istanbul_nearby
[ ] Implement istanbul_bbox_search
```

### Epic 4 — Mobility

```txt
[ ] Build İSPARK connector
[ ] Implement istanbul_parking_nearby
[ ] Build İsbike connector
[ ] Implement istanbul_bike_stations_nearby
[ ] Build air quality connector
[ ] Implement istanbul_air_quality_nearby
[ ] Build traffic connector
[ ] Implement istanbul_traffic_status
```

### Epic 5 — Transit

```txt
[ ] Build SOAP base adapter
[ ] Build İETT line info adapter
[ ] Build İETT stops adapter
[ ] Implement istanbul_transit_line_info
[ ] Implement istanbul_stops_for_line
[ ] Add SOAP fixture tests
```

### Epic 6 — Freshness & Cache

```txt
[ ] Add TTL policy per source
[ ] Add freshness state machine
[ ] Add stale cache fallback
[ ] Add source health checks
[ ] Add freshness status resource
```

### Epic 7 — Security

```txt
[ ] Add Pydantic input validation
[ ] Add hard limits for radius/limit/bbox
[ ] Add rate limiting
[ ] Add output sanitization
[ ] Add SQL/query guard
[ ] Add timeout/retry/backoff
```

### Epic 8 — Docs & Release

```txt
[ ] Write README
[ ] Write TOOL_REFERENCE
[ ] Write DATA_SOURCES
[ ] Write DEPLOY_RAILWAY
[ ] Write EXAMPLES
[ ] Add .env.example
[ ] Add Railway config
[ ] Run 20 golden prompt tests
```

---

## 17. MVP riskleri ve azaltma planı

| Risk | Etki | Çözüm |
|---|---|---|
| Kaynak endpoint değişir | Tool bozulur | Adapter fixture testleri ve health check |
| SOAP parse hatası | İETT tool’ları bozulur | Raw snapshot + parser fallback + test fixture |
| Trafik verisi beklenenden farklı formatta gelir | Yanlış yorum | Format doğrulama + kaynak limitlerini açık söyleme |
| Çok büyük sonuç döner | LLM context şişer | limit, pagination, summary-first response |
| SQLite kilitlenir | Public beta yavaşlar | WAL, read-heavy tasarım, v1’de PostGIS geçişi |
| Kullanıcı “anlık” sanır ama veri eski olabilir | Güven kaybı | freshness badge zorunlu |
| Belirsiz lokasyon adı | Yanlış bölge | MVP’de koordinat öncelikli; ilçe/mahalle resolver v0.2 |
| Rate limit yoksa kaynaklara yük biner | Servis engellenebilir | TTL cache + rate limit + backoff |
| Veri açıklamalarında prompt injection | Model yanıltılabilir | HTML/text sanitization + açıklamaları veri olarak etiketleme |

---

## 18. Net MVP “Definition of Done”

MVP bitti diyebilmek için şunlar doğru olmalı:

```txt
[ ] Tek URL ile MCP client’a bağlanıyor.
[ ] En az 10 tool çalışıyor.
[ ] İBB katalog araması çalışıyor.
[ ] En az 5 yüksek değerli şehir verisi sorgulanıyor:
    [ ] trafik
    [ ] otopark
    [ ] bisiklet
    [ ] hava kalitesi
    [ ] İETT hat/durak
[ ] Her cevap source içeriyor.
[ ] Her cevap freshness içeriyor.
[ ] Hata olunca cache fallback veya net hata mesajı dönüyor.
[ ] Railway deploy var.
[ ] README ve tool reference var.
[ ] 20 demo sorusunun en az 16’sı başarılı cevap veriyor.
[ ] Cached cevaplar 2 saniye altında dönüyor.
[ ] Public kullanımda limit/rate limit var.
```

---

## 19. MVP için önerilen ilk release adı

```txt
istanbul-mcp v0.1.0 — City Data Core
```

Release açıklaması:

```txt
İstanbul MCP v0.1.0, İBB açık veri kataloğunu ve temel şehir servislerini MCP uyumlu AI asistanlara açan ilk sürümdür. Bu sürüm dataset arama, kaynak metadata, yakındaki otopark/bisiklet/hava kalitesi noktaları, trafik durumu ve temel İETT hat/durak bilgilerini destekler. Her cevap kaynak ve veri tazeliği bilgisiyle döner.
```

---

## 20. Son net karar

MVP’de şu stratejiyi izle:

```txt
1. Önce katalog + kaynak güvenilirliği.
2. Sonra geo search.
3. Sonra 4 güçlü şehir servisi: trafik, otopark, bisiklet, hava kalitesi.
4. Sonra dar kapsamlı İETT hat/durak SOAP adapter.
5. Her şeyde source + freshness + limit.
6. Railway üzerinde tek URL ile kullanılabilir public/private beta.
```

Bu kapsamla İstanbul MCP ilk sürümde “her şeyi yapan ama kırılgan” bir demo değil, **az ama net çalışan, güvenilir ve genişletilebilir bir şehir veri MCP’si** olur.
