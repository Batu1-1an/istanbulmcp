# İstanbul MCP — 100 Senaryo Test Analiz Raporu

**Tarih:** 2026-06-13  
**Test Sırası:** Gece ~04:00-05:00 TSİ  
**Toplam API Çağrısı:** ~90 (16 tool × çeşitli varyasyonlar)

---

## 1. Genel Başarı Oranı

| Durum | Sayı | Oran |
|---|---|---|
| ✅ `ok: true` | ~75 | %83 |
| ❌ `ok: false` | ~15 | %17 |

### Hata Dağılımı

| Hata Türü | Sayı | Kaynak |
|---|---|---|
| **IETT Rate Limit** | 5 | IETT SOAP (concurrent isteklerde) |
| **Validation Error (radius_m > 5000)** | 1 | Air Quality (10.000m denendi) |
| **Validation Error (unknown neighborhood)** | 2 | Neighborhood Profile (Bomonti, Gülbahar) |
| **Validation Error (bbox min_lon > max_lon)** | 1 | BBOX ([0,0,0,0]) |
| **Validation Error (unknown place)** | 1 | City Services (Gülbahar) |

---

## 2. Tool Bazında Analiz

### 🚗 Traffic (`istanbul_traffic_status`) — ✅ 5/5

- **Hep başarılı** — basit, güvenilir
- ❌ **Limitasyon:** Şehir geneli indeks, yol bazlı veri yok
- ❌ `does_not_support` her çağrıda aynı uyarı — gereksiz tekrar

### 🅿️ Parking (`istanbul_parking_nearby`) — ✅ 10/10

- ISPark API çok sağlam — canlı doluluk verisi
- ⚠️ `is_open: 0` ama 24 saat çalışan otoparklar da 0 dönüyor (gece testi)
- ⚠️ `empty_capacity: 1` çoğu otoparkta sabit — gerçek doluluk mu, varsayılan mı belli değil
- ✅ 0 sonuç dönen (Kilyos) doğru çalışıyor

### 🚇 Metro (`istanbul_metro_stations_nearby`) — ✅ 8/8

- Sağlam, 24 saat cache ile hızlı
- ⚠️ T3 tramvay hattı da "metro" olarak dönüyor (hatta T1, TF1 de)
- ❌ Metro için sefer durumu/dk bilgisi yok

### 🌫️ Hava Kalitesi (`istanbul_air_quality_nearby`) — ✅ 6/7

- ❌ **Tüm istasyonlarda AQI = null** — veri Mayıs 2026'dan beri güncel değil
- ⚠️ `freshness: unknown` (kaynak güncelleme zamanı yok)
- ⚠️ Validation: radius_m > 5000 hata veriyor (10.000 deneyince)
- ❌ **Veri kaynağı ölü mü?** 1 aydır AQI gelmiyor

### 🏘️ Mahalle Profili (`istanbul_neighborhood_profile`) — ✅ 10/12

- Mahalle listeleme (`district` verip `neighborhood` vermeyince) çok faydalı
- ⚠️ Bomonti (Şişli) bulunamadı — Şişli'de Bomonti mahallesi veride yok
- ⚠️ Gülbahar bulunamadı — Kağıthane verisinde yok
- ⚠️ `BEÞÝKTAÞ`, `FÝKÝRTEPE` gibi encoding sorunları var
- ❌ Esenyurt'ta `"0.0"` isimli anlamsız mahalle kaydı var

### 🚌 Transit/Stops (`istanbul_transit_line_info`, `stops_for_line`) — ✅ 6/10

- ⚠️ Rate limit çok agresif (2 token, 0.5/sn refill)
- ⚠️ Ardışık çağrılarda rate limit'e takılıyor (5/10)
- ✅ 500T gibi uzun hat başarıyla dönüyor
- ❌ 999 (geçersiz hat) rate limit yerine "bulunamadı" dönmeli

### 📍 Nearby (`istanbul_nearby`) — ✅ 10/10

- Sağlam, çoklu feature type filtresi çalışıyor
- ⚠️ Bebek'te park seçeneği 20 sonuç dönüyor (limit sorunu)
- ⚠️ Kilyos'ta 0 sonuç doğru ama mesafe bilgisi referans koordinata bağlı

### 🚲 Mobility (`istanbul_mobility_nearby`) — ✅ 8/8

- Curated place çözümlemesi güzel çalışıyor (Kadıköy, Ataşehir, Sarıyer)
- ⚠️ Ataşehir'de otobüs durağı çıkmadı (GTFS DataStore 100 kayıt limiti)
- ⚠️ Sarıyer'de otopark/metro yok ama otobüs durağı var — doğru

### 🏛️ City Services (`istanbul_city_services_nearby`) — ✅ 4/6

- Kütüphane verisi ilçe bazlı, koordinat hassasiyeti yok
- ✅ Kadıköy'de 6 kütüphane, Bakırköy'de 3 kütüphane döndü
- ⚠️ Gülbahar gibi tanınmayan yer için hata dönüyor

### 🔍 Catalog/Data (`search_datasets`, `get_dataset`, `get_resource_schema`) — ✅ 10/10

- CKAN arama sağlam çalışıyor
- "engelli", "isbike", "otopark" aramaları başarılı
- ✅ İSBIKE'ın geçici olarak kapalı olduğu notu dönüyor
- ✅ Kentsel Açık ve Yeşil Alan verisi keşfedildi (ama DataStore değil, GeoJSON)

### 🗺️ BBOX (`istanbul_bbox_search`) — ✅ 3/4

- ✅ Eminönü-Sultanahmet bölgesi 10 sonuç döndü
- ✅ Beşiktaş-Üsküdar bölgesi 20 sonuç (parking filtresiyle)
- ❌ [0,0,0,0] için validation hatası dönüyor (beklenen)

---

## 3. Keşfedilen Veri Fırsatları

| Veri Seti | Tool/Format | Değer |
|---|---|---|
| **Kentsel Açık ve Yeşil Alan Koordinatları** | GeoJSON (data.ibb.gov.tr) | Park/yeşil alan sorusu için |
| **Muhtarlık Adres Bilgileri** | GeoJSON | Mahalle merkez koordinatı çözümü |
| **İBB Lokasyon Verileri** (907 kayıt) | CKAN DataStore | POI koordinat havuzu |
| **Engelli Şarj Noktaları** | CKAN DataStore | Metro istasyonları engelli erişimi |
| **Mevcut Otopark Sayıları** | CKAN DataStore | İlçe bazlı otopark istatistikleri |
| **34 Dakika İstanbul** | GeoJSON | Yürünebilirlik/yaşanabilirlik indeksi |

---

## 4. Kritik Sorunlar

### 🔴 P0 — Hemen Çözülmeli

| # | Sorun | Etkisi |
|---|---|---|
| 1 | **Hava kalitesi AQI 1 aydır null** | Tool işe yaramaz durumda |
| 2 | **IETT rate limit çok agresif** | 2 paralel çağrıda hata; kullanılamaz hale geliyor |
| 3 | **İlçe adı → koordinat çözümü yok** | "Başakşehir'de otopark" sorulamıyor |

### 🟡 P1 — Önemli Ama Acil Değil

| # | Sorun | Etkisi |
|---|---|---|
| 4 | `is_open` alanı güvenilir değil | Gece 24 saat otoparklar kapalı görünüyor |
| 5 | **Encoding sorunları** | `BEÞÝKTAÞ`, `FÝKÝRTEPE` |
| 6 | GTFS DataStore 100 kayıt limiti | 15.000+ durak varken 100 taranıyor |
| 7 | `empty_capacity: 1` şüpheli | Gerçek boş mu, default mu? |

### 🔵 P2 — İyileştirme

| # | Sorun |
|---|---|
| 8 | Geçersiz hat sorgusu (999) rate limit yerine "not found" dönmeli |
| 9 | Freshness raporlaması tutarsız (air quality'de `unknown`) |
| 10 | Çoklu paralel IETT çağrısı rate limit'i tetikliyor (seri yapılmalı) |

---

## 5. Geliştirme Önerileri (Öncelik Sırası)

1. **İlçe koordinat havuzu ekle** — 39 ilçe, sabit lat/lon (manuel veya muhtarlıktan)
2. **Air quality API'sini kontrol et** — 1 aydır AQI gelmiyor, kaynak değişmiş olabilir
3. **IETT rate limit'i yükselt** veya seri çağrı zorunluluğu getir
4. **Park/yeşil alan tool'u ekle** — GeoJSON verisi hazır, parse edip RTree'e yükle
5. **`istanbul_resolve_place` tool'u ekle** — "Başakşehir" → lat,lon döndürsün
6. **IETT GetHatOtoKonum_json** ekle — anlık otobüs konumları
7. **Metro servis durumu** ekle — hangi hat çalışıyor, gecikme var mı?
8. **GTFS DataStore limitini yükselt** veya tüm durakları local DB'e çek

---

## 6. Test İstatistikleri

| Metrik | Değer |
|---|---|
| Toplam tool çağrısı | ~90 |
| Başarılı | ~75 (%83) |
| Rate limit kaynaklı hata | 5 (%6) |
| Validation kaynaklı hata | 6 (%7) |
| Veri kalitesi sorunu (null AQI) | ~28 istasyon |
| Cache hit (tahmini) | ~30 çağrı (metro, parking) |
| En hızlı tool | Health (<100ms) |
| En yavaş tool | Air Quality (~9sn, çoklu istasyon sorgusu) |
