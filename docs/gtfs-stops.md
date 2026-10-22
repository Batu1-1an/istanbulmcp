# GTFS durak katmanı: onarım, sınırlar ve doğrulama

Bu değişiklik yalnızca **statik durak konumlarını** onarır. Yeni tool, `next_departures`, canlı varış, tarife birleştirmesi veya A–B rota motoru eklemez. Varsayılan yüzey 15 araçtır.

## Kullanım

Mevcut `istanbul_nearby` dağıtıcısını kullanın:

```json
{
  "lat": 41.01917,
  "lon": 28.684353,
  "types": ["public_transport_stop"],
  "radius_m": 2000,
  "limit": 5
}
```

`bbox` modu ve `istanbul_mobility_nearby` de aynı doğrulanmış durak indeksini kullanır. Mesafeler sıralanır; konumlar tıklanabilir `maps_url` taşır. Koordinat/yarıçap/sonuç sınırları değişmemiştir.

## Hata ve düzeltme

Eski resolver, `name + description + url` içindeki geniş sözcük eşleşmesini `datastore_active` ile birleştiriyordu. `stop_times` açıklamasındaki **“durak”** sözcüğü yanlış seçime neden oluyordu. 1.048.575 kayıtlık, koordinat içermeyen bu tablonun 100 satırlık sayfalarla taranması, doğrudan `nearby` yolunda dakikalarca sürebiliyordu. Gerçek `stops.csv` ise DataStore aktif olmadığı için dışlanıyordu.

Yeni `app/connectors/gtfs.py`:

1. `iett-gtfs-verisi` metadata'sını sınırlı yanıtla okur; dataset UUID'sini sabitlemez.
2. Yalnız canonical stops adı veya tam `stops.csv`/`stops.txt` dosya adıyla eşleşir. Açıklama metni seçimde kullanılmaz; `stop_times` dışlanır. Birden fazla gerçek aday varsa tahmin etmez.
3. DataStore pasif olsa da resmî CSV'yi indirir. Yalnız HTTPS `data.ibb.gov.tr`, seçilen resource ID'siyle eşleşen canonical download yolu kabul edilir; kullanıcı bilgisi, query/fragment, yabancı host ve redirect reddedilir.
4. UTF-8 BOM, `;` ve standart `,` ayracını, CSV quoting'i işler. `stop_id`, `stop_name`, `stop_lat`, `stop_lon` zorunludur. Çift başlık, kaymış satır genişliği, bozuk encoding/quoting ve yinelenen/eksik ID ile snapshot reddedilir.
5. Kaynaktaki sondaki adsız sütunu yok sayar; bu sütun bir geçerli kayıtta `0` da içerir. **İsimli sütunları kaydırmaz.**
6. Sadece bilinen nokta-gruplamalı biçimi çözer: `410.191.700.005.564 → 41.0191700005564`. Rastgele büyük tamsayı, bilimsel gösterim, metin/saat karışımı veya eksen değiştirme üzerinden konum tahmin etmez.
7. Sonlu WGS84 değerlerini geniş İstanbul plausibility kutusuyla denetler: enlem 40,70–41,50; boylam 27,80–30,20. Bu kutu kesin il sınırı/poligon veya konum doğruluğu garantisi değildir.
8. Tam ve kullanılabilir snapshot hazır olmadan geo/RTree katmanını değiştirmez. Boş veya tüm koordinatları geçersiz snapshot, eski katmanı silmez. SQLite yazma hatası transaction ile geri alınır.

Download URL'si bulunmayan fakat gerçekten aktif stops DataStore kaynağı için geriye uyumlu, `_id asc` sıralı 100 satırlık bounded sayfalama korunur. Her sayfada şema/toplam kontrol edilir; toplam değişmesi, eksik/fazla sayfa veya sınır aşımı kısmi başarı değildir. CSV URL'si varsa CSV tercih edilir; başarısız CSV indirmesi sessizce farklı tabloya çevrilmez.

## Kaynak ve tazelik sözleşmesi

- Başarılı cevap `sources[]` içinde dataset/resource ID'si, kaynak güncelleme zamanı, son başarılı yükleme, `scope`, received/accepted/skipped sayıları taşır.
- CSV `reported_total` ve `received_total`, tam indirilen dosyadaki filtrelenmemiş veri satırı sayısıdır; yayıncının bağımsız bir row-count beyanı değildir. DataStore yolunda `reported_total` CKAN toplamıdır.
- Bilinen biçimde normalleştirilen ve geçersiz/İstanbul-dışı olduğu için atlanan kayıt sayıları `warnings` içindedir. Yeni normalizasyon koordinat tahminini genel amaçlı hale getirmez.
- `fresh` son başarılı **yüklemenin** TTL içinde olduğunu söyler; kaynak dosyasının bugün güncellendiğini veya durağın bugün işletildiğini söylemez. Kaynak `source_updated_at` ayrıca korunur. Statik-konum uyarısı her başarılı GTFS cevabında vardır.
- TTL dolduğunda yenileme başarısızsa yalnız sınırlandırılmış son başarılı snapshot sunulabilir: `freshness.status=stale`, `coverage_status=unavailable`, özgün son-yükleme zamanı ve açık uyarı. Hatalar stale penceresini uzatmaz.
- Başarılı cache yoksa veya stale penceresi dolmuşsa GTFS-only nearby/bbox cevabı `ok=false`, `freshness=broken` ve unavailable coverage taşır. SQLite'ta eski durakların bulunması tek başına başarı/fresh yetkisi vermez.
- `mobility_nearby` diğer kullanılabilir bileşenleri korur. GTFS unavailable ise durak bölümü boş **ve açıkça unavailable**, birleşik freshness `unknown`; stale durak kullanılırsa diğer bileşenler sağlıklı olduğu sürece birleşik freshness `stale` olur. Boş durak bölümü “yakında durak yok” diye yorumlanmamalıdır.
- Varsayılan city-feature sorgusu GTFS istemediyse önceki indeks duraklarını kendiliğinden eklemez.

Cache süreç içindedir. Anahtar DB yolu, CKAN endpoint'i ve GTFS limit profilinin hash'ini içerir; farklı DB veya daha sıkı profil başka bir yüklemenin cache başarısını devralmaz. Restart'ta SQLite verisi kalabilse de cache provenance'ı kalmaz; kaynak yeniden doğrulanamazsa eski kayıtlar sunulmaz. Bu değişiklik paylaşımlı DB üzerinde çoklu worker/süreçler arası snapshot koordinasyonu veya yatay ölçekleme sağlamaz.

## Sınırlar ve konfigürasyon

| Değişken | Varsayılan | Kabul edilen üst sınır |
|---|---:|---:|
| `GTFS_STOPS_MAX_BYTES` | 5.242.880 (5 MiB) | 20.971.520 (20 MiB) |
| `GTFS_STOPS_MAX_ROWS` | 50.000 | 100.000 |
| `GTFS_STOPS_LOAD_TIMEOUT_SECONDS` | 20 | 60; sonlu ve >0 |
| `GTFS_STOPS_CACHE_TTL_SECONDS` | 86.400 (24 saat) | 86.400 |
| `GTFS_STOPS_STALE_IF_ERROR_SECONDS` | 604.800 (7 gün) | 604.800; 0 ile kapatılır |

Byte/row/TTL değerleri pozitif olmalıdır. Geçersiz ayarlar uygulama başlangıcında reddedilir. Varsayılan stale üst yaşı, başarılı yüklemeden itibaren **24 saat + 7 gün**dür.

Metadata ayrıca en fazla **512 KiB** olarak indirilir; CSV/DataStore veri bütçesinden ayrıdır. Veri yanıtlarında `Content-Length` ve okunan gerçek byte sayısı denetlenir; DataStore sayfalarında byte bütçesi toplamsaldır. Pozitif CKAN `size` metadata'sı varsa CSV boyutu onunla da eşleşmelidir; aksi halde iyi biçimlenmiş ama kesilmiş dosya da kabul edilmez. Sıkıştırılmış yanıtlar reddedilir. Byte sınırı, desteklenmeyen şema, satır sınırı veya timeout halinde kısmi indeks yayımlanmaz.

20 saniyelik kaynak bütçesi metadata, rate-limit beklemesi, indirme/sayfalama ve parsing'i kapsar; senkron parsing sonrasında da deadline kontrol edilir. Cache kilidini bekleme dahil dış bekleme sınırı bütçe +1 saniyedir. Sınırlı sayıdaki satırın senkron SQLite transaction'ı zamanlayıcıyla yarıda kesilmez. Aynı süreçte aynı profilin eşzamanlı sorguları tek başarılı yüklemeyi paylaşır. Cancel/timeout HTTP stream'ini kapatır; yükleme bitmeden indeks yayımlanmaz. Başarılı TTL içindeki sonraki sorgu dış API'ye gitmeden yerel indeksi okur.

GTFS sorgu cevaplarının `limits[]` alanı veri boyutu/satır/süre bütçesini, `/status` ise `limits.gtfs_stops` altında tüm GTFS ayarlarını bildirir. İndirmeler CKAN kaynak rate limiter'ını kullanır; ani retry döngüsü yoktur.

## Doğrulama

Offline regresyon:

```bash
pytest tests/test_gtfs.py tests/test_gtfs_regression.py tests/test_city_service.py tests/test_ckan_bounded.py
```

Küçük gerçek-kaynak fixture'ı ve kaynak notu: [tests/fixtures/gtfs](../tests/fixtures/gtfs/README.md). Testler kaynak seçimi, BOM/ayraç/adsız sütun, bozuk şema/ID/koordinat, byte/row/metadata bütçeleri, redirect/host, timeout/cancel, cache eşzamanlılığı, SQLite rollback, stale son tarihi, restart/DB/profil izolasyonu ve iki MCP protokol döneminde gerçek registry çıktısını kapsar.

Canlı kaynak testi yalnız açıkça etkinleştirilince çalışır; yerel ASGI `POST /mcp/` → gerçek GTFS kaynağı → SQLite → structured/text yanıt zincirini sınar. Geçici SQLite kullanır; deploy yapılmaz ve Railway MCP sunucusuna bağlanılmaz:

```bash
RUN_LIVE_GTFS_TESTS=1 pytest -s tests/live/test_gtfs_source_live.py
```

Yerel kabul gözleminde tam dosya **1.520.163 byte / 15.390 satır**dı; **15.386 durak** indekslendi, **4 bozuk kayıt** atlandı. Resource ID `2299bc82-983b-4bdf-8520-5cef8c555e29`; kaynak dosyası güncelleme zamanı **2026-03-17T12:25:15.191826**. ASGI MCP kabul koşumunda tek bir soğuk yükleme 4,582 saniye, cache'li sorgu 0,0086 saniye ölçüldü. Bunlar **tek gözlem**, p95/kapasite benchmark'ı veya Railway erişim garantisi değildir.

Son offline tam koşum: Python 3.12 ve temiz Python 3.11 ortamında **811 passed, 24 skipped**; skip'ler opt-in canlı testlerdir. Gerçek yerel subprocess smoke'unda 12 kontrol başarılıdır; bu smoke dış şehir API çağrısı yapmaz. Canlı GTFS kabul testi ayrıca çalıştırılmıştır. Commit/deploy yapılmamıştır.

## Kontrol edilen kaynaklar

- [Resmî dataset](https://data.ibb.gov.tr/dataset/iett-gtfs-verisi)
- [Resmî CKAN metadata](https://data.ibb.gov.tr/api/3/action/package_show?id=iett-gtfs-verisi)
- [GTFS stops referansı](https://gtfs.org/documentation/schedule/reference/#stopstxt): standart decimal WGS84 beklentisi; İBB'nin gruplamalı değerleri kaynak-özel bir kusurdur.
- [HTTPX async streaming](https://www.python-httpx.org/async/#streaming-responses) ve [response content](https://www.python-httpx.org/quickstart/#response-content): Context7 `/encode/httpx` üzerinden `AsyncClient.stream`, `aiter_bytes` ve cancellation/close davranışı kontrol edildi. `aiter_bytes` decoded byte verir; bu nedenle encoding guard ayrıca uygulanır.
