# İBB GTFS durak regresyon örnekleri

Kaynak: [İBB `iett-gtfs-verisi`](https://data.ibb.gov.tr/dataset/iett-gtfs-verisi).

- `package.json`: resmî `package_show` yanıtından seçilmiş iki kaynak ve gerekli metadata alanları. `stop_times` önce gelir, açıklamasında “durak” geçer ve DataStore aktiftir. Gerçek `stops` CSV'sinde DataStore pasiftir. Bu sıralama yanlış-kaynak regresyonunu yeniden üretir.
- `ibb_stops_sample.csv`: resmî `stops.csv` içindeki **7 kaydın** alan-değeri korunmuş küçük seçkisi; dosyanın tamamı değildir. UTF-8 BOM, `;` ayracı ve sondaki adsız sütun korunmuştur. İlk 3 kayıt kullanılabilir; 4 bozuk kayıtta tarih/saat eklenmiş koordinat veya kaymış alanlar bulunur. Bu kayıtlar tahminle düzeltilmez.
- Satır sonları depoda LF olarak normalize edilmiştir; BOM ve alan değerleri korunur. CRLF desteği ayrıca CSV parser testlerinde sınanır.
- Resmî metadata'daki tam dosya `size` değeri, küçük seçkinin gerçek boyutu olmadığı için fixture metadata'sına alınmamıştır. Boyut eşleştirmesi ayrıca sentetik HTTP testlerinde ve opt-in canlı kabul testinde sınanır.

Gözlemde resmî dataset UUID'si `8540e256-6df5-4719-85bc-e64e91508ede`, stops resource ID'si `2299bc82-983b-4bdf-8520-5cef8c555e29`, kaynak güncelleme zamanı `2026-03-17T12:25:15.191826` idi. Üretim kodu dataset UUID'sini sabitlemez; slug üzerinden güncel metadata'yı çözer.

Tam dosya indirme URL'si:

```text
https://data.ibb.gov.tr/dataset/8540e256-6df5-4719-85bc-e64e91508ede/resource/2299bc82-983b-4bdf-8520-5cef8c555e29/download/stops.csv
```

Ünite testleri ağ erişimi gerektirmez. Bu örnekler lisans veya yeniden dağıtım hakkı beyanı değildir; özgün veri kullanım koşulları kaynakta kontrol edilmelidir.
