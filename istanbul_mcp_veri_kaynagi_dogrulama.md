# Istanbul MCP — Veri Kaynagi Dogrulama Raporu

**Tarih:** 2026-06-10 (Canli test: 19:00-20:00)
**Yontem:** Her endpoint birebir HTTP cagrisi ile test edildi (Python `urllib`)
**Amac:** IBB acik veri kaynaklarinin formatini, canliligini ve veri yapisini dogrulamak

---

## 1. KRITIK BULGU: SOAP SADECE IETT ICIN

Proje dokumanlarinda "IBB'nin anlik web servislerinin tamami SOAP" ifadesi yer aliyordu. Canli testler bunun **dogru olmadigini** gostermistir:

| Servis | Dokumanda Yazan | Gercekte Olan |
|--------|----------------|---------------|
| ISPARK Otopark | SOAP | **REST/JSON** |
| ISPARK Detay | SOAP | **REST/JSON** |
| Hava Kalitesi Istasyon | SOAP | **REST/JSON** |
| Hava Kalitesi Olcum | SOAP | **REST/JSON** |
| Trafik Indeksi | SOAP | **REST/XML** |
| Metro Istanbul | SOAP | **REST/JSON** |
| **IETT Hat/Durak/Sefer** | SOAP | **SOAP** (sadece burasi) |
| **IETT Duyuru** | SOAP | **SOAP** (calismiyor, HTTP 500) |

**Etkisi:** `zeep` kullanimi sadece IETT servisleriyle sinirli. Diger tum servisler icin `httpx`/`requests` yeterli.

---

## 2. CKAN API (REST/JSON)

### 2.1 package_list — Tum Datasetler

```
GET https://data.ibb.gov.tr/api/3/action/package_list
```

| Ozellik | Deger |
|---------|-------|
| Durum | Calisiyor |
| Toplam Dataset | **550** |
| Yani suresi | ~1 sn |
| Auth | Gerekmez |

### 2.2 package_search — Dataset Arama

```
GET https://data.ibb.gov.tr/api/3/action/package_search?q=trafik&rows=5
```

| Ozellik | Deger |
|---------|-------|
| Durum | Calisiyor |
| Parametre | `q` (full-text), `rows`, `start`, `fq` (filter) |
| Ornek: "ulasim" | 179 sonuc |
| Ornek: "trafik" | 13 sonuc |

### 2.3 package_show — Dataset Metadata

```
GET https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi
```

| Ozellik | Deger |
|---------|-------|
| GTFS Guncelleme | 2026-04-21 |
| Resource sayisi | 7 (5'i DataStore aktif) |
| Toplam GTFS Boyut | ~30MB (CSV) / ~22MB (ZIP) |

### 2.4 datastore_search — Yapisal Veri Sorgulama

```
POST https://data.ibb.gov.tr/api/3/action/datastore_search
Body: {"resource_id": "...", "limit": 5, "filters": {"Ilce Adi": "Besiktas"}}
```

**DataStore ile sorgulanabilir veriler:**

| Dataset | Resource ID (ornek) | Kayit Sayisi |
|---------|-------------------|:------------:|
| GTFS routes | `46dbe388-...` | 9.279 |
| Su Kesintisi | `b4105b7e-...` | 19.236 |
| IBB Kutuphaneleri | `2ee4476c-...` | (ilce bazli) |
| IBB Muzeleri | (CKAN'da) | (ilce bazli) |

---

## 3. IETT SOAP Servisleri

### 3.1 GetHat_json — Hat Bilgisi

```
POST https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx
SOAPAction: http://tempuri.org/GetHat_json
Param: HatKodu = "34A"
```

```json
[{"SHATKODU": "34A", "SHATADI": "CEVIZLIBA - SIRTLIBESME", "TARIFE": "METROBUS", "HAT_UZUNLUGU": 22.69, "SEFER_SURESI": 109.5}]
```

| Ozellik | Deger |
|---------|-------|
| Toplam Hat | **802** |
| Protokol | SOAP/XML (JSON string doner) |
| WSDL | `.../HatDurakGuzergah.asmx?wsdl` |
| JSON varyant | `_json` suffix — direkt JSON |

### 3.2 GetDurak_json — Tum Duraklar

```
POST https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx
SOAPAction: http://tempuri.org/GetDurak_json
Param: DurakKodu = "" (tumu)
```

| Ozellik | Deger |
|---------|-------|
| Toplam Durak | **15.148** |
| Cevap Boyutu | 3.6 MB XML |
| Koordinat | WKT `POINT (lng lat)` |
| Ilce Bilgisi | Her durakta `ILCEADI` alani |
| Yani suresi | ~5-8 sn (yavas) |

### 3.3 GetFiloAracKonum_json — Anlik Arac Konumlari

```
POST https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx
SOAPAction: http://tempuri.org/GetFiloAracKonum_json
```

| Ozellik | Deger |
|---------|-------|
| Anlik Arac Sayisi | **6.911** |
| Koordinat | Ayri `Enlem` + `Boylam` |
| Hiz | km/h |
| Sinirlama | **Hat bilgisi vermez** — sadece plaka bazli |
| WSDL | `.../SeferGerceklesme.asmx?wsdl` |

### 3.4 GetHatOtoKonum_json — HAT BAZLI Anlik Arac Konumu (KESIF!)

```
POST https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx
SOAPAction: http://tempuri.org/GetHatOtoKonum_json
Param: HatKodu = "130E"
```

```json
[{
  "kapino": "O1129",
  "boylam": "29.2153278333333",
  "enlem": "40.903516",
  "hatkodu": "130E",
  "guzergahkodu": "130E_D_D0",
  "hatad": "TUZLA / EVORA KONUTLARI - KARTAL METRO / CEVIZLI",
  "yon": "DENIZ HARP OKULU",
  "son_konum_zamani": "2026-06-10 19:09:52",
  "yakinDurakKodu": "289342"
}]
```

| Ozellik | Deger |
|---------|-------|
| **ONEM** | **Hat bazli anlik arac konumu** — MVP icin kritik |
| Yon Bilgisi | `yon` alani ile hangi yone gittigi |
| Yakin Durak | `yakinDurakKodu` ile en yakin durak kodu |
| Guzergah | `guzergahkodu` ile hangi rotada |
| Ornek: 500T | **43 aktif arac** |
| Ornek: 130E | 5 aktif arac |
| Ornek: 16D | 26 aktif arac |
| Ornek: 34A | 0 arac (metrobus farkli sistem) |
| Alanlar | `kapino, enlem, boylam, hatkodu, guzergahkodu, hatad, yon, son_konum_zamani, yakinDurakKodu` |

### 3.5 IETT Duyuru Servisi

```
POST https://api.ibb.gov.tr/iett/iett/iett.asmx
```

| Durum | HATA 500 |
|-------|---------|
| Hata | "Policy Falsified — Service Not Found" |
| Cozum | Endpoint degismis olabilir, arastirilmali |

---

## 4. ISPARK (REST/JSON)

### 4.1 Park Listesi

```
GET https://api.ibb.gov.tr/ispark/Park
```

```json
[{
  "parkID": 3068,
  "parkName": "15 Temmuz Sehitler Meydani Zeminalti Otoparki",
  "lat": "41.0246", "lng": "29.0915",
  "capacity": 1029, "emptyCapacity": 414,
  "workHours": "24 Saat", "parkType": "KAPALI OTOPARK",
  "freeTime": 15, "district": "UMRANIYE", "isOpen": 1
}]
```

| Ozellik | Deger |
|---------|-------|
| Toplam Park | **259** |
| Bos Yerli Park | **208** (test aninda) |
| Anlik Bos Yer | `emptyCapacity` alani |
| Koordinat | `lat` + `lng` (WGS84) |
| Ilce | `district` alani mevcut |
| Protokol | **REST/JSON** (SOAP degil) |

### 4.2 Park Detay

```
GET https://api.ibb.gov.tr/ispark/ParkDetay?id=1751
```

Ek alanlar: `monthlyFee, tariff, address, areaPolygon, updateDate`

---

## 5. Trafik Indeksi (REST/XML)

```
GET https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1/TrafficIndexHistory/1/5M
```

| Ozellik | Deger |
|---------|-------|
| Protokol | **REST/XML** (SOAP degil, REST XML) |
| Son Index | 58 (19:47 itibariyla) |
| Kayit Sayisi | 286 |
| Periyot | 5 dakikalik araliklar |
| Content-Type | `application/xml;charset=utf-8` |
| Parse | `xml.etree.ElementTree` ile kolay |

---

## 6. Hava Kalitesi (REST/JSON)

### 6.1 Istasyon Listesi

```
GET https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler/GetAQIStations
```

| Ozellik | Deger |
|---------|-------|
| Istasyon Sayisi | **28** |
| Protokol | REST/JSON |
| Koordinat | WKT `POINT (lng lat)` |

**Istasyonlar:** Maslak, Esenler, Yenibosna, Beylikduzu, Umraniye, Aksaray, Mobil, Besiktas, Kadikoy, Sultangazi, Avcilar, Uskudar, Alibeykoy, Selimiye, D-100, Kartal, Sariyer, Tuzla ve daha fazlasi.

### 6.2 Istasyon Olcum Degerleri

```
GET https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler/GetAQIByStationId?stationId={id}
```

| Ozellik | Deger |
|---------|-------|
| Durum | Servis calisiyor ama tum AQI degerleri `null` |
| Okuma Sayisi | 721 kayit (Maslak) |
| En Son Olcum | 2026-05-11 (1 ay once) |
| Sorun | Istasyonlar olcum yapmiyor olabilir |

---

## 7. Metro Istanbul (REST/JSON)

```
GET https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/GetStations
```

| Ozellik | Deger |
|---------|-------|
| Toplam Istasyon | **248** |
| Toplam Hat | **18** |
| Protokol | REST/JSON |
| Koordinat | `DetailInfo.Latitude` + `DetailInfo.Longitude` |

**Tum Hatlar:**

| Hat | Tur | Istasyon | Guzergah |
|-----|-----|:--------:|----------|
| M1A | Metro | 18 | Ataturk Havalimani - Otogar |
| M1B | Metro | 13 | Kirazli - Otogar |
| M2 | Metro | 16 | Yenikapi - Haciosman |
| M3 | Metro | 20 | Metrokent - Bakirkoy Sahil |
| M4 | Metro | 23 | Kadikoy - Sabiha Gokcen |
| M5 | Metro | 24 | Uskudar - Sultanbeyli |
| M6 | Metro | 4 | Levent - Hisarustu |
| M7 | Metro | 17 | Yildiz - Mahmutbey |
| M8 | Metro | 13 | Bostanci - Parseller |
| M9 | Metro | 14 | Olimpiyat - Atakoy |
| T1 | Tramvay | 31 | Bagcilar - Kabatas |
| T3 | Tramvay | 11 | Kadikoy IDO - Altiyol |
| T4 | Tramvay | 22 | Mescid-i Selam - Topkapi |
| T5 | Tramvay | 14 | Eminonu - Alibeykoy |
| F1 | Funikuler | 2 | Kabatas - Taksim |
| F4 | Funikuler | 2 | Asiyan - Rumeli Hisarustu |
| TF1 | Teleferik | 2 | Macka - Taskisla |
| TF2 | Teleferik | 2 | Eyup - Piyerloti |

**Diger Metro API'leri:**
- `GetStationById/{LineId}` — Hat ID'sine gore istasyon
- `GetStationBetweenTime` — Istasyonlar arasi sure
- `GetFares` — Ucret tarifesi
- `GetActivities` — Etkinlik listesi
- `GetSchedule` — Sefer tarifesi

---

## 8. Isbike (REST/JSON)

```
GET https://api.ibb.gov.tr/ispark-bike/GetAllStationStatus
```

| Ozellik | Deger |
|---------|-------|
| Durum | Servis calisiyor ama `dataList: []` bos |
| Protokol | REST/JSON |
| Portal Uyarisi | "This service is temporarily unavailable" |
| Alternatif | `.../GetStationStatus` (tek istasyon) |

---

## 9. Su Kesintileri (CKAN DataStore)

| Ozellik | Deger |
|---------|-------|
| Kayit Sayisi | **19.236** |
| DataStore | Aktif |
| Guncelleme | 2026-02-13 |
| Sutunlar | ARIZA NUMARASI, ILCE, MAHALLE, ARIZA SEBEP, SORUMLU, BASLANGIC, BITIS |
| Filtreleme | `{"ILCE": "Kadikoy"}` ile ilce bazli |

---

## 10. GTFS Verisi (CKAN DataStore + CSV)

| Dosya | Boyut | DataStore |
|-------|-------|:---------:|
| `agency.csv` | 114 B | |
| `calendar.csv` | 232 B | |
| `routes.csv` | 812 KB | **9.279 kayit** |
| `trips.csv` | 5.8 MB | |
| `stops.csv` | 1.5 MB | DataStore yok |
| `stop_times.csv` | 26 MB | |
| `stop_times.zip` | 22 MB | (zip) |

**Guncelleme:** 2026-04-21

---

## 11. CKAN'da Kesfedilen Diger Veri Setleri

| Kategori | Dataset Sayisi | Format |
|----------|:--------------:|--------|
| Muze | 2 | XLS |
| Tiyatro | 6 | CSV |
| Muhtarlik | 2 | **GeoJSON** |
| Tuvalet | 2 | **GeoJSON** |
| Kutuphane | 1 | XLSX (DataStore) |
| Wi-Fi | 4 | CSV |
| Mezarlik | 1 | XLSX |
| Engelli | 6 | XLSX |
| Halk Ekmek | ? | (aranacak) |
| Kent Lokantasi | ? | (aranacak) |

---

## 12. MVP Kapsamli Dogrulama Tablosu

| # | Veri Kaynagi | Protokol | Canli | Detay |
|---|-------------|----------|-------|-------|
| 1 | CKAN Katalog | REST/JSON | | 550 dataset |
| 2 | CKAN Arama | REST/JSON | | 179 sonuc (ulasim) |
| 3 | CKAN DataStore | REST/JSON | | 9.279 kayit (routes) |
| 4 | ISPARK | REST/JSON | | 259 park, 208 bos yer |
| 5 | ISPARK Detay | REST/JSON | | tarife + ucret + polygon |
| 6 | Isbike | REST/JSON | (bos) | dataList bos |
| 7 | Hava Kalitesi Istasyon | REST/JSON | | 28 istasyon |
| 8 | Hava Kalitesi Olcum | REST/JSON | (bos) | AQI=None |
| 9 | Trafik | REST/XML | | index=58, 286 kayit |
| 10 | IETT Hat | SOAP | | 802 hat |
| 11 | IETT Durak | SOAP | | 15.148 durak |
| 12 | IETT Anlik Arac (hat bazli) | SOAP | | 43 arac/hat (500T) |
| 13 | IETT Anlik Arac (tum) | SOAP | | 6.911 arac |
| 14 | IETT Duyuru | SOAP | HATA 500 | Policy Falsified |
| 15 | Metro Istanbul | REST/JSON | | 248 istasyon, 18 hat |
| 16 | Su Kesintisi | REST/JSON | | 19.236 kayit |
| 17 | CKAN: kutuphane | DataStore | | ilce bazli sorgu |
| 18 | CKAN: muhtarlik | GeoJSON | | 2 dataset |
| 19 | CKAN: tuvalet | GeoJSON | | 2 dataset |
| 20 | CKAN: muze | XLS | | 2 dataset |
| 21 | CKAN: tiyatro | CSV | | 6 dataset |
| 22 | CKAN: wifi | CSV | | 4 dataset |

---

## 13. GetHatOtoKonum_json — Detayli Analiz

Bu metod **MVP icin en kritik kesiflerden biridir.** `GetFiloAracKonum_json`'dan farkli olarak:

| Karsilastirma | GetFiloAracKonum_json | **GetHatOtoKonum_json** |
|--------------|----------------------|------------------------|
| Filtre | Yok (tum araclar) | **Hat koduna gore** |
| Arac Sayisi | 6.911 (tum Istanbul) | Sadece o hattakiler |
| Yon Bilgisi | Yok | **Var (`yon`)** |
| Yakin Durak | Yok | **Var (`yakinDurakKodu`)** |
| Guzergah | Yok | **Var (`guzergahkodu`)** |
| Alan Adlari | Buyuk harf (Plaka, Enlem) | Kucuk harf (kapino, enlem) |
| Kullanim | MVP'de gerekmez | **MVP icin ideal** |

**Ornek Kullanim:**
```
HatKodu=500T -> 43 arac
HatKodu=130E -> 5 arac
HatKodu=16D  -> 26 arac
HatKodu=34A  -> 0 arac (metrobus sistemi)
```

---

## 14. CKAN DataStore Filtreli Sorgu Ornekleri

### Kutuphane (Ilce bazli)

```
POST /api/3/action/datastore_search
Body: {"resource_id": "2ee4476c-...", "filters": {"Ilce Adi": "Besiktas"}}
```

```json
[{
  "Kutuphane Adi": "Besiktas Iskele Kutuphanesi",
  "Ilce Adi": "Besiktas",
  "Adres": "Sinanpasa, Iskele Cd. No:16, 34353 Besiktas/Istanbul",
  "Telefon": "0212 312 67 72",
  "Calisma Saatleri": "09:00-22:00",
  "Calisma Gunleri": "Hergun",
  "Acilis Yili": "2023"
}]
```

**Kolonlar:** Kutuphane Adi, Ilce Adi, Acilis Yili, Adres, Telefon, Calisma Saatleri, Calisma Gunleri

### Su Kesintisi (Ilce bazli)

```
POST /api/3/action/datastore_search
Body: {"resource_id": "...", "filters": {"ILCE": "Kadikoy"}}
```

**Kolonlar:** _id, ARIZA NUMARASI, ILCE, MAHALLE, ARIZA SEBEP, SORUMLU, BASLANGIC, BITIS

---

## 15. Duzeltilen Yanlis Anlamalar

| Dokumanda Yazilan | Gercekte Olan | Etki |
|-------------------|---------------|------|
| "Anlik verilerin tamami SOAP" | Sadece IETT SOAP, digerleri REST | SOAP kullanimi cok daha az |
| "41 API'nin tamami SOAP" | REST ve SOAP karisimi | Daha basit stack |
| "ISPARK SOAP" | REST/JSON | `httpx` yeterli |
| "Hava kalitesi SOAP" | REST/JSON | `httpx` yeterli |
| "Trafik indeksi SOAP" | REST/XML | `httpx` + XML parse |
| "Metro SOAP" | REST/JSON | `httpx` yeterli |
| "542 veri seti" | **550** (guncel sayi) | Kucuk fark |
| "GTFS son Mart 2026" | **2026-04-21** (Nisan) | Daha guncel |
| "ISPARK 300+ park" | **259** park | Guncel sayi |
| "Hava kalitesi 10+ istasyon" | **28** istasyon | Daha fazla |
| "Trafik JSON doner" | **XML** donuyor | Parse farki |

---

## 16. Koordinat Doyusum Notlari

| Kaynak | Format | Ornek |
|--------|--------|-------|
| IETT Durak (SOAP) | WKT `POINT (lng lat)` | `POINT (29.0333 40.9908)` |
| IETT Arac (SOAP) | Ayri `enlem`+`boylam` | `enlem: 41.074, boylam: 29.017` |
| ISPARK | Ayri `lat`+`lng` string | `lat: "41.0246", lng: "29.0915"` |
| Hava Kalitesi | WKT `POINT (lng lat)` | `POINT (29.0245 41.1000)` |
| Metro | `DetailInfo.Latitude/Longitude` | `"40.990663811475805"` |
| GTFS stops.csv | Ayri `stop_lat`+`stop_lon` | `stop_lat: 41.005, stop_lon: 29.022` |

**Tum koordinatlar WGS84 (EPSG:4326) standardindadir.**

---

## 17. Veri Kaynagi Kararlilik Degerlendirmesi

| Kaynak | Hiz | Guvenilirlik | Not |
|--------|-----|-------------|-----|
| CKAN API | Hizli (~1 sn) | Yuksek | Public, auth gerekmez |
| IETT SOAP (Durak) | Yavas (~5-8 sn) | Orta | Gece kapanir, 15K durak |
| IETT SOAP (Arac) | Orta (~3-5 sn) | Orta | Gece kapanir |
| IETT HatOtoKonum | Orta (~3-5 sn) | Orta | **MVP icin en kritik** |
| ISPARK | Hizli (~1 sn) | Yuksek | REST/JSON |
| Trafik | Cok hizli (~0.5 sn) | Yuksek | REST/XML |
| Hava Kalitesi | Hizli (~1 sn) | Orta | Olcumler null su an |
| Metro | Hizli (~1 sn) | Yuksek | REST/JSON |
| Isbike | Hizli | Bos | Servis gecici olarak kapali |
| GTFS DataStore | Hizli | Yuksek | SQL sorgulanabilir |

---

## 18. Baglanti Bilgileri

### CKAN API
- Base: `https://data.ibb.gov.tr/api/3/action/`

### SOAP WSDL'ler
- Hat/Durak/GuZergah: `https://api.ibb.gov.tr/iett/UlasimAnaVeri/HatDurakGuzergah.asmx?wsdl`
- Sefer Gerceklesme: `https://api.ibb.gov.tr/iett/FiloDurum/SeferGerceklesme.asmx?wsdl`

### REST API'ler
- Trafik Indeksi: `https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1/`
- ISPARK: `https://api.ibb.gov.tr/ispark/`
- Hava Kalitesi: `https://api.ibb.gov.tr/havakalitesi/OpenDataPortalHandler/`
- Metro: `https://api.ibb.gov.tr/MetroIstanbul/api/MetroMobile/V2/`
- Isbike: `https://api.ibb.gov.tr/ispark-bike/`
