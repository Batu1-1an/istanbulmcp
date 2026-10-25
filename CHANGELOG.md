# Changelog

0.2.4 ve önceki kayıtlar Git geçmişinden geriye dönük hazırlanmıştır. Tarihler, sürüm numarasının
depoda değiştiği tarihlerdir; GitHub Release veya Registry yayını yapıldığını
göstermez. Registry yayın bilgisi için [yayın rehberine](docs/registry.md) bakın.

## [Unreleased]

### Changed
- `sources[].url` yalnız kullanıcının açabileceği web sayfalarını taşır. API uçları
  (`api.ibb.gov.tr` vb.), proxy adresleri ve ham veri dosyaları (JSON, CSV, ZIP, XLSX)
  `null` döner; yayıncı, dataset/resource ID ve tazelik bilgisi korunur.
- Sunucu talimatı, cevapta kaynağı yayıncı adıyla belirtmeyi ve yalnız dolu
  `sources[].url` alanını link olarak vermeyi ister.

### Security
- İSKİ relay adresi artık tool sonucunda kaynak URL'i olarak görünmez.

## [0.2.5] - 2026-10-25

### Added
- `MCP_CORS_ALLOWED_ORIGINS` ile yalnız belirlenen sitelerden tarayıcı bağlantısı.
  Boş liste hiçbir browser origin'ine izin vermez; wildcard ve `null` kabul edilmez.
- MCP uçlarında yerel OPTIONS/preflight yanıtı; MCP ve Authorization başlıkları,
  JavaScript'ten okunabilen oturum, tekrar deneme ve kota başlıkları.
- İzinli origin'ler için 401/413/429/500 yanıtlarında da CORS başlıkları.
- İzin verilmeyen veya yinelenen Origin başlıklarının MCP çalışmadan reddedilmesi.

### Notes
- Preflight API anahtarı veya kota tüketmez; gerçek isteklerde mevcut anahtar,
  gövde, hız, eşzamanlılık ve kota kontrolleri korunur. Cookie credentials açılmaz.
- Origin göndermeyen mevcut istemciler değişmez. Yeni araç veya SQL değişikliği yoktur.

### Tests
- GTFS stale testlerinde süre, makinenin çalışma süresinden bağımsız olacak şekilde
  güncel monoton saate göre ayarlanır. Üretim önbellek süreleri değiştirilmedi.
- Gerçek süreç smoke testinin açılış bütçesi paylaşılan CI makineleri için 45 saniye;
  başarısız açılışta sunucu günlüğü hata çıktısına eklenir.

## [0.2.4] - 2026-10-25

### Publication
- Sürüm değişikliklerini kaydeden bu CHANGELOG.
- Resmî MCP Registry'de 0.2.4 için ilk remote-only kayıt ve yayın/doğrulama adımları
  (2026-10-25). Bu kayıt yeni bir uygulama sürümü veya directory kabulü değildir.
- Kod lisansı henüz seçilmedi. LICENSE dosyası eklenmedi. Veri kaynaklarının
  kullanım koşulları ve lisansları ayrı değerlendirilir.

### Added
- Her GTFS ve planlı terminal kalkışında `realtime:false`,
  `schedule_relationship:STATIC` ve veri kaynağı alanı.
- GTFS durak adayları ve kalkışlarında `stop_code`, `stop_desc`,
  `platform_direction_text` ve `location_type`.
- İndirme başlatmadan yerel tarife yaşı, takvim, kayıt ve atlama sayılarını
  gösteren `istanbul_gtfs_snapshot_status` aracı.
- Ortak `error` sözleşmesi: hata kodu, geçicilik, tekrar deneme gecikmesi ve
  uygun olduğunda bir sonraki araç çağrısı.
- Ortak `result_info` sözleşmesi: döndürülen/eşleşen kayıt sayısı, kesilme,
  sayım kapsamı ve devam önerisi. Bilinmeyen tamamlık açıkça belirtilir.

### Fixed
- İsteğe bağlı bozuk `location_type` alanları tüm tarifeyi reddetmez;
  `null`, sayaç ve uyarıyla bildirilir.
- Eski durak şeması, yeni snapshot ile aynı transaction içinde yükseltilir;
  başarısız yayın eski şema ve satırları korur.
- GTFS araçları kapatıldığında listeden gizlenir, eski istemciler için
  çağrılabilir kalır.

### Notes
- SQL aracı, sorgu motoru ve allowlist değiştirilmedi.
- Canlı ETA, gecikme veya o gün sefer işletildiği garantisi eklenmedi.

## [0.2.3] - 2026-10-25

### Added
- `istanbul_next_departures` üzerinde isteğe bağlı `stop_query` ile Türkçe/ASCII
  durak adı araması, sıralı adaylar ve açıkça etiketlenmiş yazım önerileri.
- Aynı adlı durakların ayrı tutulması; toplam, kesilme ve arama bütçesi bilgisi.

### Notes
- Ad araması kalkış döndürmez; yalnız `limit` ile kullanılır. Durak, ilçe veya
  yön otomatik seçilmez. Yeni bir araç adı eklenmedi.

## [0.2.2] - 2026-10-25

### Fixed
- Çelişen `(trip_id, stop_sequence)` kayıtları, batch sınırları arasında da
  yakalanarak yeni GTFS snapshot'ının yayınlanması engellenir.
- Sefer saatlerinin durak sırasına göre geriye gitmesi reddedilir.
  Saatsiz ara duraklar, geceyarısı sonrası saatler ve önceki snapshot korunur.

## [0.2.1] - 2026-10-25

### Added
- 39 ilçede koordinat veya mesafe uydurmadan ilçe geneli hizmet özetleri.
- Kaynak ve lisans bilgili statik yer referansları; belirsiz Acıbadem için
  Kadıköy/Üsküdar ayrımı.

### Notes
- İlçe hareketlilik özeti otoparkla; ilçe şehir-hizmeti özeti kütüphane/kültür
  adresleriyle sınırlıdır. Tam adres çözümleme değildir.

## [0.2.0] - 2026-10-24

### Changed
- Yayımlanmış araç adları, kompakt listede görünmeseler de gizli alias olarak
  çağrılabilir tutuldu.

### Included from earlier 0.1.0 development
- Python MCP SDK 2.3'e geçiş; eski ve yeni MCP protokolleri, yerel keşif
  kaynakları, prompt'lar ve yapılandırılmış yanıt şemaları.
- Kompakt salt okunur araç yüzeyi, isteğe bağlı erişim/kota kontrolleri ve
  sınırlı DataStore sorguları.

### Added while the version remained 0.2.0
- Tam GTFS ZIP üzerinden planlı kalkışlar, açılış ön ısıtması ve açık
  `warming_up` / `outside_calendar` yanıtları (2026-10-25).
- Kaynak bütünlüğü, tazelik ve kaynak hatalarını boş sonuçtan ayıran düzeltmeler.

## [0.1.0] - 2026-06-12

### Added
- Python MCP sunucusu, temel şehir-verisi konektörleri, SQLite depolama ve test
  altyapısıyla projenin ilk temeli.

[Unreleased]: https://github.com/Batu1-1an/istanbulmcp/commits/main
[0.2.5]: https://github.com/Batu1-1an/istanbulmcp/compare/9010d75...main
[0.2.4]: https://github.com/Batu1-1an/istanbulmcp/commit/1736725
[0.2.3]: https://github.com/Batu1-1an/istanbulmcp/commit/ccc3864
[0.2.2]: https://github.com/Batu1-1an/istanbulmcp/commit/e76a46f
[0.2.1]: https://github.com/Batu1-1an/istanbulmcp/commit/952fa5e
[0.2.0]: https://github.com/Batu1-1an/istanbulmcp/commit/0e7ff31
[0.1.0]: https://github.com/Batu1-1an/istanbulmcp/commit/553a065
