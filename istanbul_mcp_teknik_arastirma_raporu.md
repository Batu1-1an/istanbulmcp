# İstanbul MCP — Teknik Araştırma ve Stack Kararı Raporu

**Tarih:** 2026-06-10
**Durum:** Araştırma tamamlandı
**Hazırlayan:** opencode (ctx7 + Exa derin araştırma)

---

## 1. Projenin Net Tanımı

> İBB'nin 542 veri seti (41 API + CSV/GeoJSON/SOAP/GTFS) içeren açık veri portalını, AI asistanların (Claude, ChatGPT, Cursor) tek URL ekleyerek kullanabileceği bir **remote MCP Server** haline getirmek.

### Pazar Boşluğu

| Şehir | MCP Server | Durum |
|---|---|---|
| İzmir | `halilcengel/IzmirMCP` | ✅ npm'de yayında, 15+ tool |
| İzmir | `ogulcanakca/izmir-ulasim-mcp` | ✅ Python, ESHOT odaklı |
| New York | `jdamcd/gtfs-mcp` | ✅ MTA, config-driven |
| Madrid | `dieguezz/mcp-madrid-public-transport` | ✅ Metro + EMT + Cercanías |
| Zürih | `malkreide/zurich-opendata-mcp` | ✅ 20 tool, 6 API, Python |
| Hong Kong | `rxtech-lab/hk-transportation-mcp` | ✅ Go + PostGIS |
| **İstanbul** | **❌ Yok** | **Boşluk** |

---

## 2. Kaynak Doküman Analizi

Proje dizinindeki 4 dokümanın ortak vizyonu:

| Doküman | Odak | Tutarsızlık |
|---------|------|-------------|
| `ibb-mcp-analysis-report.md` | 304 dataset analizi, SOAP problemi, 3 MCP önerisi | TS/Python belirtilmemiş |
| `ibb-mcp-project-report.md` | Rekabet analizi, SOAP çözümü, mimari | **TypeScript** öneriyor |
| `istanbul_mcp_mvp_kapsami.md` | MVP tool listesi, veri modeli, 4 haftalık plan | **Python** öneriyor |
| `istanbul_mcp_yol_haritasi.md` | Full product vision, 6 faz, 30 gün planı | **Python** öneriyor |

### Kritik Karar Noktası: TypeScript vs Python

Dokümanlarda çelişki var. Bu rapor, ctx7 ve Exa ile yapılan derin araştırma sonucunda **Python'u** önermektedir.

---

## 3. ctx7 ile Güncel Dokümantasyon Araştırması

### 3.1 FastMCP / MCP Python SDK

- **libraryId:** `/modelcontextprotocol/python-sdk`
- **Versiyon:** v1.12.4
- **Snippet sayısı:** 450
- **Benchmark:** 94.1/100
- **Kaynak itibarı:** High

```python
from mcp.server.fastmcp import FastMCP

# Stateless HTTP + JSON response (recommended for production)
mcp = FastMCP("istanbul-mcp", stateless_http=True, json_response=True)

@mcp.tool()
def trafik_durumu(ilce: str) -> str:
    """İstanbul'da belirtilen ilçedeki anlık trafik durumunu döndürür"""
    return f"{ilce} trafik verisi..."

@mcp.resource("istanbul://catalog/summary")
def katalog_ozeti() -> str:
    """İBB açık veri kataloğu özeti"""
    return "..."

@mcp.prompt()
def nearby_mobility_brief(lat: float, lon: float) -> str:
    """Koordinat bazlı mobilite özeti üretir"""
    return f"..."

if __name__ == "__main__":
    mcp.run(transport="streamable-http")
```

**Önemli:** `transport="streamable-http"` ile tek satırda HTTP server. `stateless_http=True` ile Railway'de yatay scale edilebilir.

### 3.2 Zeep (Python SOAP)

- **libraryId:** `/mvantellingen/python-zeep`
- **Snippet sayısı:** 214
- **Benchmark:** 76.17/100

```python
from zeep import Client
from zeep import AsyncClient
import asyncio

# Senkron
wsdl = 'https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl'
client = Client(wsdl=wsdl)
data = client.service.GetFiloAracKonum_json({})
# Direkt JSON dönüyor! *_json suffix'li metodlar IBB'ye özel

# Asenkron (production için önerilen)
async def get_bus_locations():
    client = AsyncClient(wsdl)
    result = await client.service.GetFiloAracKonum_json({})
    await client.transport.aclose()
    return result

# Raw XML oluşturma (debug için)
envelope = client.create_message(client.service, 'GetFiloAracKonum_json')
```

### 3.3 CKAN API

- **libraryId:** `/ckan/ckan`
- **Snippet sayısı:** 5918
- **Benchmark:** 88.5/100

```python
import requests

CKAN_BASE = "https://data.ibb.gov.tr/api/3/action"

# Dataset arama
r = requests.get(f"{CKAN_BASE}/package_search", params={"q": "trafik"})

# Dataset metadata
r = requests.get(f"{CKAN_BASE}/package_show", params={"id": "dataset-slug"})

# DataStore SQL sorgu
r = requests.get(f"{CKAN_BASE}/datastore_search_sql", params={
    "sql": "SELECT * FROM \"resource_id\" WHERE \"ilce\" = 'Kadıköy' LIMIT 20"
})

# DataStore filtreli sorgu
r = requests.get(f"{CKAN_BASE}/datastore_search", params={
    "resource_id": "resource-uuid",
    "limit": 5,
    "filters": {"ilce": "Kadıköy"}
})
```

### 3.4 GTFS Kit

- **libraryId:** `/araichev/gtfs_kit_docs`
- **Snippet sayısı:** 423

```python
import gtfs_kit as gk

feed = gk.read_feed("iett_gtfs.zip", dist_units="km")

# Tüm duraklar
stops = feed.stops

# Bir hattaki duraklar (GeoDataFrame)
stops = feed.get_stops(route_ids=["34A"], as_gdf=True)

# Sefer istatistikleri
stats = feed.compute_trip_stats(route_ids=["34A", "500T"])

# Zaman serisi (bir duraktan saatlik geçen sefer sayısı)
ts = feed.compute_stop_time_series(
    dates=["20260715"],
    stop_ids=["12345"],
    freq="h"
)
```

---

## 4. Exa ile Derin Web Araştırması

### 4.1 İBB SOAP Çözümü: hakanatak/dataibbgovtr

- **Yıldız:** 36 ★
- **Dil:** JavaScript (Node.js/Express) + Python versiyonu da var
- **Kapsam:** İBB İETT: filo konum, durak, garaj, duyuru
- **SOAP çözümü:** `soap` npm paketi (JS) / `zeep` (Python)
- **Çıktı:** GeoJSON
- **Önemli not:** SOAP servisleri her gece 00:15'te kapanıyor

```python
# hakanatak/dataibbgovtr_python'dan alınan gerçek kod
import zeep
import json
import geopandas as gpd
import shapely.wkt

wsdl = 'https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl'
client = zeep.Client(wsdl=wsdl)
data = client.service.GetDurak_json(DurakKodu="")
data = json.loads(data)
# Koordinat dönüşümü + GeoJSON çıktı
```

### 4.2 En Yakın Referans Projeler

#### Zurich Open Data MCP (Python) — En Yakın Model

| Özellik | Değer |
|---------|-------|
| Dil | Python (FastMCP) |
| Tools | 20 |
| Resources | 6 |
| APIs | CKAN + WFS + REST + SPARQL |
| Gerçek Zamanlı | Hava, park, yaya sayacı |
| Deploy | Streamable HTTP |

**Ders:** CKAN + gerçek zamanlı + geo = İstanbul MCP için en yakın mimari.

#### IzmirMCP (TypeScript)

| Özellik | Değer |
|---------|-------|
| Dil | TypeScript |
| Tools | 15+ |
| Veri | CKAN + OpenAPI |
| Transport | stdio (lokal) |
| Mimari | Modüler: `api/` + `tools/` |

**Ders:** Belediye MCP pattern'i. Aynı yapı İstanbul'a uyarlanabilir.

#### gtfs-mcp (TypeScript) — jdamcd

| Özellik | Değer |
|---------|-------|
| SQLite cache | ✅ GTFS schedule |
| Config | JSON (sistem bazında) |
| Tools | 11 |

**Ders:** GTFS SQLite cache + config-driven pattern.

#### Madrid Transport MCP (TypeScript)

| Özellik | Değer |
|---------|-------|
| Dil | TypeScript |
| GTFS | 229MB SQLite cache |
| SOAP | Phase 2'ye ertelenmiş |

**Ders:** SOAP'ı MVP dışı bırakma stratejisi.

### 4.3 Railway + FastMCP Deploy

Araştırma sonucu **Railway'de FastMCP deploy** için kanıtlanmış pattern:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
```

FastMCP'nin `http_app()` metodu ASGI uyumlu bir uygulama döndürür. Railway otomatik PORT env atar, otomatik SSL sağlar.

---

## 5. Stack Kararı — Nihai

### Önerilen: Python + FastMCP + zeep + SQLite + Railway

| Bileşen | Seçim | Gerekçe |
|---------|-------|---------|
| **Dil** | **Python 3.11+** | SOAP/zeep, GTFS/gtfs_kit, Geo/shapely avantajı; FastMCP olgun (450 snippet) |
| **MCP** | **FastMCP** (`mcp>=1.9.4`) | Resmi Python SDK, `streamable-http` built-in, stateless mode |
| **SOAP** | **zeep** | İBB'de hakanatak tarafından kanıtlanmış, AsyncClient var |
| **CKAN** | **requests** | Direkt REST, 3 satır kod, ckanapi opsiyonel |
| **GTFS** | **gtfs_kit** | Pandas/GeoPandas tabanlı, stops/routes/trips hazır metodlar |
| **DB** | **SQLite WAL** | MVP için yeterli, FTS5 + RTree built-in, Railway volume persistence |
| **Geo** | **shapely + haversine** | MVP'de radius/bbox için yeterli; geopandas ileri faz |
| **Validation** | **pydantic** | FastMCP ile native entegre |
| **Deploy** | **Railway Docker** | Python Docker, otomatik SSL, $5/ay Hobby, volume desteği |
| **Jobs** | **APScheduler** | Catalog refresh, GTFS update, freshness checks |
| **Logging** | **structlog** | JSON log, Railway structured logs ile uyumlu |
| **Test** | **pytest + respx** | HTTP mock, SOAP fixture, MCP Inspector |

### Neden TypeScript Değil?

> **ÖNEMLİ GÜNCELLEME (2026-06-10):** Canlı testler sonucu SOAP'un **sadece İETT servisleri** (HatDurakGuzergah, SeferGerceklesme, Duyuru) için gerekli olduğu tespit edilmiştir. ISPARK, Hava Kalitesi, Trafik, Metro servislerinin tamamı REST/JSON'dir.

| İhtiyaç | Python | TypeScript |
|---------|--------|------------|
| IBB SOAP (SADECE İETT) | `zeep` — tek satırda JSON | `soap` npm — çalışıyor, 36★ kanıt |
| GTFS 30MB CSV işleme | `gtfs_kit` (Pandas) — hazır metodlar | `gtfs-bindings` — manuel işleme |
| GeoJSON/KML/KMZ dönüşüm | `shapely` + `geopandas` | `@turf/turf` — daha az kapsamlı |
| FTS5 + RTree | Python `sqlite3` built-in | `better-sqlite3` — ek paket |
| Async HTTP | `httpx` | `axios` — benzer |
| Streamable HTTP | `FastMCP.run(transport="streamable-http")` | Express + `@modelcontextprotocol/sdk` |

### Alternatif: TypeScript (Eğer Israr Edilirse)

Dokümanlardaki TypeScript önerisi de geçerlidir. Stack şöyle olur:

```txt
TypeScript + @modelcontextprotocol/sdk + soap npm + better-sqlite3 + Express + Railway
```

Ama İBB'nin SOAP, GTFS, GeoJSON, CSV, KML gibi çeşitli formatları **Python'un veri işleme ekosisteminde** çok daha rahat yönetilir.

---

## 6. Önerilen Mimari

```
MCP Client (Claude / ChatGPT / Cursor)
    │ Streamable HTTP (POST /mcp)
    ▼
FastMCP Server — /mcp endpoint (Railway, $5/ay)
    │
    ├── Tools (11 MVP)
    │   ├── istanbul_search_datasets(query, formats, limit)
    │   ├── istanbul_get_dataset(dataset_id)
    │   ├── istanbul_get_resource_schema(resource_id)
    │   ├── istanbul_nearby(lat, lon, types, radius_m, limit)
    │   ├── istanbul_bbox_search(min_lon, min_lat, max_lon, max_lat, types)
    │   ├── istanbul_parking_nearby(lat, lon, radius_m, limit, only_with_capacity)
    │   ├── istanbul_bike_stations_nearby(lat, lon, radius_m, limit, only_available_bikes)
    │   ├── istanbul_air_quality_nearby(lat, lon, radius_m, limit)
    │   ├── istanbul_traffic_status(district, lat, lon, bbox)
    │   ├── istanbul_transit_line_info(line_code)
    │   └── istanbul_stops_for_line(line_code, direction)
    │
    ├── Resources
    │   ├── istanbul://catalog/summary
    │   ├── istanbul://status/freshness
    │   └── istanbul://docs/usage-examples
    │
    ├── Prompts
    │   ├── nearby_mobility_brief
    │   └── istanbul_dataset_finder
    │
    ├── Domain Services
    │   ├── Catalog Service (CKAN connector)
    │   ├── Geo Service (Haversine + RTree)
    │   ├── Mobility Service (İSPARK, İsbike, Trafik, Hava)
    │   ├── Transit Service (İETT SOAP/zeep adapter)
    │   └── Freshness Service (TTL + stale fallback)
    │
    ├── Connectors
    │   ├── ckan.py (REST/JSON)
    │   ├── soap_base.py (zeep AsyncClient wrapper)
    │   ├── iett.py (HatDurakGuzergah, SeferGerceklesme)
    │   ├── ispark.py
    │   ├── isbike.py
    │   ├── air_quality.py
    │   ├── traffic.py
    │   └── gtfs.py (gtfs_kit loader)
    │
    ├── Storage
    │   ├── db.py (SQLite WAL)
    │   ├── repositories.py
    │   ├── sqlite_geo.py (RTree)
    │   └── migrations/
    │
    └── SQLite Cache (Railway volume persistence)
```

### Repo Yapısı

```
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
        mobility.py
        dataset_finder.py
    connectors/
      ckan.py
      soap_base.py
      iett.py
      ispark.py
      isbike.py
      air_quality.py
      traffic.py
      gtfs.py
    domain/
      models.py
      freshness.py
      geo.py
      search.py
      normalization.py
    storage/
      db.py
      migrations/
      repositories.py
      sqlite_geo.py
    jobs/
      refresh_catalog.py
      refresh_gtfs.py
      freshness_checks.py
    security/
      validation.py
      rate_limit.py
      output_sanitizer.py
  tests/
    fixtures/
      ckan/
      soap/
      geojson/
    test_catalog.py
    test_geo.py
    test_mobility.py
    test_transit.py
    test_freshness.py
  docs/
    README.md
    TOOL_REFERENCE.md
    DATA_SOURCES.md
    DEPLOY_RAILWAY.md
  Dockerfile
  pyproject.toml
  railway.toml
  .env.example
```

---

## 7. Veri Katmanları

> **GÜNCELLEME (2026-06-10):** Canlı testler sonucu SOAP katmanının **sadece İETT** için gerekli olduğu tespit edilmiştir. ISPARK, Hava Kalitesi, Trafik, Metro saf REST/JSON'dir.

| Katman | Teknoloji | Güncellik | Protokol | MVP |
|--------|-----------|-----------|----------|-----|
| CKAN Katalog | REST + requests | 6-24 saat snapshot | REST/JSON | ✅ |
| GTFS Static | gtfs_kit + SQLite | Günlük refresh | CSV/REST | ✅ (v0.2) |
| İETT (SOAP) | zeep AsyncClient | Her sorguda (gece kapanır) | **SOAP/XML** | ✅ |
| İETT HatOtoKonum | zeep AsyncClient | Her sorguda (MVP icin ideal) | **SOAP/XML** | ✅ (kesif!) |
| İSPARK | httpx | Sorgu anında | **REST/JSON** | ✅ |
| Metro İstanbul | httpx | Sorgu anında | **REST/JSON** | ✅ |
| Trafik İndeksi | httpx | Sorgu anında | **REST/JSON** | ✅ |
| Hava Kalitesi | httpx | Sorgu anında | **REST/JSON** | ✅ |
| Su Kesintisi | CKAN DataStore | Güncel veri | REST/JSON | P1 |
| Isbike | httpx | Sorgu anında | **REST/JSON** | ⚠️ şu an boş |
| Geo Cache | SQLite RTree | Snapshot periyoduna göre | Local | ✅ |

---

## 8. Response Standardı

Her tool aynı envelope'ı kullanır:

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
    "retrieved_at": "2026-06-10T12:00:00+03:00",
    "source_updated_at": null,
    "ttl_seconds": 120
  },
  "sources": [
    {
      "name": "İBB Açık Veri Portalı",
      "publisher": "İstanbul Büyükşehir Belediyesi",
      "dataset_id": "",
      "resource_id": "",
      "license": "İstanbul Büyükşehir Belediyesi Açık Veri Lisansı",
      "url": ""
    }
  ],
  "limits": [],
  "warnings": [],
  "next_queries": []
}
```

### Freshness Durumları

| Durum | Anlam |
|-------|-------|
| `fresh` | TTL içinde, kaynak cevap verdi |
| `stale` | Son veri var ama TTL geçti |
| `unknown` | Kaynak güncelleme zamanı vermiyor |
| `broken` | Kaynak hata veriyor, cache fallback |

### TTL Politikası

| Veri Tipi | TTL |
|-----------|-----|
| Trafik | 30-120 sn |
| İsbike | 60-180 sn |
| İSPARK | 60-300 sn |
| Hava kalitesi | 5-15 dk |
| İETT hat/durak | 6-24 saat |
| Dataset katalog | 6-24 saat |

---

## 9. SOAP Gece Kapanması (Sadece İETT)

`hakanatak/dataibbgovtr` notu:
> SOAP servisleri her gece saat 00.15'ten sonra kapatılmaktadır.

**Bu sadece İETT servislerini etkiler.** ISPARK, Trafik, Hava Kalitesi, Metro gibi REST/JSON servisler gece de çalışır.

**Çözüm (İETT için):**
- Tool açıklamasında belirt
- GTFS static verisi (tarifeler) çalışmaya devam eder
- Cache fallback: son başarılı yanıtı döndür, `freshness: stale` olarak işaretle
- REST servisler (ISPARK, Trafik, Hava, Metro) zaten sorunsuz çalışır

---

## 10. Railway Deploy Planı

```
FastMCP → http_app() → ASGI (Uvicorn) → Docker → Railway
```

**Dockerfile:**
```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install uv && uv sync
COPY . .
EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
```

**railway.toml:**
```toml
[build]
builder = "DOCKERFILE"

[deploy]
startCommand = "uvicorn app.main:app --host 0.0.0.0 --port $PORT"
healthcheckPath = "/healthz"
```

**Claude Desktop Config:**
```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://istanbul-mcp.up.railway.app/mcp"
    }
  }
}
```

---

## 11. İlk Adım Planı (1 Hafta MVP Core)

| Gün | Ne Yapılacak | Teknoloji |
|-----|-------------|-----------|
| 1 | Repo + FastMCP hello tool + Railway deploy | Python, FastMCP, Docker |
| 2 | CKAN connector + catalog snapshot + SQLite schema | requests, sqlite3 |
| 3 | `istanbul_search_datasets` + FTS5 + response envelope | FastMCP tool, FTS5 |
| 4 | SOAP base adapter (zeep) + İETT hat/durak tool | zeep, FastMCP |
| 5 | Geo features tablosu + RTree + `istanbul_nearby` | RTree, shapely |
| 6 | İSPARK + İsbike + trafik connector'ları | httpx, zeep |
| 7 | Hava kalitesi + freshness sistemi + test | pytest, respx |

---

## 12. Referans Projeler (Linkler)

| Proje | URL | Dil | Önemi |
|-------|-----|-----|-------|
| Zurich Open Data MCP | `github.com/malkreide/zurich-opendata-mcp` | Python | En yakın şehir MCP modeli |
| IzmirMCP | `github.com/halilcengel/IzmirMCP` | TypeScript | Belediye MCP pattern |
| gtfs-mcp | `github.com/jdamcd/gtfs-mcp` | TypeScript | GTFS SQLite cache |
| dataibbgovtr | `github.com/hakanatak/dataibbgovtr` | JavaScript | IBB SOAP çözümü (36★) |
| dataibbgovtr_python | `github.com/hakanatak/dataibbgovtr_python` | Python | IBB SOAP + zeep (5★) |
| FastMCP | `github.com/jlowin/fastmcp` | Python | Resmi MCP Python SDK |
| Railway MCP deploy | `github.com/Magnazee/railwaymcp` | Python | Railway deploy reference |
| Madrid Transport | `github.com/dieguezz/mcp-madrid-public-transport` | TypeScript | SOAP erteleme |
| Hong Kong Transport | `github.com/rxtech-lab/hk-transportation-mcp` | Go | PostGIS + MCP |
| Winnipeg City MCP | `github.com/nhannpl/wpg-city-mcp` | Python | Şehir transit MCP |
| MBTA GTFS MCP | `github.com/bribroder/gtfs-mcp` | Python | GTFS + Streamable HTTP |

---

## 13. Sonuç

**Net öneri:** Python + FastMCP + zeep + SQLite + Railway ile İstanbul MCP.

**Gerekçe:**
1. SOAP **sadece İETT için** gerekli — diğer tüm servisler REST/JSON (dokümanlardaki "her şey SOAP" bilgisi güncel değil)
2. İBB'nin İETT SOAP servisleri `zeep` ile 3 satır kodda çözülüyor (hakanatak kanıtı)
3. FastMCP `streamable-http` ile tek satırda remote MCP server
4. GTFS/GeoJSON/CSV işleme Python'da çok daha rahat
5. Railway Docker + Python + SQLite kanıtlanmış kombinasyon
6. Zurich Open Data MCP (Python) aynı mimariyi kanıtlıyor
7. Toplam MVP süresi **~6-7 gün**

**Riskler:**
- SOAP gece 00:15 kapanması (sadece İETT'yi etkiler, REST servisler çalışır)
- Isbike API şu an boş dönüyor (portal "temporarily unavailable" diyor)
- Hava kalitesi AQI değerleri null dönüyor (zamanla düzelebilir)
- İETT Duyuru servisi HTTP 500 "Policy Falsified" hatası veriyor

**Ek Bulgular:**
- `GetHatOtoKonum_json` keşfedildi: hat bazlı anlık araç konumu + yön + yakın durak — MVP için en değerli veri kaynağı
- CKAN DataStore ilçe bazlı filtreleme ile kütüphane, su kesintisi gibi veriler sorgulanabiliyor
- Metro İstanbul 18 hat, 248 istasyon ile çok kapsamlı bir REST API sunuyor
- ISPARK 259 park, anlık boş yer bilgisi ile en pratik demo verisi

---

## 14. EK: Canlı Veri Kaynağı Doğrulama — 2026-06-10

Tüm kritik İBB endpoint'leri birebir HTTP çağrısı ile test edilmiştir. Detaylı doğrulama raporu `istanbul_mcp_veri_kaynagi_dogrulama.md` dosyasındadır.

### Özet Bulgular

#### 🚨 KRİTİK KEŞİF: SOAP SADECE İETT İÇİN

Önceki dokümanlarda "tüm anlık veriler SOAP" deniyordu. Gerçek kontrolde:

| Servis | Sanılan | Gerçek |
|--------|---------|--------|
| ISPARK | SOAP | **REST/JSON** ✅ |
| Hava Kalitesi | SOAP | **REST/JSON** ✅ |
| Trafik İndeksi | SOAP | **REST/XML** ✅ |
| Metro | SOAP | **REST/JSON** ✅ |
| **İETT (Hat,Durak,Sefer)** | SOAP | **SOAP** — sadece burası |

Bu, `zeep` kullanımını çok dar bir alana (sadece İETT servisleri) indirgemektedir.

#### 🎯 KRİTİK KEŞİF: GetHatOtoKonum_json

`GetFiloAracKonum_json`'dan farklı olarak **hat bazlı anlık araç konumu** döndürür:
- Sadece o hattaki araçlar
- Yön bilgisi (`yon`)
- Yakın durak kodu (`yakinDurakKodu`)
- Güzergah kodu (`guzergahkodu`)

MVP için **en değerli veri kaynağı**.

#### Test Edilen Endpoint'ler (Canlı)

| # | Endpoint | Protokol | Canlı | Veri |
|---|----------|----------|-------|------|
| 1 | CKAN `package_list` | REST | ✅ | 550 dataset |
| 2 | CKAN `package_search` | REST | ✅ | Filtreli arama |
| 3 | CKAN `datastore_search` | REST | ✅ | Structured data, ilçe bazlı |
| 4 | İETT `GetHat_json("130E")` | SOAP | ✅ | 802 hat sorgulanabilir |
| 5 | İETT `GetDurak_json("")` | SOAP | ✅ | **15.148 durak** |
| 6 | İETT `GetFiloAracKonum_json` | SOAP | ✅ | **6.911 araç anlık** |
| 7 | İETT `GetHatOtoKonum_json("500T")` | SOAP | ✅ | **43 araç** (hat bazlı!) |
| 8 | İETT Duyuru | SOAP | ❌ | HTTP 500 |
| 9 | ISPARK `.../ispark/Park` | REST | ✅ | **259 park**, anlık boş yer |
| 10 | ISPARK `.../ParkDetay?id=X` | REST | ✅ | Tarife, ücret, polygon |
| 11 | Trafik `.../TrafficIndexHistory` | REST/XML | ✅ | Index 58 (19:47), 286 kayıt |
| 12 | Hava Kalitesi `GetAQIStations` | REST | ✅ | **28 istasyon** |
| 13 | Hava Kalitesi `GetAQIByStationId` | REST | ⚠️ | AQI değerleri null |
| 14 | Metro `GetStations` | REST | ✅ | **248 istasyon, 18 hat** |
| 15 | Su Kesintisi (CKAN) | REST | ✅ | **19.236 kayıt** |
| 16 | Kütüphane (CKAN) | REST | ✅ | İlçe bazlı sorgu |
| 17 | Isbike `GetAllStationStatus` | REST | ⚠️ | dataList: [] boş |

### Düzeltilen Sayısal Bilgiler

| Eski Bilgi | Yeni (Doğrulanmış) |
|------------|-------------------|
| 542 veri seti | **550** |
| GTFS son güncelleme: Mart 2026 | **2026-04-21** |
| ISPARK 300+ park | **259 park** |
| Hava kalitesi 10+ istasyon | **28 istasyon** |
| Metro bilinmiyor | **248 istasyon, 18 hat** |
| İETT durak sayısı bilinmiyor | **15.148 durak** |
| İETT hat sayısı bilinmiyor | **802 hat** |
| Trafik indeksi SOAP | REST/XML |
| Trafik kayıt sayısı | **286** (5 dk aralık) |
