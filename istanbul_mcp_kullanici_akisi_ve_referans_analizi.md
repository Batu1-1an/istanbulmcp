# Istanbul MCP — Kullanici Akisi ve Referans Proje Analizi

**Tarih:** 2026-06-10
**Amac:** MCP'nin calisma mantigini, Claude'in kullanici sorusu uzerine nasil tool cagirdigini ve referans projelerin bunu nasil yaptigini aciklamak.

---

## 1. MCP Calisma Mantigi (Kullanim Akisi)

### Adim Adim: Kullanici Sorusundan Cevaba

Kullanici soyle bir soru sordugunda:
> "Kadikoy RIhtim'dan Sogutlucesme Metrobuse nasil giderim?"

Su akis gerceklesir:

```
KULLANICI (Claude Desktop / ChatGPT / Cursor)
  |
  | "Kadikoy RIhtim'dan Sogutlucesme Metrobuse nasil giderim?"
  v
CLAUDE (LLM)
  |
  | 1. Soruyu anlar: Kadikoy'de bir noktadan metrobuse gececek
  | 2. Hangi tool'lari kullanacagini belirler
  | 3. MCP Server'a tools/list istegi atar
  v
MCP SERVER (istanbul-mcp)
  |
  | tools/list doner:
  |   - istanbul_nearby(lat, lon, types, radius)
  |   - istanbul_transit_line_info(line_code)
  |   - istanbul_stops_for_line(line_code)
  |   - istanbul_traffic_status(district)
  |
  v
CLAUDE (Karar Mekanizmasi)
  |
  | 4. Ilk cagri: istanbul_nearby(lat=40.9924, lon=29.0249, 
  |                types=["bus_stop","metro"], radius=200)
  |
  v
MCP SERVER
  |
  | Cevap: RIHTIM duragi (205421), KADIKOY metrobus (49m otede)
  |
  v
CLAUDE
  |
  | 5. Ikinci cagri: istanbul_transit_line_info("34A")
  |
  v
MCP SERVER
  |
  | Cevap: 34A = METROBUS, Cevizlibag - Siritlibesme
  |
  v
CLAUDE
  |
  | 6. Ucuncu cagri: istanbul_stops_for_line("34A")
  |
  v
MCP SERVER
  |
  | Cevap: ... Sogutlucesme, Uzuncayir, ... (durak listesi)
  |
  v
CLAUDE
  |
  | 7. Tum bilgileri birlestirir, kullaniciya cevap verir
  |
  v
KULLANICI
  | "RIhtim'dan 50m yuruyerek Kadikoy metrobuse gelin.
  |  34A metrobusune binin, Sogutlucesme'de inin.
  |  (Yaklasik 10 dakika)"
```

### Protokol Detayi

MCP protokolunde iki ana istek var:

**1. tools/list** — Claude hangi tool'larin oldugunu ogrenir:
```json
// Request (Claude -> MCP Server)
{
  "jsonrpc": "2.0",
  "method": "tools/list",
  "id": 1
}

// Response (MCP Server -> Claude)
{
  "jsonrpc": "2.0",
  "tools": [
    {
      "name": "istanbul_nearby",
      "description": "Bir koordinata yakin sehir nesnelerini (durak, metro, otopark) bulur",
      "inputSchema": {
        "type": "object",
        "properties": {
          "lat": { "type": "number", "description": "Enlem (-90 ile 90 arasi)" },
          "lon": { "type": "number", "description": "Boylam (-180 ile 180 arasi)" },
          "types": { "type": "array", "items": { "type": "string" }, "description": "Nesne turleri" },
          "radius": { "type": "number", "description": "Yaricap (metre, max 5000)" }
        },
        "required": ["lat", "lon"]
      }
    }
  ]
}
```

**2. tools/call** — Claude bir tool'u calistirir:
```json
// Request
{
  "jsonrpc": "2.0",
  "method": "tools/call",
  "params": {
    "name": "istanbul_nearby",
    "arguments": {
      "lat": 40.9924,
      "lon": 29.0249,
      "types": ["bus_stop", "metro"],
      "radius": 200
    }
  }
}

// Response
{
  "jsonrpc": "2.0",
  "result": {
    "content": [
      {
        "type": "text",
        "text": "750 metre icinde 3 otobus duragi ve 1 metro istasyonu bulundu..."
      }
    ]
  }
}
```

### Claude'in Karar Mekanizmasi

Claude yuksek seviyede bir LLM olarak:

1. **Tool secimi**: Kullanici sorusundaki anahtar kelimelere gore hangi tool'un uygun oldugunu belirler
   - "nasil giderim" = transit/ulasim tool'lari
   - "nerede" = nearby/location tool'lari
   - "trafik" = traffic tool'u

2. **Parametre tahmini**: Konum adlarini koordinata cevirir (veya ayri bir geocode tool'u cagirir)
   - "Kadikoy RIhtim" = ~40.9924, 29.0249
   - "Sogutlucesme" = ~40.9924, 29.0249 (metrobus duragi)

3. **Tool zincirleme**: Birden fazla tool'u sirayla cagirir
   - Once yakin yerleri bul
   - Sonra hat bilgisini sorgula
   - Sonra durak listesini al
   - Hepsini birlestir

4. **Cevap sentezi**: Tool'lardan gelen ham veriyi dogal dile cevirir

---

## 2. Referans Projelerin Karsilastirmasi

| Proje | Dil | MCP SDK | Transport | Tool Sayisi | Veri Kaynagi | Response | Yildiz |
|-------|-----|---------|-----------|:-----------:|--------------|----------|:------:|
| **Yargi MCP** | **Python** | FastMCP | HTTP + stdio | **19** | **15+ REST/HTML/PDF** | JSON | **758** |
| **Zurich Open Data MCP** | Python | FastMCP | stdio/HTTP | 20 | CKAN + WFS + REST + SPARQL | Markdown | ~10 |
| **IzmirMCP** | TypeScript | @mcp/sdk | stdio | 19 | CKAN + OpenAPI | JSON | ~5 |
| **gtfs-mcp** | TypeScript | @mcp/sdk | stdio/HTTP | 11 | GTFS + GTFS-RT | JSON | ~5 |
| **Winnipeg City MCP** | Python | FastMCP | stdio | 8 | Transit REST + 311 API | Text | ~3 |

### 2.1 Zurich Open Data MCP (En Yakin Model)

**URL:** `github.com/malkreide/zurich-opendata-mcp`
**Dil:** Python (FastMCP)
**Tool sayisi:** 20
**Response:** Markdown string

**Mimari:**
```
FastMCP Server
  |
  +-- tools/ (catalog.py, datastore.py, geo.py, realtime.py, ...)
  |     Her tool @mcp.tool() dekoratoru ile kayitli
  |     async fonksiyonlar, Pydantic input validation
  |
  +-- clients/ (wfs.py, paris.py, tourism.py)
  |     Herbiri ayri API'ye ozgu istemci
  |
  +-- http_client.py (shared httpx.AsyncClient)
  +-- formatters.py (markdown formatlama)
  +-- config.py (API URL'leri, literal sabitler)
```

**Tool tanimlama ornegi:**
```python
@mcp.tool(name="zurich_parking_live")
async def zurich_parking_live() -> str:
    """Get real-time parking garage occupancy in Zurich"""
    try:
        data = await http_get_json(PARKENDD_URL)
        # formatla ve markdown don
        return "\n".join(lines)
    except Exception as e:
        return handle_api_error(e, "Parkplatz-Daten")
```

**Dersler:**
- **Pydantic** ile input validation sart (ekstra alanlari engelle)
- **Markdown** format LLM'in daha iyi yorumlamasini saglar
- **client/*** klasoruyle API istemcileri ayri dosyalarda
- `readOnlyHint`, `idempotentHint` gibi annotation'lar tool metadata'sina eklenmis

### 2.2 IzmirMCP (En Yakin Belediye MCP'si)

**URL:** `github.com/halilcengel/IzmirMCP`
**Dil:** TypeScript (@modelcontextprotocol/sdk)
**Tool sayisi:** 19
**Response:** JSON (stringify)

**Mimari:**
```
McpServer
  |
  +-- tools/ (eshot.ts, izban.ts, metro.ts, tram.ts, ferry.ts, train.ts)
  |     Her dosya register*Tools(server) export eder
  |     Zod ile schema dogrulama
  |
  +-- api/ (eshot.ts, izban.ts, ...)
  |     Her ulasim turu icin API cagrilari
  |     Iki veri kaynagi: CKAN (static) + OpenAPI (gercek zamanli)
  |
  +-- http.ts (Axios client factory)
  +-- config.ts (env-based config)
```

**Tool tanimlama:**
```typescript
server.tool(
  "get-line-bus-locations",
  "Get real-time locations of buses on a specific ESHOT line",
  { hatNo: z.string().describe("Line number (e.g., 121)") },
  async ({ hatNo }) => {
    const data = await getLineBusLocations(hatNo);
    return { content: [{ type: "text", text: JSON.stringify(data, null, 2) }] };
  }
);
```

**Dersler:**
- CKAN + OpenAPI ikili veri kaynagi - Izmir de ayni yapiyi kullaniyor
- Her ulasim turu ayri tool dosyasinda (moduler)
- **Stdio transport** sadece — HTTP yok
- JSON response (biz Markdown tercih edebiliriz)

### 2.3 gtfs-mcp (GTFS Veri Yonetimi)

**URL:** `github.com/jdamcd/gtfs-mcp`
**Dil:** TypeScript
**Tool sayisi:** 11
**Veri:** GTFS static + GTFS-RT realtime

**Mimari:**
```
Config JSON (sistem tanimlari)
  |
  v
GTFS Static (SQLite + `gtfs` npm paketi)
  |  - Her sistem ayri SQLite db
  |  - schedule_refresh_hours ile TTL
  |
GTFS-RT (30 sn in-memory cache)
  |  - protobuf decode (gtfs-realtime-bindings)
  |  - TripUpdates, VehiclePositions, Alerts
  |
Tools (stops.ts, routes.ts, arrivals.ts, alerts.ts, ...)
  |  - find_nearby_stops: bounding box + Haversine
  |  - get_arrivals: RT + schedule birlestirme
```

**Nearby stop algoritmasi:**
```typescript
// 1. SQL bounding box (index kullanir)
// 2. Haversine distance (JS'de hesaplar)
const candidates = db.prepare(`
  SELECT stop_id, stop_name, stop_lat, stop_lon
  FROM stops
  WHERE stop_lat BETWEEN ? AND ?
    AND stop_lon BETWEEN ? AND ?
`).all(lat - latDelta, lat + latDelta, lon - lonDelta, lon + lonDelta);

// Haversine filtrele + sirala + limit uygula
return candidates
  .map(s => ({ ...s, distance_m: haversineMeters(lat, lon, s.stop_lat, s.stop_lon) }))
  .filter(s => s.distance_m <= radiusMeters)
  .sort((a, b) => a.distance_m - b.distance_m)
  .slice(0, limit);
```

**Dersler:**
- SQLite'da **RTree index** yakindaki durak sorgulari icin ideal
- **GTFS-RT protobuf** decode kutuphanesi
- **Config-driven** yaklasim: her sehir JSON config dosyasiyla eklenebilir
- RT + scheduled veriyi birlestirme mantigi

### 2.4 Winnipeg City MCP (Transit + Trip Planning)

**URL:** `github.com/nhannpl/wpg-city-mcp`
**Dil:** Python (FastMCP)
**Tool sayisi:** 8
**Veri:** Winnipeg Transit API + Open-Meteo + 311

**Mimari:**
```
FastMCP Server
  |
  +-- tools/transit.py (get_bus_arrivals, find_stops_near)
  +-- tools/trip_planning.py (plan_trip, plan_journey)
  +-- tools/issues.py (search_311_issues)
  +-- tools/locations.py (landmark cozucu + OSM geocoding)
  +-- config.py (API anahtarlari + URL'ler)
```

**Trip planning akisi:**
```python
# 1. Lokasyon cozumu: landmark mi? durak no mu? adres mi?
def format_location(input_str):
    if input_str in LANDMARKS:
        return LANDMARKS[input_str]
    if input_str.isdigit():
        return f"stops/{input_str}"
    # OSM Nominatim ile geocode
    ...

# 2. API cagrisi
async def fetch_trip_plan(origin, dest, mode="depart-after"):
    url = f"{BASE}/trip-planner.json?api-key={key}&origin={origin}&dest={dest}"

# 3. Yaniti insan-okur formata cevir
def format_plan_text(plan):
    return f"""
    Trip: {origin} -> {dest}
    Total: {duration} min
      Walk: {walk} min
      Ride: {ride} min
    """
```

**Dersler:**
- **Landmark cozucu**: "Kadikoy RIhtim" gibi dogal dil girdilerini koordinata cevirme
- **OSM Nominatim** ile geocoding
- `asyncio.gather` ile paralel API cagrilari
- **Google Maps walking direction linki** olusturma

### 2.5 Yargi MCP (Turkish Legal Databases — EN KAPSAMLI REFERANS)

**URL:** `github.com/saidsurucu/yargi-mcp`
**Yildiz:** 758+ ⭐
**Dil:** Python (FastMCP 2.10+)
**Tool sayisi:** 27 (24 aktif + 3 ozel)
**Veri:** 15+ Turk hukuk veritabani
**Kaynak Kodu:** 56 Python dosyasi, ~124 KB ana dosya
**Deploy:** Streamable HTTP (Fly.io) + stdio (uvx)
**PyPI:** `yargi-mcp` (pip ile kurulum)

---

#### Genel Bakis

Yargi MCP, Turk hukuk kaynaklarina MCP uzerinden erisim saglayan **en kapsamli Turk MCP projesidir.** Tum kaynak kodu kopyalanip `C:\Users\X\AppData\Local\Temp\opencode\yargi-mcp` adresine klonlanmis ve her dosya tek tek okunmustur.

Proje, Istanbul MCP ile birebir ayni kategoride olmasa da (hukuk vs ulasim), **Turk kamu verisine MCP ile erisim** konusunda en iyi referanstir. IBB acik verisi de kamu verisidir ve ayni mimari pattern'lerin cogu birebir uygulanabilir.

---

#### 2.5.1 Proje Yapisi (Her Dosya)

Klonlanan projede 56 Python dosyasi bulunmaktadir:

```
yargi-mcp/
├── mcp_server_main.py           # 124.782 bytes — TUM tool tanimlari
├── asgi_app.py                  # FastAPI ASGI wrapper
├── app.py                       # Minimal ASGI (FastMCP http_app)
├── pyproject.toml               # Bagimliliklar
├── CLAUDE.md                    # 86 KB dokumantasyon
├── redis_session_store.py       # Upstash Redis OAuth store
├── example_fastapi_app.py       # 79 KB — REST API wrapper
├── __main__.py                  # Entry point
├── Dockerfile                   # Python 3.12-slim
├── railway.json                 # Railway config
│
├── bedesten_mcp_module/         #   ★ MERKEZI MODUL
│   ├── client.py                #   BedestenApiClient + TokenBucket
│   ├── models.py                #   Pydantic request/response modelleri
│   └── enums.py                 #   BirimAdiEnum (79 chamber kodu)
│
├── sayistay_mcp_module/         #   Sayistay (ASP.NET WebForms)
│   ├── client.py                #   32 KB — CSRF + DataTables + WAF
│   ├── models.py                #   11 KB — 3 karar tipi model
│   ├── unified_client.py        #   Birlestirici client
│   └── enums.py                 #   Daire, Kurum, Konu enum'lari
│
├── anayasa_mcp_module/          #   Anayasa Mahkemesi
│   ├── client.py                #   Norm denetimi
│   ├── bireysel_client.py       #   Bireysel basvuru
│   ├── unified_client.py        #   URL'den tip algilama
│   └── models.py                #   15 KB — tum modeller
│
├── kik_mcp_module/              #   KIK (AES-256-CBC sifreleme)
│   ├── client_v2.py             #   23 KB — AES-192 imzalama
│   └── models_v2.py             #   Decision type enum
│
├── rekabet_mcp_module/          #   Rekabet Kurumu
│   ├── client.py                #   24 KB — HTML + PDF scraping
│   └── models.py                #   KararTuru GUID enum
│
├── kvkk_mcp_module/             #   KVKK (Brave Search API)
│   ├── client.py                #   15 KB
│   └── models.py
│
├── bddk_mcp_module/             #   BDDK (Tavily API)
│   ├── client.py                #   10 KB
│   └── models.py
│
├── gib_mcp_module/              #   GIB (vergi)
│   ├── client.py                #   13 KB
│   └── models.py
│
├── sigorta_tahkim_mcp_module/   #   Sigorta Tahkim
│   ├── client.py                #   13 KB
│   └── models.py
│
├── uyusmazlik_mcp_module/       #   Uyusmazlik Mahkemesi
│   ├── client.py                #   12 KB — ASP.NET form POST
│   └── models.py
│
├── emsal_mcp_module/            #   UYAP Emsal
│   ├── client.py                #   8 KB
│   └── models.py
│
├── yargitay_mcp_module/         #   Yargitay (DEACTIVE)
│   ├── client.py                #   9 KB
│   └── models.py
│
├── danistay_mcp_module/         #   Danistay (DEACTIVE)
│   ├── client.py                #   9 KB
│   └── models.py
│
└── semantic_search/             #   Opsiyonel embedding
    ├── embedder.py              #   13 KB — OpenAI uyumlu
    ├── vector_store.py          #   8 KB — numpy ile cosine similarity
    └── processor.py             #   10 KB — chunking + temizlik
```

---

#### 2.5.2 Tool Kayit Mimarisi

**MCP Spec Compliance:** Dosyanin en basinda (satir 1-13) JSON-RPC uyumluluk yamasi:
```python
from mcp.types import JSONRPCNotification as _McpJSONRPCNotification
from pydantic import ConfigDict as _ConfigDict
_McpJSONRPCNotification.model_config = _ConfigDict(extra="forbid")
```
Bu, null JSON-RPC ID'lerinin `-32600 Invalid Request` hatasiyla reddedilmesini saglar.

**FastMCP App olusturma:**
```python
app = FastMCP(name="Yargı MCP Server", version="0.1.6")

def create_app():
    global app
    if TIKTOKEN_AVAILABLE:
        token_counter = TokenCountingMiddleware()
        app.add_middleware(token_counter)
    return app
```

**Tool tanimlama patterni:**
```python
@app.tool(
    description="Use this when searching...",
    annotations={
        "readOnlyHint": True,        # Okuma sadece
        "openWorldHint": True,        # Acik uclu veri (search)
        "idempotentHint": True        # Ayni girdi -> ayni cikti
    }
)
async def tool_name(
    param1: str = Field(""),         # Bos string default -> anyOf yok!
    param2: int = Field(1, ge=1),
    param3: List[str] = []
) -> dict:
    ...
```

**Middleware (TokenCountingMiddleware):**
```python
class TokenCountingMiddleware(Middleware):
    def __init__(self, model: str = "cl100k_base"):
        self.encoder = tiktoken.get_encoding(model)
    
    async def on_call_tool(self, context, call_next):
        # Girdi token'larini say
        # Cikti token'larini say
        # JSON log: tool_name, input_tokens, output_tokens, duration_ms
        # Per-tool istatistik tut
```

**Client Instance'lar (16 adet singleton):**
```python
yargitay_client_instance = YargitayOfficialApiClient()
bedesten_client_instance = BedestenApiClient()
danistay_client_instance = DanistayApiClient()
emsal_client_instance = EmsalApiClient()
uyusmazlik_client_instance = UyusmazlikApiClient()
anayasa_norm_client_instance = AnayasaMahkemesiApiClient()
anayasa_bireysel_client_instance = AnayasaBireyselBasvuruApiClient()
anayasa_unified_client_instance = AnayasaUnifiedClient()
kik_v2_client_instance = KikV2ApiClient()
rekabet_client_instance = RekabetKurumuApiClient()
sayistay_client_instance = SayistayApiClient()
sayistay_unified_client_instance = SayistayUnifiedClient()
kvkk_client_instance = KvkkApiClient()
bddk_client_instance = BddkApiClient()
gib_client_instance = GibApiClient()
sigorta_tahkim_client_instance = SigortaTahkimApiClient()

atexit.register(perform_cleanup)  # Tum client session'lari kapat
```

---

#### 2.5.3 Tum Aktif Tool'lar (24 + 3 = 27)

**Katalog Tool'lari (3):**

| # | Tool Adi | Aciklama |
|:-:|----------|----------|
| 1 | `search_emsal_detailed_decisions` | UYAP Emsal kararlarinda detayli arama |
| 2 | `get_emsal_document_markdown` | Emsal karar metnini Markdown getir |
| 3 | `search_uyusmazlik_decisions` | Uyusmazlik Mahkemesi kararlari ara |

**Anayasa Mahkemesi (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 4 | `search_anayasa_unified` | decision_type, keywords, page_to_fetch, norm/bireysel parametreleri |
| 5 | `get_anayasa_document_unified` | document_url, page_number |

**KIK (Kamu Ihale Kurulu) (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 6 | `search_kik_v2_decisions` | decision_type (uyusmazlik/duzenleyici/mahkeme), karar_metni, karar_no, basvuran, idare_adi, tarihler |
| 7 | `get_kik_v2_document_markdown` | gundemMaddesiId |

**Rekabet Kurumu (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 8 | `search_rekabet_kurumu_decisions` | sayfaAdi, PdfText, KararTuru (6 tip), KararSayisi, KararTarihi, page |
| 9 | `get_rekabet_kurumu_document` | karar_id, page_number |

**Bedesten Unified API (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 10 | `search_bedesten_unified` | **ctx: Context**, phrase, court_types (5 tip), pageNumber, birimAdi (79 kod), kararTarihiStart/End |
| 11 | `get_bedesten_document_markdown` | documentId |

**Sayistay Unified (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 12 | `search_sayistay_unified` | decision_type (3 tip), start, length, karar_tarih_baslangic/bitis, daire, kurum, konu + tip-specific |
| 13 | `get_sayistay_document_unified` | decision_id, decision_type |

**KVKK (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 14 | `search_kvkk_decisions` | keywords, page |
| 15 | `get_kvkk_document_markdown` | decision_url, page_number |

**BDDK (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 16 | `search_bddk_decisions` | keywords, page |
| 17 | `get_bddk_document_markdown` | document_id, page_number |

**GIB (2):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 18 | `search_gib_ozelge` | keywords, ozelgeNo, kanunNo, tarihler, page, pageSize |
| 19 | `get_gib_ozelge_document_markdown` | ozelge_id, page_number |

**Sigorta Tahkim (3):**
| # | Tool Adi | Parametreler |
|:-:|----------|--------------|
| 20 | `search_sigorta_tahkim_decisions` | keywords, page |
| 21 | `get_sigorta_tahkim_document_markdown` | issue_number, page_number |
| 22 | `search_within_sigorta_tahkim_issue` | issue_number, keyword, max_results |

**Ozel Tool'lar (5):**
| # | Tool Adi | Aciklama |
|:-:|----------|----------|
| 23 | `search_bedesten_semantic` | (opsiyonel) Bedesten + embedding ile semantik arama |
| 24 | `check_government_servers_health` | Tum sunuculari saglik kontrolu |
| 25 | `search` | ChatGPT Deep Research icin birlesik arama |
| 26 | `fetch` | ChatGPT Deep Research icin belge getirme |

---

#### 2.5.4 Veri Kaynagi Connector Pattern'leri

**7 farkli connector patterni tespit edilmistir:**

| Pattern | Protokol | Kullanilan Modul | Detay |
|---------|----------|-----------------|-------|
| **A. JSON POST API** | REST | Yargitay, Danistay, Emsal, GIB | `POST {"data": {...}}` -> JSON response |
| **B. JSON REST API** | REST | Bedesten, KIK v2 | Standart REST + AES sifreleme (KIK) |
| **C. HTML Form POST** | Web | Uyusmazlik, Sayistay | `application/x-www-form-urlencoded` + BS4 |
| **D. HTML Scrape** | Web | Anayasa (norm + bireysel) | GET -> BeautifulSoup parse |
| **E. HTML + PDF Download** | Web | Rekabet | Sayfa scraping -> PDF indir -> pypdf |
| **F. 3rd Party Search API** | API | KVKK (Brave), BDDK (Tavily), Sigorta (Tavily) | Arama API + dogrudan indirme |
| **G. Unified Client** | Wrapper | AnayasaUnifiedClient, SayistayUnifiedClient | URL/param'den tip algilama + yonlendirme |

**Pattern A: JSON POST API (Detayli)**
```python
# Yargitay ornegi
class YargitayOfficialApiClient:
    BASE_URL = "https://karararama.yargitay.gov.tr"
    SEARCH_ENDPOINT = "/aramadetaylist"
    
    async def search_detailed_decisions(self, request: YargitayDetailedSearchRequest):
        response = await self.http_client.post(
            self.SEARCH_ENDPOINT,
            json={"data": request.model_dump(exclude_none=True)}
        )
        return YargitayDetailedSearchResponse(**response.json())
```

**Pattern C: HTML Form POST (Sayistay detayli)**
```python
class SayistayApiClient:
    BASE_URL = "https://www.sayistay.gov.tr"
    _WAF_BLOCK_MARKER = "Bilgi Güvenliği Politikaları Gereği Kısıtlanmıştır"
    
    async def _initialize_session_for_endpoint(self, endpoint_type: str) -> bool:
        # 1. GET ile CSRF token al
        response = await self.http_client.get(page_url)
        soup = BeautifulSoup(response.text, 'html.parser')
        csrf_input = soup.find('input', {'name': '__RequestVerificationToken'})
        self.csrf_tokens[endpoint_type] = csrf_input['value']
        
        # 2. Session cookie'lerini sakla
        for cookie_name, cookie_value in response.cookies.items():
            self.session_cookies[cookie_name] = cookie_value
    
    def _raise_if_waf_blocked(self, response):
        if response.status_code == 418 or self._WAF_BLOCK_MARKER in response.text:
            raise RuntimeError("Sayistay WAF blocked the request...")
    
    async def search_genel_kurul_decisions(self, params):
        # DataTables protocol: columns[] + order[] + search parametreleri
        form_data = [
            ("draw", "1"), ("start", "0"), ("length", "10"),
            ("columns[0][data]", "KARARNO"),
            ("columns[1][data]", "KARARTARIH"),
            # ... 30+ column definition
            ("KararlarGenelKurulAra.KARARNO", params.karar_no or ""),
            ("__RequestVerificationToken", self.csrf_tokens['genel_kurul'])
        ]
        response = await self.http_client.post(
            self.GENEL_KURUL_ENDPOINT,
            data=urlencode(form_data)
        )
        self._raise_if_waf_blocked(response)
        return self._parse_datatables_response(response.json())
```

**Pattern F: Brave Search API (KVKK)**
```python
class KvkkApiClient:
    BRAVE_API_URL = "https://api.search.brave.com/res/v1/web/search"
    KVKK_BASE_URL = "https://www.kvkk.gov.tr"
    
    def __init__(self):
        self.brave_api_token = os.getenv("BRAVE_API_TOKEN", "BSAuaRKB-dvSDSQxIN0ft1p2k6N82Kq")
        # Fallback token built-in!
    
    async def search_decisions(self, request: KvkkSearchRequest) -> KvkkSearchResult:
        brave_params = {
            "q": f"site:kvkk.gov.tr \"karar özeti\" {request.keywords}",
            "count": 10,
            "offset": (request.page - 1) * 10
        }
        response = await self.http_client.get(
            self.BRAVE_API_URL,
            params=brave_params,
            headers={"Accept": "application/json", "Accept-Encoding": "gzip"}
        )
        # Sonuclari KVKK sitesinden indir
        for result in web_results:
            doc_response = await self.http_client.get(result["url"])
            # HTML -> Markdown
```

---

#### 2.5.5 Rate Limiter: TokenBucket Implementasyonu

```python
class _TokenBucket:
    def __init__(self, capacity: int, refill_per_s: float):
        self.capacity = float(capacity)
        self.refill_per_s = float(refill_per_s)
        self._tokens = float(capacity)
        self._lock = asyncio.Lock()
    
    async def acquire(self, max_wait: Optional[float] = None):
        """Token al. Bekleme suresi max_wait'i asarsa BedestenRateLimited firlat."""
        while True:
            async with self._lock:
                now = time.monotonic()
                if now < self._not_before:
                    wait_s = self._not_before - now
                else:
                    self._tokens = min(self.capacity,
                        self._tokens + (now - self._last) * self.refill_per_s)
                    self._last = now
                    if self._tokens >= 1.0:
                        self._tokens -= 1.0
                        return
                    wait_s = (1.0 - self._tokens) / self.refill_per_s
            if deadline and wait_s > remaining:
                raise BedestenRateLimited(retry_after=wait_s)
            await asyncio.sleep(wait_s)
    
    def penalize_until(self, monotonic_deadline: float):
        """429 alindiginda bucket'i dondur."""
        self._not_before = max(self._not_before, monotonic_deadline)
        self._tokens = 0.0
```

Konfigurasyon (env vars):
```
BEDESTEN_RATE_CAPACITY = 1     # burst kapasitesi
BEDESTEN_RATE_REFILL_S = 3.5   # token basi saniye (%14 marj)
BEDESTEN_RATE_MAX_WAIT_S = 8.0 # maksimum bekleme
```

Olculen limit: 10 req / 30sn window per source IP. 429 dondugunde `Retry-After` header'ina gore bucket dondurulur.

---

#### 2.5.6 Token Optimizasyon Stratejisi (Phase-by-Phase)

Proje %56.8 token azaltimi yapmis (14.061 -> 6.073 token):

**Phase 1: Null Type Simplification (%42.1 azalma)**
- `Optional[str] = Field(None)` -> `str = Field("")`
- ~72 parametrede uygulandi
- JSON Schema'daki `anyOf` pattern'lerini yok etti

**Phase 2: Chamber Enum Compression**
- 79 daire kodu -> `H1`-`H23`, `C1`-`C23`, `D1`-`D17` gibi 2-5 karakter
- Orjinal mapping korundu, client tarafinda genisletiliyor

**Phase 3-4: Description + Micro-optimizations**
- 16 kelimeye indirgenmis tool aciklamalari
- `pageSize` parametre olarak kaldirildi, sabit 10 yapildi

**Phase 5: Tool Removal (Yargitay & Danistay)**
- 5 tool devre disi birakildi (comment out)
- Bedesten unified API alternatif olarak kullaniliyor

**Phase 6-7: Tool Unification**
- 4 Anayasa Mahkemesi araci -> 2 unified tool
- 6 Sayistay araci -> 2 unified tool
- Toplam 11 tool 4'e indirgendi

---

#### 2.5.7 HTML/PDF -> Markdown Donusum Pattern'i

Tum module'ler ayni pattern'i kullanir:

```python
from markitdown import MarkItDown
import io

# HTML -> BytesIO -> MarkItDown
html_bytes = html_content.encode('utf-8')
html_stream = io.BytesIO(html_bytes)
md_converter = MarkItDown()
result = md_converter.convert(html_stream)
markdown_content = result.text_content
```

**Thread offload patterni** (event-loop blokajini engeller):
```python
markdown_content = await asyncio.to_thread(self._convert_html_to_markdown, html_content)
```

**Pagination:** Uzun dokumanlar 5.000 karakter chunk'lara bolunur:
```python
DOCUMENT_MARKDOWN_CHUNK_SIZE = 5000
total_pages = math.ceil(content_length / DOCUMENT_MARKDOWN_CHUNK_SIZE)
markdown_chunk = full_markdown_content[start_index:end_index]
```

---

#### 2.5.8 Hata Yonetimi Pattern'leri

| Pattern | Kullanim | Davranis |
|---------|----------|----------|
| **1. Graceful Error Return** | KIK, BDDK, KVKK | Hata -> `{"error_code":"...","error_message":"..."}` dict don |
| **2. Re-raise** | Yargitay, Danistay, Emsal | Hata -> `logger.exception` + `raise` |
| **3. 429 Rate Limit** | Bedesten | Rate limit -> `{"error":"rate_limit_exceeded","status_code":429}` |
| **4. WAF Detection** | Sayistay | 418/WAF -> `RuntimeError("Sayistay WAF blocked...")` |
| **5. Input Validation** | Tum tool'lar | `if not id.strip(): raise ValueError(...)` |

**Tool-level error handling (KIK ornegi):**
```python
@app.tool(description="...")
async def search_kik_v2_decisions(...) -> dict:
    try:
        kik_decision_type = KikV2DecisionType(decision_type)
    except ValueError:
        return {"decisions": [], "error_code": "INVALID_DECISION_TYPE",
                "error_message": f"Invalid type: {decision_type}"}
    try:
        api_response = await kik_v2_client_instance.search_decisions(...)
        return {"decisions": [...], "total_records": ..., "page": ...}
    except Exception as e:
        return {"decisions": [], "error_code": "TOOL_ERROR",
                "error_message": str(e)}
```

---

#### 2.5.9 Deployment Mimarisi

```
ASGI Dual-Mode:
  app.py:           FastMCP.http_app() -> direkt mount
  asgi_app.py:      FastAPI + CORS -> /mcp/ mount + /health + /status

Dockerfile:
  FROM python:3.12-slim
  CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]

railway.json:
  { "deploy": { "startCommand": "uvicorn asgi_app:app --host 0.0.0.0 --port $PORT" } }

OAuth (redis_session_store.py):
  - Upstash Redis REST API ile serverless-friendly
  - OAuth code TTL: 600s, Session TTL: 3600s
  - Exponential backoff ile Redis retry
  - Key patterns: oauth:code:{code}, session:{session_id}
```

---

#### 2.5.10 Semantik Arama

```python
# 1. Bedesten ile 100 karar getir
initial_results = await bedesten_client.search_documents(
    BedestenSearchRequest(data=BedestenSearchData(phrase=initial_keyword, pageSize=100))
)

# 2. Embedding olustur
embedder = OpenRouterEmbedder(model="google/gemini-embedding-001", dims=3072)
doc_embeddings = embedder.encode_documents(document_texts)
query_embedding = embedder.encode_query(query)

# 3. Cosine similarity ile sirala
store = VectorStore()
store.add(doc_embeddings, metadata_list)
results = store.search(query_embedding, top_k=10, threshold=0.3)
```

Iki embedding saglayicisi:
- **Local**: Ollama/HuggingFace TEI (varsayilan: `nomic-embed-text`, 768 dim)
- **Hosted**: OpenRouter (varsayilan: `google/gemini-embedding-001`, 3072 dim)

---

#### 2.5.11 Devre Disi Biractiktan Tool'lar (Commentary)

Asagidaki tool'lar kodda comment icinde korunuyor. Silinmemis, cunku ileride tekrar aktif edilebilir:

- `search_yargitay_detailed` -> Bedesten ile degistirildi
- `get_yargitay_document_markdown` -> Bedesten ile degistirildi
- `search_danistay_by_keyword` -> Bedesten ile degistirildi
- `search_danistay_detailed` -> Bedesten ile degistirildi
- `get_danistay_document_markdown` -> Bedesten ile degistirildi
- 4 Anayasa tool -> 2 unified tool
- 6 Sayistay tool -> 2 unified tool

**Strateji:** Daha az tool, daha cok parametre. Tek `decision_type` Literal parametresi, 3 ayri tool'un yerini aliyor.

---

#### 2.5.12 Istanbul MCP Icin Cikarilacak Dersler

| # | Ders | Yargi MCP'deki Karsiligi | Istanbul MCP'ye Uyarlama |
|:-:|------|-------------------------|-------------------------|
| 1 | **Token optimizasyonu** | `str=""` default, kodlu enumlar, %56.8 azaltma | Tum tool aciklamalari 15-20 kelimeyi gecmemeli |
| 2 | **Unified API** | Bedesten 5 mahkeme -> 1 tool | `istanbul_nearby` tum tipler tek tool'da |
| 3 | **Rate limiter** | TokenBucket + 429 back-pressure | IBB SOAP ve REST API'ler icin lazim |
| 4 | **Monolitik yapi** | 124 KB tek `mcp_server_main.py` | Biz de tek `server.py` ile basla |
| 5 | **HTTP + stdio** | Her iki transport | Biz de her ikisini destekle |
| 6 | **Semantic search** | OpenRouter/Ollama + numpy | Faz 2'de eklenebilir |
| 7 | **CLAUDE.md** | 86 KB dokuman | Projenin en onemli dokumani |
| 8 | **Pagination** | 5.000 karakter chunk | Buyuk veri setleri icin gerekli |
| 9 | **Graceful error** | `{"error_code":"..."}` donmek | LLM hatayi yonlendirebilir |
| 10 | **Modul-per-source** | Herbir API icin ayri `_mcp_module/` | IBB icin: `iett_mcp_module/`, `ispark_mcp_module/` |
| 11 | **WAF detection** | Sayistay 418 yaniti | IBB'de benzeri olabilir |
| 12 | **HTML->Markdown** | MarkItDown + BytesIO + thread offload | Ayni pattern |
| 13 | **Fallback token** | Brave API token built-in | KVKK modulunde hazir token var |
| 14 | **2 asamali arama** | Brave/Tavily ile once bul, sonra icerigi indir | KVKK/BDDK patterni |
| 15 | **Veri kaynagi sagligi** | `check_government_servers_health` tool | Biz de benzer tool eklemeliyiz |

---

#### Karsilastirma: Tum Referans Projeler

| Proje | Yildiz | Tool | Dosya | Dil | Transport | Veri Kaynagi | Response | LOC |
|-------|:------:|:----:|:----:|:---:|:---------:|--------------|:--------:|:---:|
| **Yargi MCP** | **758** | **27** | **56** | Python | HTTP+stdio | 15+ REST/HTML/PDF | JSON | ~124K |
| Zurich Open Data | ~10 | 20 | ~30 | Python | HTTP+stdio | CKAN+WFS+REST | Markdown | ~5K |
| IzmirMCP | ~5 | 19 | ~12 | TypeScript | stdio | CKAN+OpenAPI | JSON | ~3K |
| gtfs-mcp | ~5 | 11 | ~10 | TypeScript | HTTP+stdio | GTFS+GTFS-RT | JSON | ~2K |
| Winnipeg MCP | ~3 | 8 | ~6 | Python | stdio | REST APIs | Text | ~1K |

**Yargi MCP, 758 yildiz, 56 dosya, 27 tool, 15+ veri kaynagi ile bu listedeki acik ara en kapsamli projedir.** Tum kaynak kodu klonlanip okunmus, her bir pattern detaylica analiz edilmistir. Istanbul MCP icin en degerli referans kaynagidir.

## 3. Istanbul MCP Icin Onerilen Tool Akisi

### "Kadikoy RIhtim'dan Sogutlucesme'ye nasil giderim?"

Istanbul MCP'de tool'lar calisir hale geldiginde akis su sekilde olacak:

```
Adim 1: istanbul_nearby(40.9924, 29.0249, types=["bus_stop","metro"], radius=300)
  -> RIHTIM duragi (0m)
  -> KADIKOY metrobus duragi (49m)

Adim 2: istanbul_stops_for_line("34A")
  -> Sogutlucesme, Uzuncayir, ... listesi

Adim 3: istanbul_transit_line_info("34A")
  -> 34A: METROBUS, Cevizlibag - Siritlibesme

Adim 4 (opsiyonel): istanbul_traffic_status(district="Kadikoy")
  -> Trafik yogunlugu bilgisi

CLAUDE SENTEZI:
  "Kadikoy RIhtim'dan Kadikoy metrobus duruguna yuruyun (50m).
   34A metrobusune binin, Sogutlucesme'de inin.
   Yolculuk yaklasik 5-10 dakika surer."
```

### Gerekli Tool'lar

| Tool | Input | Output | Veri Kaynagi |
|------|-------|--------|-------------|
| `istanbul_nearby` | lat, lon, types, radius | Mesafeye gore siralanmis yerler | SQLite RTree + IETT duraklar |
| `istanbul_transit_line_info` | line_code | Hat adi, tarife, uzunluk | IETT SOAP `GetHat_json` |
| `istanbul_stops_for_line` | line_code | Sırali durak listesi | GTFS SQLite (stop_times) |
| `istanbul_search_datasets` | query | Dataset listesi | CKAN DataStore |
| `istanbul_traffic_status` | district, bbox | Trafik indeksi | REST XML |

### Eksik Olan Fonksiyonlar (MVP'de Cozulecek)

| Eksik | Cozum | Kaynak |
|-------|-------|--------|
| **Hat-durak iliskisi** (hangi hat hangi duraktan gecer) | GTFS stop_times.csv SQLite'a yuklenecek | ~26 MB CSV |
| **Lokasyon adindan koordinat** (RIhtim -> 40.9924) | IETT durak adi + ilce eslesmesi | 15.148 durak |
| **Rota planlama** (A'dan B'ye nasil gidilir) | GTFS routing algoritmasi | v0.2+ |
| **Anlik metrobus konumu** | Ayri bir sistem (UYM) | Metrobus IETT verisinde yok |

---

## 4. Referans Projelerden Alinan Dersler

### 4.1 Tool Tanimlama

**Iyi:**
```python
@mcp.tool(name="istanbul_nearby", annotations={"readOnlyHint": True})
async def istanbul_nearby(lat: float, lon: float, types: list[str] = None, radius: int = 500) -> str:
    """Bir koordinata yakin sehir nesnelerini bulur"""
    ...
```

**Kotu:**
```typescript
// JSON.stringify dondurmek - LLM'in yorumlamasi zor
return { content: [{ type: "text", text: JSON.stringify(data) }] };
```

### 4.2 Response Formati

- **Markdown** LLM icin JSON'dan daha iyidir (Zurich tercihi)
- **Source + Freshness** bilgisi her cevapta olmali
- **Summary** ile baslayip detaya gecmeli

### 4.3 Veri Katmanlari

```
Tool Layer (Kullaniciya en yakin)
  |
Domain Service Layer (Is mantigi)
  |
Connector/Client Layer (API cagrilari)
  |
Cache Layer (SQLite / Redis)
  |
Source Layer (IBB API'leri)
```

### 4.4 Hata Yonetimi

```python
# Zurich patterni - merkezi hata yonetimi
def handle_api_error(e, context=""):
    if isinstance(e, httpx.HTTPStatusError):
        if status == 404: return f"{prefix}Kaynak bulunamadi."
        if status == 429: return f"{prefix}Cok fazla istek."
        if status == 503: return f"{prefix}Servis su an kullanilamiyor."
    return f"{prefix}{type(e).__name__}: {e}"
```

### 4.5 Performans

- **gtfs-mcp**: 30 sn in-memory cache GTFS-RT icin
- **Zurich**: Her cagrida canli API (cache yok)
- **Bizim tercihimiz**: TTL-based cache (freshness sistemi ile)

---

## 5. Sonuc: Istanbul MCP'nin Kullanici Akisi

Istanbul MCP calisirken kullanici hicbir sey bilmez. Sadece Claude'a sorar:

> "Kadikoy RIhtim'dan Sogutlucesme'ye nasil giderim?"

Claude arka planda:
1. MCP'ye baglanir, tool'lari gorur
2. `istanbul_nearby` ile yakin durak bulur
3. `istanbul_stops_for_line` ile hat bilgisi alir  
4. `istanbul_traffic_status` ile trafik durumunu kontrol eder
5. Tumunu birlestirip kullaniciya soyler

Kullanici sadece dogal dilde sorar, Claude + MCP gerisini halleder. Bu, diger tum referans projelerin de calisma prensibidir.
