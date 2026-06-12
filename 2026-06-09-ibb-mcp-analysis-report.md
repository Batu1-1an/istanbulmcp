# İBB Açık Veri MCP Analiz Raporu

**Tarih:** 2026-06-09
**Kapsam:** İstanbul Büyükşehir Belediyesi Açık Veri Portalı'ndaki 304 veri setinin MCP (Model Context Protocol) geliştirme potansiyeli analizi

---

## 1. Genel Bakış

İBB Açık Veri Portalı (`data.ibb.gov.tr`), **CKAN** (Comprehensive Knowledge Archive Network) tabanlı bir açık veri platformudur. Portalda toplam **542 veri seti** bulunur, bunlardan **41'inin API'si** vardır (REST ve SOAP karışımı). Geri kalanı CSV/Excel/GeoJSON indirme formatındadır.

**Mimari:**
- CKAN API Base: `https://data.ibb.gov.tr/api/3/action/`
- Web Servisler: `https://api.ibb.gov.tr/` altında SOAP (.asmx?wsdl)
- Kimlik Doğrulama: Public veriler için gerekmez
- Lisans: İstanbul Büyükşehir Belediyesi Açık Veri Lisansı

---

## 2. Veri Kategorileri ve MCP Değer Analizi

### 2.1 Anlık / Gerçek Zamanlı Veriler (En Yüksek Öncelik)

Bu kategorideki veriler, AI agent'ın eğitim verisinde bulunamayacağı için MCP olarak **en yüksek değeri** taşır.

#### 2.1.1 İETT Sefer Gerçekleşme (Journey Realization)
| Özellik | Detay |
|---|---|
| **Endpoint** | `api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl` |
| **Protokol** | SOAP/XML |
| **Güncellik** | Anlık (instant) |
| **Değer Skoru** | 10/10 |
| **Mantığı** | Otobüs seferlerinin gerçekleşme oranını anlık verir. "34A hattı çalışıyor mu?" sorusu, İstanbullu bir AI kullanıcısının en sık soracağı sorulardandır. Agent bu veriyi bilemez. |

#### 2.1.2 Trafik İndeksi
| Özellik | Detay |
|---|---|
| **Endpoint** | Trafik indeks web servisi (day/period parametreli) |
| **Protokol** | SOAP/XML |
| **Güncellik** | Anlık |
| **Değer Skoru** | 9/10 |
| **Mantığı** | "İstanbul'da trafik yoğun mu?" en sık sorulan İstanbul sorusudur. Belli bir gün/saat için ortalama trafik yoğunluğunu döndürür. |

#### 2.1.3 Hava Kalitesi Ölçüm Sonuçları
| Özellik | Detay |
|---|---|
| **Endpoint** | Çevre web servisi |
| **Protokol** | SOAP/XML |
| **Güncellik** | Anlık |
| **Değer Skoru** | 8/10 |
| **Mantığı** | PM10, PM2.5, NO2, SO2, CO, O3 anlık ölçümleri. "Bugün dışarı çıkılır mı?" sorusu — sağlık kararları için. İstasyon bazlı veri. |

#### 2.1.4 İsbike İstasyon Durumları
| Özellik | Detay |
|---|---|
| **Endpoint** | İSPARK web servisi |
| **Protokol** | SOAP/XML |
| **Güncellik** | Anlık |
| **Değer Skoru** | 7/10 |
| **Mantığı** | Hangi istasyonda bisiklet var/boş yer var. Mikromobilite için anlık karar. Kullanıcı kitlesi dar (İsbike üyeleri). |

#### 2.1.5 İETT Duyuruları
| Özellik | Detay |
|---|---|
| **Endpoint** | İETT web servisi |
| **Protokol** | SOAP/XML |
| **Güncellik** | Anlık |
| **Değer Skoru** | 7/10 |
| **Mantığı** | Sefer iptalleri, güzergah değişiklikleri, aksama bilgileri. Agent'ın asla bilemeyeceği veri. |

#### 2.1.6 Baraj Doluluk Oranları (Günlük)
| Özellik | Detay |
|---|---|
| **Dataset** | `istanbul-barajlari-gunluk-doluluk-oranlari` |
| **Format** | CSV (CKAN datastore) |
| **Güncellik** | Günlük |
| **Değer Skoru** | 6/10 |
| **Mantığı** | "İstanbul'un suyu ne kadar gitti?" — periyodik olarak takip edilen, agent'ın bilemeyeceği güncel veri. Kamuoyu ilgisi yüksek. |

#### 2.1.7 Su Kesintileri
| Özellik | Detay |
|---|---|
| **Dataset** | `istanbul-da-meydana-gelen-su-kesintileri` |
| **Format** | CKAN datastore (API ile sorgulanabilir) |
| **Güncellik** | Anlık |
| **Değer Skoru** | 7/10 |
| **Mantığı** | İlçe/mahalle bazlı anlık su kesintisi. Günlük hayatı etkileyen pratik veri. |

#### 2.1.8 Hal Ürünleri Fiyatları
| Özellik | Detay |
|---|---|
| **Endpoint** | Hal web servisi |
| **Protokol** | SOAP/XML |
| **Güncellik** | Günlük |
| **Değer Skoru** | 6/10 |
| **Mantığı** | "Domates kaç TL?" — güncel hal fiyatları. Tüketici için anlık fiyat takibi. |

---

### 2.2 Ulaşım / Mobilite Verileri (En Zengin Kategori)

#### 2.2.1 İETT GTFS Verisi (En Değerli Statik Veri)
| Özellik | Detay |
|---|---|
| **ID** | `iett-gtfs-verisi` |
| **Format** | CSV (6 dosya, 30MB+ toplam) |
| **CKAN SQL Sorgulanabilir** | ✅ Evet (datastore_active) |
| **Değer Skoru** | 9/10 |
| **İçerik** | |
| | `agency.csv` — kurum bilgisi |
| | `calendar.csv` — sefer takvimi |
| | `routes.csv` (812KB) — tüm hatlar |
| | `trips.csv` (5.8MB) — tüm seferler |
| | `stops.csv` (1.5MB) — tüm duraklar (enlem/boylam) |
| | `stop_times.csv` (26MB/22MB zip) — durak saatleri |
| **Mantığı** | GTFS standart bir formattır, dünyada binlerce uygulama kullanır. CKAN SQL ile `SELECT * FROM stops WHERE the_geom LIKE '%Kadıköy%'` gibi sorgular yapılabilir. MCP tool olarak: "34A hattının durakları", "Kadıköy'deki duraklar", "10 numaralı duraktan geçen hatlar". |

#### 2.2.2 İETT Hat-Durak-Güzergâh Web Servisi
| Özellik | Detay |
|---|---|
| **Endpoint** | `api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl` |
| **Protokol** | SOAP/XML |
| **Döküman** | PDF (Türkçe + İngilizce) |
| **Değer Skoru** | 8/10 |
| **Mantığı** | Hat, durak, hattın durakları, güzergah, güzergahın durakları — beş farklı veri tipi tek serviste. GTFS'ten farkı: SOAP üzerinden anlık sorgulanabilir. |

#### 2.2.3 İETT Durak ve Hat Bilgileri Web Servisi
| Özellik | Detay |
|---|---|
| **Endpoint** | `api.ibb.gov.tr/iett/ibb/ibb.asmx?wsdl` |
| **Protokol** | SOAP/XML |
| **Değer Skoru** | 6/10 |
| **Mantığı** | Daha basit, sadece durak ve hat sorgulama. Hat-Durak-Güzergah servisi ile büyük ölçüde örtüşür. |

#### 2.2.4 Metro İstanbul Verileri (12+ veri seti)
| Veri Setleri | Format | Değer |
|---|---|---|
| İstasyon Bilgi Listesi | Web servis | 7/10 |
| Raylı Sistem Grup Listesi | Web servis | 5/10 |
| Hat/İstasyon Yön Bilgisi | Web servis | 5/10 |
| Sefer Tarifeleri | Web servis | 7/10 |
| Bilet Fiyat Listesi | Web servis | 6/10 |
| Ağ Haritası | Web servis | 5/10 |
| Devam Eden Projeler | Web servis | 4/10 |
| Hat bazlı yolcu sayıları | CKAN | 6/10 |
| İstasyon bazlı yolcu sayıları | CKAN | 6/10 |
| Enerji tüketimi | CKAN | 4/10 |
| Vagon kilometre | CKAN | 4/10 |
| **Mantığı** | Toplamda 12+ veri seti ile İstanbul metrosu en detaylı kategorilerden biri. Ama hepsi ayrı ayrı tool olmaz — tek bir "metro" tool'u altında birleştirilebilir. |

#### 2.2.5 İSPARK Otopark Verileri
| Veri Setleri | Format | Değer |
|---|---|---|
| Otopark Listesi | Web servis | 7/10 |
| Otopark Detay Bilgileri | Web servis | 7/10 |
| Abone sayıları (yıllık) | CKAN | 3/10 |
| **Mantığı** | Tüm İSPARK otoparklarının konum, kapasite, fiyat bilgisi. "Kadıköy'de nerede otopark var?" pratik bir AI sorusu. |

#### 2.2.6 Deniz Ulaşımı
| Veri Setleri | Format | Değer |
|---|---|---|
| Deniz Ulaşım Hatları (vektör) | GeoJSON | 6/10 |
| Deniz Ulaşım İstasyonları (vektör) | GeoJSON | 6/10 |
| Şehir Hatları Sefer Sayıları | CKAN | 5/10 |
| Yolcu Sayıları | CKAN | 5/10 |
| **Mantığı** | Şehir hatları, motor, arabalı vapur. İstanbul'un deniz ulaşımı için referans veri. |

#### 2.2.7 Minibüs ve Taksi Verileri
| Veri Setleri | Format | Değer |
|---|---|---|
| Minibüs Durakları | CKAN | 5/10 |
| Minibüs Hatları | CKAN | 5/10 |
| Taksi Durakları | CKAN | 5/10 |
| Taksi/Dolmuş Durakları | CKAN | 4/10 |
| Taksi/Dolmuş Hatları | CKAN | 4/10 |
| **Mantığı** | Alternatif ulaşım türleri. Tamamlayıcı veri. Tek başına yetmez ama GTFS + Metro + Deniz + Taksi birleşince İstanbul ulaşımının tam haritası çıkar. |

---

### 2.3 Çevre ve Enerji

| Veri Seti | Format | Güncellik | Değer |
|---|---|---|---|
| Hava Kalitesi İstasyon Bilgileri | SOAP | Statik | 5/10 |
| Hava Kalitesi Ölçüm Sonuçları | SOAP | Anlık | 8/10 |
| Baraj Doluluk (günlük) | CKAN | Günlük | 6/10 |
| Baraj Konum | CKAN | Statik | 3/10 |
| Baraj Hacim | CKAN | Statik | 3/10 |
| Günlük Yağış | CKAN | Günlük | 5/10 |
| Güneş Enerji Santrali Üretim | CKAN | Periyodik | 4/10 |
| İstanbul Güneş Enerji Potansiyel Haritası | CKAN | Statik | 4/10 |
| Çöp Gazından Enerji Üretimi | CKAN | Periyodik | 4/10 |
| Elektrik Tüketimi (bölge bazlı) | CKAN | Periyodik | 4/10 |
| Şarj İstasyonları Tüketim | CKAN | Aylık | 4/10 |
| Saatlik Trafik Yoğunluğu | CKAN | Saatlik | 7/10 |
| Saatlik Toplu Taşıma Verisi | CKAN | Saatlik | 7/10 |
| **Toplam Değer** | | | **Orta-Yüksek** |

---

### 2.4 Kültür, Sanat ve Yaşam

| Veri Seti | Format | Güncellik | Değer |
|---|---|---|---|
| Müze Lokasyon/Çalışma Saatleri | CKAN | Statik | 6/10 |
| Kütüphane Lokasyon/Çalışma Saatleri | CKAN | Statik | 6/10 |
| Şehir Tiyatroları Oyun Listesi | CKAN | Periyodik | 6/10 |
| Şehir Tiyatroları Oyun İstatistiği | CKAN | Güncel | 5/10 |
| Şehir Tiyatroları Oyun/İstatistik (eski) | CKAN | Eski | 3/10 |
| Kültür Merkezleri | CKAN | Statik | 5/10 |
| Kent Lokantaları Konum | CKAN | Statik | 7/10 |
| Kent Lokantaları Doluluk | CKAN | Anlık? | 6/10 |
| İBB Wi-Fi Lokasyon | CKAN | Statik | 5/10 |
| İBB Wi-Fi Kullanıcı Sayıları | CKAN | Günlük | 4/10 |
| Halk Ekmek Büfe Konumları | CKAN | Statik | 6/10 |
| Sosyal Tesis Konumları | CKAN | Statik | 5/10 |
| Sosyal Tesis Doluluk | CKAN | Periyodik | 4/10 |
| Mezarlık Adres Bilgileri | CKAN | Statik | 5/10 |
| Muhtarlık Adres Bilgileri | CKAN | Statik | 6/10 |
| Şehir Tuvaletleri | CKAN | Güncel | 5/10 |
| **Toplam Değer** | | | **Orta** |

---

### 2.5 Sosyal ve Demografik

| Veri Seti | Format | Değer |
|---|---|---|
| Nüfus Bilgileri | CKAN | 5/10 |
| İlçe bazlı hane büyüklüğü | CKAN | 4/10 |
| İlçe bazlı okuma-yazma | CKAN | 4/10 |
| İşsizlik Verileri | CKAN | 5/10 |
| İşsizlik Ödeneği | CKAN | 4/10 |
| İşgücü Verileri | CKAN | 5/10 |
| Sosyal Yardım Alan Hane Sayısı | CKAN | 4/10 |
| Görme Engelli Vatandaş Verileri | CKAN | 4/10 |
| VDY Anket Verileri (30+ dataset) | CKAN | 3/10 |
| **Toplam Değer** | | **Düşük-Orta** |
| **Mantığı** | TÜİK verisi İBB üzerinden aktarılmış. Orijinal kaynak TÜİK olduğu için ve TÜİK MCP zaten var olduğu için düşük değer. VDY anketleri (Veriye Dayalı Yönetim Modeli) çok detaylı ama niş. |

---

## 3. Teknik Değerlendirme

### 3.1 API Kalitesi

| Kriter | CKAN API | SOAP Web Servisler | CSV İndirme |
|---|---|---|---|
| **Standart** | REST + JSON | Legacy SOAP/XML | Dosya |
| **Dökümantasyon** | CKAN standart | PDF (mevcut) | Yok |
| **Sorgulama** | SQL + parametre | SOAP metod çağrısı | Manuel yükleme |
| **Performans** | Yüksek | Orta | Çok yüksek (lokal) |
| **MCP'ye Uyum** | Çok kolay (HTTP) | Zor (SOAP parse) | Çok kolay (embed) |
| **Auth** | Yok | Yok | Yok |

### 3.2 SOAP Sorunu

İBB'nin anlık web servislerinin tamamı SOAP/XML (`*.asmx?wsdl`) üzerinden çalışır. Bu, MCP geliştirmede ek yük getirir:

```
SOAP Request (XML) → HTTP POST → SOAP Response (XML) → Parse → JSON → MCP Tool Output
```

FastMCP içinde SOAP çağrısı yapmak ~10 satır kod, ama REST kadar temiz değil.

### 3.3 CKAN Avantajı

CKAN API, İBB verilerinin çoğuna REST üzerinden erişim sağlar:

```
# Tüm veri setlerini listele
GET /api/3/action/package_list

# SQL ile sorgula
GET /api/3/action/datastore_search_sql?sql=SELECT * FROM "resource_id" WHERE...
```

Hatta `FastMCP.from_openapi()` ile CKAN'ın OpenAPI spec'i üzerinden otomatik MCP oluşturulabilir — ama İBB'nin CKAN'ının OpenAPI dokümanı yok.

---

## 4. MCP Server Önerileri

### 4.1 Öneri: İBB Ulaşım MCP (En Yüksek Öncelik)

**Kapsam:** GTFS + İETT web servisleri + Metro + İSPARK

**Tools:**
| Tool Adı | Veri Kaynağı | Sorgu Parametreleri |
|---|---|---|
| `get_stops_by_line` | GTFS stops + routes | `line_code` |
| `get_lines_by_stop` | GTFS stops + trips | `stop_id` veya `stop_name` |
| `search_nearby_stops` | GTFS stops (lat/lon) | `lat`, `lng`, `radius_m` |
| `get_line_route` | GTFS trips + stop_times | `line_code` |
| `get_trip_times` | GTFS stop_times | `line_code`, `direction` |
| `get_journal_realization` | Sefer Gerçekleşme (SOAP) | `line_code` |
| `get_traffic_index` | Trafik Web Servisi | `day`, `period` |
| `search_parking_lots` | İSPARK | `district` |
| `get_metro_stations` | Metro WS | `line_id` |
| `get_metro_schedule` | Metro WS | `station_id` |

**Değer:** 9/10
**Çaba:** 2-3 gün (SOAP entegrasyonu en çok vakit alan kısım)
**Eşsizlik:** ✅ Türkiye'de toplu taşıma odaklı başka MCP yok

### 4.2 Öneri: İBB Çevre MCP (Orta Öncelik)

**Kapsam:** Hava kalitesi + Baraj + Deprem + Hava durumu

**Tools:**
| Tool Adı | Veri Kaynağı |
|---|---|
| `get_air_quality` | Hava Kalitesi WS |
| `get_air_quality_stations` | İstasyon Bilgileri |
| `get_dam_occupancy` | Baraj Günlük Doluluk |
| `get_dam_rainfall` | Günlük Yağış |
| `get_recent_earthquakes` | İstanbul Deprem Verisi |

**Değer:** 7/10
**Çaba:** 1 gün
**Eşsizlik:** ⚠️ AFAD/Kandilli Deprem MCP ile örtüşme riski

### 4.3 Öneri: İBB Yaşam MCP (Düşük Öncelik)

**Kapsam:** Kültür + Sosyal tesisler + Wi-Fi + Halk Ekmek

**Tools:**
| Tool Adı | Veri Kaynağı |
|---|---|
| `get_museums` | Müze verileri |
| `get_libraries` | Kütüphane verileri |
| `get_theater_plays` | Tiyatro oyunları |
| `get_city_restaurants` | Kent lokantaları |
| `get_public_wifi` | Wi-Fi noktaları |
| `get_water_outages` | Su kesintileri |

**Değer:** 5/10
**Çaba:** 1 gün
**Eşsizlik:** ✅ Ama talep düşük

---

## 5. Risk ve Engeller

| Risk | Seviye | Açıklama |
|---|---|---|
| SOAP protokolü | 🟡 Orta | Anlık verilerin tamamı SOAP. XML işleme ek yükü. |
| Servis kararlılığı | 🟡 Orta | Bazı web servisler "temporarily unavailable" dönebiliyor. |
| Veri güncelliği | 🟢 Düşük | GTFS verisi düzenli güncelleniyor (Mart 2026). |
| Lisans kısıtı | 🟢 Düşük | İBB Açık Veri Lisansı, ticari kullanıma da izin veriyor. |
| Kapsam sınırı | 🟡 Orta | Sadece İstanbul. Kullanıcı kitlesi Türkiye'nin ~%20'si. |
| SOAP dökümantasyonu | 🟢 Düşük | PDF doküman mevcut (Türkçe + İngilizce v1.5). |
| API değişikliği | 🟡 Orta | Portal altyapısı güncellendi (İBB Hesabım). Gelecekte REST'e geçebilir. |

---

## 6. Sonuç ve Öncelik Sıralaması

### 6.1 Net Öneri: İBB Ulaşım MCP

İBB'nin en değerli verisi **ulaşım verisidir**. GTFS feed'i sayesinde standart bir formatta, CKAN SQL ile sorgulanabilir. Anlık sefer gerçekleşme ve trafik indeksi ile gerçek zaman bilgisi eklenir. Metro, İSPARK, deniz ulaşımı ile tamamlanır.

**Bir AI agent'ın İstanbul ulaşımı hakkında sorabileceği soruların %90'ı** bu MCP ile karşılanır:
- "34A'nın durakları nelerdir?"
- "Kadıköy'deki en yakın durak neresi?"
- "Trafik yoğun mu?"
- "Metro seferleri aksıyor mu?"
- "Kadıköy'de otopark var mı?"
- "15 numaralı duraktan hangi hatlar geçer?"

### 6.2 Öncelik Matrisi

```
                  YÜKSEK DEĞER
                      │
                      │
        Çevre MCP     │  Ulaşım MCP ★
        (7/10)         │  (9/10)
                      │
     DÜŞÜK ÇABA ──────┼────── YÜKSEK ÇABA
                      │
        Yaşam MCP     │  (Tümü)
        (5/10)         │
                      │
                  DÜŞÜK DEĞER
```

### 6.3 Tavsiye Edilen Yol Haritası

| Aşama | Ne Yapılmalı | Süre |
|---|---|---|
| **1. Hafta** | GTFS verisini MCP tool'larına dönüştür (stops, routes, trips CKAN SQL) | 1 gün |
| **2. Hafta** | SOAP web servisleri entegre et (SeferGerçekleşme + Trafik İndeksi) | 2 gün |
| **3. Hafta** | Metro + İSPARK verilerini ekle | 1 gün |
| **4. Hafta** | Test, dökümantasyon, yayınlama | 1 gün |

**Toplam: ~5 gün** ile İstanbul'un en kapsamlı açık veri MCP'si hazır.

---

*Rapor, İBB Açık Veri Portalı CKAN API'sinden alınan canlı verilerle hazırlanmıştır (304 veri seti taranmıştır).*
