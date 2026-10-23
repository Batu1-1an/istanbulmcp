# Statik şehir katmanları: EV, taksi, pazar, kültür merkezi

Durum: kod ve fixture doğrulaması tamam; **canlı İBB kaynağı bu ortamdan
doğrulanamadı** (TCP timeout). Bu katmanlar yayımlanmış statik snapshot'lardır;
canlı doluluk, açılış veya işletilme durumu değildir.

## Kaynaklar

| Katman | Kaynak | Kayıt | Kullanım |
|---|---|---|---|
| EV şarj | [İBB GeoJSON](https://data.ibb.gov.tr/dataset/79b0e26e-e923-498b-a675-453382274178/resource/726e9d82-37f7-4142-8fa0-4f70a5530188/download/sarj_istasyonlari.geojson) | ~2.933 point | `nearby(types=["ev_charging"])` |
| Taksi durağı | [İBB GeoJSON](https://data.ibb.gov.tr/dataset/10fc48d1-ba69-423d-9414-8bb3487e6e2a/resource/33c384f3-f456-474c-90cf-1c4e65ac221f/download/istanbul_taksi_duraklari.geojson) | ~613 point | `nearby(types=["taxi_stand"])` |
| Pazar yeri | İBB DataStore `78d6e0eb-9012-43c1-9eb1-cd30f743f3a8` | 385 satır | `nearby(types=["market"])` ve `market_schedule` |
| Kültür merkezi | [İBB XLSX](https://data.ibb.gov.tr/dataset/d299950a-3476-4576-967a-9ab7bbe2aa06/resource/9f16f741-742f-41f8-9e36-918fb7fc2a7f/download/kultur-merkezleri-veri-seti_.xlsx) | 16 satır, koordinatsız | `city_services_nearby` içinde `address_search` |

Pazar şeması: `_id`, `Ilce`, `Pazar Adi`, `Koordinat`, `Mahalle`, `Cadde`,
`Sokak`, `Gun`, `Pazar Tipi`. Koordinat `"lat,lon"` metnidir; yalnız iki sonlu
sayı ve İstanbul plausibility kutusu kabul edilir.

## Davranış

- `istanbul_nearby(types=[...])` yalnız açıkça istenen katmanları yeniler; yeni
  katmanlar varsayılan sorguya sessizce eklenmez.
- Başarılı katman `geo_features` içinde kaynak/tür bazında **atomik replace**
  edilir; başarısız veya boş yükleme önceki katmanı silmez.
- Her sonuç `maps_url`, kaynak kimliği, kaynak URL'i, alınan/kabul edilen/atlanan
  sayıları ve uyarı taşır. Statik veri `freshness` durumunu canlı sağlıkla
  karıştırmaz.
- EV/taksi GeoJSON'unda koordinat önce property (`LATITUDE/LONGITUDE`, `lat/lon`)
  sonra Point geometry'den okunur; İstanbul dışı ve geçersiz noktalar atlanır.
- Pazar takvimi `day` için Türkçe/İngilizce gün, `bugün/yarın/today/tomorrow`
  veya ISO tarih kabul eder. `district` Türkçe karakter normalizasyonuyla
  eşleşir. Varsayılan limit 50, üst sınır 100.
- Kültür merkezleri koordinat üretmediği için radius sonucuna zorlanmaz; ilçe
  bazlı `city_services_nearby` içinde adres araması olarak döner.

## Sınırlar

| Ayar | Varsayılan | Üst sınır |
|---|---:|---:|
| `OPEN_DATA_LAYERS_MAX_BYTES` | 8 MiB | 32 MiB |
| `OPEN_DATA_LAYERS_MAX_ROWS` | 5.000 | 10.000 |
| `OPEN_DATA_LAYERS_REQUEST_TIMEOUT_SECONDS` | 5 | 30; sonlu ve pozitif |
| `OPEN_DATA_LAYERS_CACHE_TTL_SECONDS` | 86.400 | 86.400 |

GeoJSON/XLSX indirmeleri yalnız canonical HTTPS `data.ibb.gov.tr` URL'lerini
kabul eder; redirect, query/fragment, yabancı host, sıkıştırılmış gövde ve
Content-Length/byte aşımı reddedilir. Pazar DataStore sayfaları tamamlanana kadar
döngüde okunur; toplam değişirse veya sayfa eksikse başarısız olur. XLSX yalnız
ilk worksheet'i, formülsüz hücre değerleriyle ve satır/hücre sınırıyla okur.

## Doğrulama

```bash
pytest tests/test_city_open_data.py tests/test_city_service.py
pytest
python -m scripts.smoke_mcp
```

Fixture'lar: `tests/fixtures/city_layers/`. Gerçek kaynak kabulü, erişebilen bir
ortamdan EV/taksi/pazar/kültür sayılarının ve şemalarının yeniden okunmasını
gerektirir; mevcut koşumda İBB'ye TCP bağlantısı kurulamadı. Bu nedenle canlı
kaynak doğrulandı veya üretim performansı ölçüldü denemez.
