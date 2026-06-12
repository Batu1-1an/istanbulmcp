# İstanbul İBB Açık Veri MCP Server — Kapsamlı Proje Raporu

**Tarih:** 2026-06-09
**Versiyon:** 1.0
**Durum:** Planlama / Araştırma tamam

---

## 1. Yönetici Özeti

Bu rapor, İstanbul Büyükşehir Belediyesi'nin (İBB) açık veri portalını Model Context Protocol (MCP) üzerinden AI ajanlarına açacak bir MCP server'ın fizibilite, mimari ve uygulama planını kapsar.

**Ana Bulgu:** İstanbul İBB için özel bir MCP server bulunmamaktadır. İzmir'in halihazırda iki farklı MCP server'ı (`IzmirMCP`, `izmir-ulasim-mcp`) varken, Türkiye'nin en büyük şehri ve en zengin açık veri portalına sahip İstanbul bu alanda boşluktadır. Mevcut tek alternatif, generic CKAN MCP server'ıdır ancak bu, İBB'nin anlık SOAP servislerine erişemez.

**Öneri:** TypeScript + `@modelcontextprotocol/sdk` ile, `soap` npm paketi kullanılarak İBB SOAP servislerini de kapsayan, GTFS verisini SQLite'da cache'leyen, Streamable HTTP transport ile Railway'de host edilen bir İstanbul İBB MCP server geliştirilmesi.

---

## 2. Problem Tanımı

### 2.1 Mevcut Durum

İstanbul Büyükşehir Belediyesi, `data.ibb.gov.tr` adresinde CKAN tabanlı bir açık veri portalı işletmektedir. Portalda:
- **542** veri seti
- **41** API'ye sahip veri seti (REST + SOAP karışımı)
- Yüzlerce CSV/Excel/GeoJSON indirilebilir veri

Bu verilere AI ajanlarının (Claude, Cursor, ChatGPT vb.) standart bir yöntemle erişmesini sağlayacak bir MCP server bulunmamaktadır.

### 2.2 Karşılaştırmalı Boşluk Analizi

| Şehir | MCP Server | Durum |
|---|---|---|
| İzmir | `halilcengel/IzmirMCP` | ✅ 6 ulaşım türü, npm'de yayında |
| İzmir | `ogulcanakca/izmir-ulasim-mcp` | ✅ Python, ESHOT odaklı |
| New York | `jdamcd/gtfs-mcp` | ✅ MTA, config-driven |
| Boston | `cubismod/mbta-mcp` | ✅ 20+ tool, trip planning |
| Madrid | `dieguezz/mcp-madrid-public-transport` | ✅ Metro + EMT + Cercanías |
| Hong Kong | `rxtech-lab/hk-transportation-mcp` | ✅ Go + PostGIS |
| İsviçre | `malkreide/swiss-transport-mcp` | ✅ SOAP/XML çözümü |
| **İstanbul** | **❌ Yok** | **Boşluk** |

### 2.3 Potansiyel Kullanıcı Senaryoları

Bir AI asistanının İstanbul İBB MCP ile cevaplayabileceği sorular:

- "34A hattının tüm duraklarını göster"
- "Kadıköy Meydan'a en yakın durak neresi?"
- "Bugün İstanbul'da trafik yoğun mu?"
- "Kadıköy'de boş otopark var mı?"
- "Metro seferleri aksıyor mu?"
- "Üsküdar'da su kesintisi var mı?"
- "Bugün hava kalitesi nasıl, dışarı çıkılır mı?"
- "Yakınımdaki İsbike istasyonunda bisiklet var mı?"
- "15 numaralı duraktan hangi hatlar geçer?"

---

## 3. Veri Kaynakları Analizi

### 3.1 CKAN API (REST/JSON)

İBB'nin açık veri portalı CKAN (Comprehensive Knowledge Archive Network) yazılımını kullanır. CKAN, dünyada yaygın olarak kullanılan bir açık veri portalı yazılımıdır (ABD, İngiltere, Kanada, Avrupa Birliği vb.).

- **Base URL:** `https://data.ibb.gov.tr/api/3/action/`
- **Protokol:** REST/JSON
- **Auth:** Gerekmez (public veriler)
- **Sorgulama:** `package_list`, `package_show`, `datastore_search_sql`

**Örnek:**
```bash
# Tüm veri setlerini listele
GET https://data.ibb.gov.tr/api/3/action/package_list

# SQL ile GTFS durakları sorgula
GET https://data.ibb.gov.tr/api/3/action/datastore_search_sql?sql=SELECT * FROM "resource_id" WHERE the_geom LIKE '%Kadıköy%'
```

### 3.2 SOAP Web Servisleri (XML)

İBB'nin anlık verileri SOAP (Simple Object Access Protocol) üzerinden sunulur. SOAP, REST'ten önceki nesil web servis protokolüdür ve XML mesajlaşma kullanır.

| Servis | Endpoint | Veri |
|---|---|---|
| İETT Durak/Hat | `api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl` | Tüm duraklar, hatlar, güzergahlar |
| İETT Filo/Sefer | `api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl` | **Anlık** otobüs konumları |
| İETT Duyuru | İETT web servisi | **Anlık** sefer iptalleri |
| Trafik | Trafik web servisi | **Anlık** trafik indeksi |
| Hava Kalitesi | Çevre web servisi | **Anlık** PM/NO2 ölçümleri |

### 3.3 GTFS Verisi (CSV, CKAN DataStore)

İETT, standart GTFS (General Transit Feed Specification) formatında toplu taşıma verisi yayınlar.

| Dosya | Boyut | İçerik |
|---|---|---|
| `agency.csv` | 114 B | Kurum bilgisi |
| `calendar.csv` | 232 B | Sefer takvimi |
| `routes.csv` | 812 KB | Tüm hatlar (800+ satır) |
| `trips.csv` | 5.8 MB | Tüm seferler |
| `stops.csv` | 1.5 MB | Tüm duraklar (enlem/boylam) |
| `stop_times.csv` | ~26 MB | Durak-saat eşleşmeleri |

GTFS verisi CKAN DataStore üzerinden SQL ile sorgulanabilir ve düzenli güncellenir (son güncelleme: Mart 2026).

### 3.4 Metro İstanbul Web Servisleri

Metro İstanbul'a ait 12+ ayrı web servisi:

- İstasyon Bilgi Listesi
- Raylı Sistem Grup Listesi
- Hat/İstasyon Yön Bilgisi
- Sefer Tarifeleri
- Bilet Fiyat Listesi
- Ağ Haritası
- Devam Eden Projeler
- Hat/Yolcu İstatistikleri

### 3.5 Diğer Web Servisleri

- **İSPARK:** Otopark listesi ve detay bilgileri
- **İsbike:** Bisiklet istasyon listesi ve anlık durum
- **Trafik İndeksi:** Anlık trafik yoğunluğu
- **Hava Kalitesi:** Anlık ölçüm sonuçları
- **Hal Ürünleri Fiyatları:** Günlük hal fiyatları
- **Su Kesintileri:** İlçe/mahalle bazlı anlık kesintiler

---

## 4. SOAP Engeli ve Çözümü

### 4.1 SOAP Neden Engel?

SOAP, REST'e göre daha karmaşıktır:
- XML mesajlaşma (JSON değil)
- WSDL (Web Services Description Language) gerektirir
- namespace yönetimi
- Gece 00:15'te kapanma (hakanatak/dataibbgovtr notu)
- Yavaş yanıt süreleri

### 4.2 Karşılaştırmalı SOAP Çözümleri

Araştırma kapsamında üç farklı SOAP çözümü incelenmiştir:

#### A. swiss-transport-mcp (Python, FastMCP) — Manuel XML

```python
# xml.etree.ElementTree ile namespace-aware parsing
def _xpath(path: str) -> str:
    def replace_tag(m):
        tag = m.group(0)
        if tag in (".", "..", ""):
            return tag
        return _qn(tag)
    return re.sub(r'[a-zA-Z_:][\w:]*', replace_tag, path)

def _text(el: ET.Element, path: str) -> str | None:
    found = el.find(_xpath(path))
    return found.text if found is not None and found.text else None
```

- **Artı:** Tam kontrol, 115 test, production-ready
- **Eksi:** ~200 satır XML işleme kodu, İsviçre'ye özel
- **Kaynak:** `malkreide/swiss-transport-mcp` (1 star, Python)

#### B. hakanatak/dataibbgovtr (Node.js, Express) — `soap` npm paketi ✅

```javascript
const soap = require('soap');
const url = 'https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl';

soap.createClient(url, function(err, client) {
    client.GetFiloAracKonum_json({}, function(err, result) {
        const data = JSON.parse(result.GetFiloAracKonum_jsonResult);
        // → anlık otobüs konumları (GeoJSON)
    });
});
```

- **Artı:** 5 satır kod, WSDL otomatik parse, İBB'ye özel yazılmış
- **Eksi:** SOAP kapanma saatine dikkat edilmeli
- **Kaynak:** `hakanatak/dataibbgovtr` (38 star, JavaScript)

#### C. Madrid Transport MCP (TypeScript) — SOAP'ı erteleme

```
CRTM SOAP için: "Complexity: High. Defer to Phase 2. Not MVP."
```

- **Artı:** Hızlı MVP
- **Eksi:** Anlık veri yok
- **Kaynak:** `dieguezz/mcp-madrid-public-transport` (5 star, TypeScript)

### 4.3 Seçilen Çözüm: `soap` npm paketi

İstanbul İBB MCP için `soap` npm paketi en uygun çözümdür:

```typescript
// clients/soap.ts
import { createClientAsync } from 'soap';

const WSDL = {
  filo: 'https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl',
  hat:  'https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl',
};

export async function getBusLocations() {
  const client = await createClientAsync(WSDL.filo);
  const [result] = await client.GetFiloAracKonum_jsonAsync({});
  return JSON.parse(result.GetFiloAracKonum_jsonResult);
}
```

**Gerekçe:** `soap` paketi WSDL'den metodları otomatik çıkarır, XML detaylarını soyutlar. İBB'nin `*_json` suffix'li metodları sayesinde doğrudan JSON yanıt alınır.

---

## 5. Referans Projeler ve Alınan Dersler

### 5.1 IzmirMCP — `halilcengel/IzmirMCP`

| Özellik | Detay |
|---|---|
| **Dil** | TypeScript |
| **Dağıtım** | npm (`npx izmir-mcp`) |
| **Kapsam** | ESHOT, İZBAN, Metro, Tramvay, Vapur, Tren |
| **Veri** | CKAN + OpenAPI |
| **Tool sayısı** | 15+ |
| **Mimari** | Modüler: `api/` + `tools/` (her ulaşım türü ayrı) |
| **Transport** | stdio |
| **Boyut** | 52.3KB, 23 dosya |
| **Ders** | CKAN-based belediye verisi için kanıtlanmış pattern. Aynı yapı İstanbul'a uyarlanabilir. |

### 5.2 swiss-transport-mcp — `malkreide/swiss-transport-mcp`

| Özellik | Detay |
|---|---|
| **Dil** | Python (FastMCP) |
| **Kapsam** | OJP 2.0 (SOAP/XML), SIRI-SX (XML), CKAN, REST |
| **Tool sayısı** | 11 + 2 resources |
| **Test** | 115 test, respx mocking |
| **SOAP Çözümü** | `ojp_client.py` + XML template'lar + `xml.etree.ElementTree` |
| **Production** | v0.3.0 — 41/41 best-practice audit pass |
| **Ders** | SOAP/XML çözümü için referans mimari. `ojp_client.py` pattern'i. |

### 5.3 gtfs-mcp — `jdamcd/gtfs-mcp`

| Özellik | Detay |
|---|---|
| **Dil** | TypeScript |
| **Kapsam** | Herhangi bir GTFS sistemi (config-driven) |
| **Tool sayısı** | 11 |
| **Cache** | SQLite (GTFS schedule) |
| **Config** | JSON (sistem bazında) |
| **Ders** | GTFS handling için referans. `SQLite cache + config-driven` pattern. |

### 5.4 hakanatak/dataibbgovtr — İBB SOAP → REST bridge

| Özellik | Detay |
|---|---|
| **Dil** | JavaScript (Node.js, Express) |
| **Star** | 38 |
| **Kapsam** | İBB İETT: durak, garaj, filo, duyuru |
| **SOAP** | `soap` npm paketi ile WSDL'den otomatik client |
| **Çıktı** | GeoJSON (REST API) |
| **Deploy** | Heroku (`mekansal.herokuapp.com`) |
| **Ders** | **İBB SOAP çözümü için en doğrudan referans.** `soap` npm paketi + `*_json` metodları. |

### 5.5 Madrid Transport MCP — `dieguezz/mcp-madrid-public-transport`

| Özellik | Detay |
|---|---|
| **Dil** | TypeScript |
| **Kapsam** | Metro (REST), EMT (OAuth), Cercanías (GTFS-RT) |
| **GTFS** | 229MB compressed, SQLite cache |
| **Mimari** | DDD + Functional Programming |
| **SOAP** | CRTM SOAP → Phase 2'ye ertelenmiş |
| **Ders** | Hangi verinin önceliklendirileceği, SOAP'ın MVP dışı bırakılması kararı. |

### 5.6 Generic CKAN MCP — `ondata/ckan-mcp-server`

| Özellik | Detay |
|---|---|
| **Dil** | TypeScript |
| **Çalışma** | Herhangi bir CKAN portalı |
| **Tool** | `ckan_package_search`, `ckan_datastore_search_sql` |
| **Hosted** | `https://ckan-mcp-server.andy-pr.workers.dev/mcp` |
| **Test** | 200+ test |
| **Limit** | Sadece CKAN, SOAP/REST spesifik verilere erişemez |
| **Ders** | İBB CKAN kısmı için kullanılabilir ama anlık verileri kapsamaz. |

---

## 6. Önerilen Mimari

### 6.1 Proje Yapısı

```
istanbul-mcp/
├── src/
│   ├── server.ts                    # MCP server (McpServer + Streamable HTTP)
│   ├── config.ts                    # API URL'leri, port, auth
│   ├── clients/
│   │   ├── soap.ts                  # SOAP web servis katmanı (soap npm)
│   │   ├── ckan.ts                  # CKAN DataStore REST katmanı
│   │   └── rest.ts                  # Metro/İSPARK REST katmanı
│   ├── services/
│   │   ├── gtfs.ts                  # GTFS loader + SQLite cache
│   │   ├── geo.ts                   # Haversine + yakın durak
│   │   └── cache.ts                 # In-memory TTL cache
│   ├── tools/
│   │   ├── iett.ts                  # İETT durakları, hatları
│   │   ├── realtime.ts              # Anlık sefer/trafik
│   │   ├── metro.ts                 # Metro istasyon/sefer
│   │   ├── parking.ts               # İSPARK otopark
│   │   ├── environment.ts           # Hava kalitesi
│   │   └── city.ts                  # Su kesintisi, kültür
│   └── types/
│       └── index.ts                 # Zod şemaları
├── data/
│   └── cache.db                     # SQLite (GTFS cache)
├── package.json
├── tsconfig.json
└── railway.json                     # Railway deploy config
```

### 6.2 Veri Katmanları

| Katman | Teknoloji | Güncellik |
|---|---|---|
| GTFS Static | SQLite (`better-sqlite3`) | Günlük refresh |
| SOAP Anlık | `soap` npm + httpx | Her sorguda (gece kapanır) |
| CKAN DataStore | REST + SQL | Sorgu anında |
| Metro/İSPARK REST | `axios` | Sorgu anında |

### 6.3 Tool Tanımları (MVP)

```typescript
server.tool(
  "get_stops_by_line",
  "Bir hattaki tüm durakları listeler",
  { line_code: z.string() },
  async ({ line_code }) => {
    const stops = await gtfs.getStopsByLine(line_code);
    return { content: [{ type: "text", text: JSON.stringify(stops) }] };
  }
);

server.tool(
  "get_nearby_stops",
  "Koordinata göre en yakın durakları bulur",
  { lat: z.number(), lng: z.number(), radius: z.number().optional() },
  async ({ lat, lng, radius }) => {
    const stops = await geo.findNearbyStops(lat, lng, radius ?? 500);
    return { content: [{ type: "text", text: JSON.stringify(stops) }] };
  }
);

server.tool(
  "get_traffic_index",
  "İstanbul anlık trafik yoğunluk indeksi",
  { period: z.enum(["H", "D", "M", "Y"]).optional() },
  async ({ period }) => {
    const data = await soap.call("trafik", { period: period ?? "D" });
    return { content: [{ type: "text", text: JSON.stringify(data) }] };
  }
);
```

### 6.4 Streamable HTTP Transport (Remote Server)

```typescript
// server.ts
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { createMcpExpressApp } from "@modelcontextprotocol/sdk/server/express.js";

const server = new McpServer({
  name: "istanbul-mcp",
  version: "1.0.0",
});

// Tool kayıtları buraya...

const app = createMcpExpressApp(server);

// Auth middleware
app.use("/mcp", (req, res, next) => {
  const token = req.headers["authorization"]?.split(" ")[1];
  if (token !== process.env.BEARER_TOKEN) return res.status(401).end();
  next();
});

const PORT = parseInt(process.env.PORT || "3000", 10);
app.listen(PORT, () => {
  console.error(`İstanbul MCP running on port ${PORT}`);
});
```

---

## 7. Deployment

### 7.1 Platform: Railway

| İhtiyaç | Railway Karşılığı |
|---|---|
| SOAP çağrıları | ✅ Uzun süreç desteği |
| SQLite (30MB GTFS cache) | ✅ Disk persistence |
| HTTPS | ✅ Otomatik SSL |
| Domain | `ibb-mcp.up.railway.app` |
| Fiyat | $5/ay (Hobby) |
| Auth | `BEARER_TOKEN` env variable |

### 7.2 Claude Desktop Konfigürasyonu

```json
{
  "mcpServers": {
    "istanbul": {
      "url": "https://ibb-mcp.up.railway.app/mcp"
    }
  }
}
```

Kullanıcının hiçbir şey kurması gerekmez — sadece URL ekler.

---

## 8. Zorluklar ve Riskler

| Zorluk | Seviye | Çözüm | Ek Çaba |
|---|---|---|---|
| SOAP protokolü | 🟧 Orta | `soap` npm paketi ile soyutlama | 0.5 gün |
| SOAP gece kapanması | 🟧 Orta | Tool açıklamasına not düşme | 0 |
| GTFS 30MB cache | 🟧 Orta | SQLite + günlük refresh | 1 gün |
| SOAP yavaşlık | 🟧 Orta | Cache + timeout (30sn) | 0.5 gün |
| Koordinat dönüşümü | 🟧 Orta | `proj4js` kütüphanesi | 0.5 gün |
| GTFS-RT eksikliği | 🟨 Düşük | SOAP ile real-time, GTFS static ile tarife | Doğal |
| Auth | 🟨 Düşük | Railway env'de `BEARER_TOKEN` | 0.5 gün |
| Kitle sınırı (sadece İstanbul) | 🟨 Düşük | İstanbul nüfus ~20 milyon | Doğal |
| API değişikliği | 🟨 Düşük | İBB portal altyapısı güncelleniyor | İzleme |

### 8.1 SOAP Gece Kapanması

`hakanatak/dataibbgovtr` projesinin notu: *"SOAP servisleri her gece saat 00.15'ten sonra kapatılmaktadır."*

Bu, anlık veri tool'larının gece çalışmayacağı anlamına gelir. GTFS static verisi (tarifeler) çalışmaya devam eder. Tool açıklamasında belirtilmelidir.

---

## 9. Önceliklendirme ve Yol Haritası

### 9.1 Faz 1 (MVP) — 1 Hafta

| Adım | Süre |
|---|---|
| GTFS SQLite cache + stop/route sorgulama | 2 gün |
| SOAP katmanı (`soap` npm ile anlık sefer) | 1 gün |
| Metro/İSPARK REST tool'ları | 1 gün |
| Streamable HTTP + Railway deploy | 1 gün |
| Test + dökümantasyon | 1 gün |

**Toplam: ~6 gün**

### 9.2 Faz 2 (Extension)

| Özellik |
|---|
| Trafik indeksi anlık |
| Hava kalitesi anlık |
| Su kesintisi sorgulama |
| İsbike anlık durum |
| Koordinat dönüşümü (WGS84) |
| BEARER_TOKEN auth |

### 9.3 Faz 3 (Production)

| Özellik |
|---|
| OAuth 2.1 auth (Cloudflare Workers geçiş) |
| npm yayınlama (`npx istanbul-mcp`) |
| Otomatik GTFS refresh (cron) |
| Rate limiting |
| Monitoring (health endpoint) |

---

## 10. Stack Kararı

| Bileşen | Seçim | Gerekçe |
|---|---|---|
| **Dil** | TypeScript | IzmirMCP ile uyum, NPM dağıtımı |
| **MCP SDK** | `@modelcontextprotocol/sdk` | Resmi SDK |
| **HTTP** | Express + `createMcpExpressApp` | En geniş ekosistem |
| **Validation** | Zod | Endüstri standardı |
| **SOAP** | `soap` npm paketi | WSDL otomatik parse, 5 satır kod |
| **GTFS Cache** | `better-sqlite3` | 30MB için ideal |
| **HTTP Client** | `axios` + retry | SOAP/REST çağrıları |
| **Deploy** | Railway | SOAP + SQLite desteği, $5/ay |

---

## 11. Referanslar

### Projeler

| Proje | URL | Yıldız | İlgili Kısım |
|---|---|---|---|
| IzmirMCP | `github.com/halilcengel/IzmirMCP` | 3 ★ | Benzer belediye MCP mimarisi |
| dataibbgovtr | `github.com/hakanatak/dataibbgovtr` | 38 ★ | İBB SOAP → REST çözümü |
| swiss-transport-mcp | `github.com/malkreide/swiss-transport-mcp` | 1 ★ | SOAP/XML MCP pattern |
| gtfs-mcp | `github.com/jdamcd/gtfs-mcp` | 0 ★ | GTFS SQLite cache pattern |
| mcp-madrid-transport | `github.com/dieguezz/mcp-madrid-public-transport` | 5 ★ | SOAP erteleme stratejisi |
| ondata/ckan-mcp-server | `github.com/ondata/ckan-mcp-server` | - | CKAN generic MCP |
| ckan-mcp-server (mjanez) | `github.com/mjanez/ckan-mcp-server` | - | CKAN semantic search |
| ibb (R wrapper) | `github.com/berkorbay/ibb` | - | İBB CKAN R istemcisi |
| ibb (Go wrapper) | `github.com/ycd/ibb` | - | İBB CKAN Go istemcisi |
| IBB.Api (.NET) | `github.com/AydinAdn/IBB.Api` | 3 ★ | İBB SOAP .NET istemcisi |

### Dokümantasyon

| Kaynak | URL |
|---|---|
| İBB Açık Veri Portalı | `data.ibb.gov.tr` |
| CKAN API | `docs.ckan.org/en/latest/api/` |
| MCP Resmi Sitesi | `modelcontextprotocol.io` |
| MCP TypeScript SDK | `ts.sdk.modelcontextprotocol.io` |
| GTFS Referans | `gtfs.org` |
| SOAP npm paketi | `npmjs.com/package/soap` |
| FastMCP | `github.com/johnlambertz/fastmcp` |

### Teknik Arka Plan

| Kavram | Açıklama |
|---|---|
| **CKAN** | Açık veri portalı yazılımı, REST/JSON API |
| **SOAP** | Eski nesil web servis protokolü, XML mesajlaşma |
| **GTFS** | Toplu taşıma verisi standardı (Google Transit) |
| **MCP** | Model Context Protocol — AI araçları için standart protokol |
| **Streamable HTTP** | MCP remote transport (spec 2025-03-26) |

---

## 12. Ek: Veri Seti Envanteri (En Değerliler)

### Anlık / Gerçek Zamanlı (En Yüksek Değer)

| ID | Açıklama | Güncellik |
|---|---|---|
| `iett-gtfs-verisi` | Tüm İETT durakları, hatları, sefer saatleri (30MB) | Aylık/günlük |
| `sefer-gerceklesme-web-servisi` | Anlık otobüs sefer gerçekleşme oranı | Anlık (SOAP) |
| `istanbul-trafik-indeksi` | Anlık trafik yoğunluğu | Anlık (SOAP) |
| `hava-kalitesi-istasyon-olcum-sonuclari-web-servisi` | Anlık PM10/PM2.5/NO2 | Anlık (SOAP) |
| `isbike-stations-status-web-service` | Anlık bisiklet istasyon doluluk | Anlık (SOAP) |
| `iett-duyurular-web-servisi` | Sefer iptalleri, aksama bilgileri | Anlık (SOAP) |
| `istanbul-barajlari-gunluk-doluluk-oranlari` | Baraj doluluk | Günlük (CSV) |
| `istanbul-da-meydana-gelen-su-kesintileri` | Su kesintileri | Anlık (CKAN) |
| `hal-urunleri-ve-fiyatlari-web-servisi` | Güncel hal fiyatları | Günlük (SOAP) |

### Statik / Referans (Orta Değer)

| ID | Açıklama |
|---|---|
| `metro-istanbul-istasyon-bilgi-listesi` | Metro istasyon listesi |
| `metro-istanbul-sefer-tarifeleri-listesi-web-servisi` | Metro sefer saatleri |
| `ispark-otopark-listesi-web-servisi` | Tüm İSPARK otoparkları |
| `iett-otobus-duraklari-verisi` | Otobüs durakları (GeoJSON) |
| `deniz-ulasim-hatlari-vektor-verisi` | Şehir hatları güzergahları |
| `sehir-tiyatrolari-oyun-istatigi` | Tiyatro oyun ve seyirci |
| `kent-lokantalari-konumlari` | Kent lokantası konumları |
| `ibb-muzeleri-lokasyon-calisma-gun-ve-saatleri` | Müze bilgileri |
| `istanbul-halk-ekmek-bufe-konumlari-veri-seti` | Halk ekmek büfeleri |

---

## 13. Sonuç

İstanbul İBB MCP, hem teknik olarak yapılabilir hem de pazarda boşlukta olan bir projedir. İzmir'in iki farklı MCP'si varken İstanbul'un olmaması önemli bir eksikliktir.

**Anahtar bulgular:**

1. İBB verisi zengin ve çeşitlidir (542 veri seti, 41 API)
2. SOAP engeli `soap` npm paketi ile 5 satır kodda çözülmüştür (`hakanatak/dataibbgovtr` kanıtı)
3. Referans alınacak projeler mevcuttur (IzmirMCP, swiss-transport-mcp, gtfs-mcp)
4. Railway'de host etmek GTFS SQLite cache + SOAP çağrıları için idealdir
5. Toplam geliştirme süresi **~6 gün** olarak öngörülmektedir
6. Kullanıcı için kurulum gerektirmez: sadece URL ekle

**En büyük risk:** SOAP servislerinin gece 00:15'te kapanması, bu da anlık veri tool'larının gece çalışamayacağı anlamına gelir.
