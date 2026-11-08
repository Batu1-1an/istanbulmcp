# Niloya ek saatleri ve esnek giriş bileti düzeltmesi

8 Kasım 2026 · Sürüm 0.7.0.

## Yeni testteki iki bulgu

Önceki 50 sorudan farklı hazırlanmış 50 soru, canlı 0.6.1 üzerinde çalıştırıldı.
Sekiz karşılaştırma araması ve bir takip detayıyla toplam 59 gerçek MCP çağrısı
yapıldı. Parametre denetimleri geçti; kaynak çapraz kontrolü iki zamanlama
kusurunu ortaya çıkardı. Bu nedenle sıfır filtre ihlali kaynak saatlerinin veya
kullanıcıya faydanın tamamının doğrulandığı anlamına gelmez.

1. Niloya: canlı detayda üç HTML seansına ek olarak üç saat ilerideki JSON
   seansları vardı. Güncel görünür sağlayıcı sayfası üç İstanbul seansı yayımlıyordu.
   İlk üretim indirmesinin ham gövdesi saklanmadığından kaynak varyasyonunun
   nedeni kesinleşmedi. Kodda ise farklı JSON saati, aynı gün/mekânın görünür
   seansı varken bile ek bir seans gibi kabul ediliyordu.
2. Olimpik Go Kart: HTML seansında gün/mekân ve gün içi kullanım kuralı var,
   saat yok. Kod bu HTML satırını atlayıp JSON-LD 23.59 zamanını planın başlangıcı
   sayıyordu. Bu, biletin gün içindeki kullanım hakkını sabit ziyaret saati yapıyordu.

Kontrol edilen birincil sayfalar:
[Niloya](https://biletinial.com/tr-tr/tiyatro/niloya-renkli-baliklar-muzikali),
[Olimpik Go Kart](https://biletinial.com/tr-tr/etkinlik/olimpik-go-kart).
Saatler başlıktan, mekân türünden veya tahmini çalışma saatinden türetilmedi.

## Doğrulanmayan ek JSON saatleri

HTML'deki açık gün/ay/saat, aynı mekân ve güne ait tam kaynak yılını kullanabilir;
JSON'un saatinin eşit olması şart değildir. Örneğin HTML 14 Kasım 16.00,
JSON 2030-11-14 19.00 olduğunda görünür 16.00 seansı indekslenir. 19.00 kaydı
başka bir gösteri diye eklenmez veya üç saat çıkarılarak yeniden yazılmaz.

Aynı mekân/günde görünür HTML seansı varsa, HTML ile eşleşmeyen JSON saatleri
`unconfirmed_json_sessions` sayacına ve kısmi kapsam uyarısına gider. İlgili HTML
kartında source_time_conflict ve uyarı korunur. Bu politika görünür listede
bulunmayan gerçek bir ek seansı da doğrulama gelene kadar dışlayabilir; eksiksiz
katalog iddiası yerine bu sınırlama açıkça bildirilir.

Başka tarih/mekândaki JSON-only kayıtlar ve görünür HTML'ye tam eşleşen gerçek
UTC gece yarısı seansları korunur. 0.6.1 offset uzlaştırması da korunur.
Yenileme transaction'ı eski ek JSON performansını pasifleştirir; eski seçimi
başka saate sessizce taşımaz.

## Esnek giriş sözleşmesi

Ayrıştırıcı, aynı tarihte istenen saatte kullanım bilgisini açık kaynak metninden
okur; yalnız saatin 23.59 olması veya ürün başlığı esnek giriş kanıtı değildir.
HTML saat içermese de tam kaynak tarihlerinden yılı doğrulanabilen gün, gerçek
HTML seans kimliği, bilet türleri ve bağlantı tutulur.

| Alan | Saatli seans | Esnek giriş |
|---|---|---|
| timing_kind | scheduled | flexible_entry |
| event_date | Seansın İstanbul tarihi | Kaynakta listelenen tarih |
| start_at | Kaynak başlangıcı ISO | null |
| source_start_at | Genellikle null | Varsa kaynağın ham zaman anlamı taşıyan damgası; ziyaret saati değil |
| end_at / end_known | Kaynak/süre kanıtına göre | null / false |
| start_time_basis | provider_datetime, html_session, json_ld | html_date veya JSON-only kaynağında json_ld |

SQLite'daki zorunlu datetime, esnek giriş için yalnız yerel tarih indeksleme
ankorudur; kullanıcıya başlangıç diye sunulmaz. Tarih boyunca kaydın başlamış
sayılması engellenir. Takvim güne göre değerlendirilir; kaynakta yayımlanan
rezervasyon, yaş/boy ve kullanım istisnalarının ayrıca doğrulanması gerekir.
Liste tarihi, işletmenin açık veya biletin herkese geçerli olduğunun kanıtı değildir.

Saat aralığı verilmiş normal arama, esnek giriş için o aralığı doğrulayamayacağı
için kaydı dışlar; `filter_counts.excluded_unverified_time` bunu açıklar.
Tarih/metin/fiyat araması esnek kartları döndürebilir; bilinmeyen fiyat ücretsiz
sayılmaz. Aynı gündeki gerçek 00.00 seansı ile esnek tarih kaydı tekilleştirilmez.

## Plan ve takvim

Planın saatli `options` ve `unverified_budget` alanları yalnız scheduled
performansları içerir. Esnek biletler en fazla 20 kartlık `flexible_entries`
alanında ayrı görünür. flexible_entry_count tüm uygun esnek aday sayısını,
flexible_entries_truncated kırpılmayı açıklar. Tarih, program/satış, tür, yaş
ve bilinen bütçe sınırları uygulanır; ayrı liste bütçe veya giriş garantisi değildir.

`rejected.reason=flexible_entry_requires_visit_time` ile kaynakta ziyaret saati
ve giriş koşullarını doğrulama adımı verilir. 23.59, takvim veya etkinlikler
arası süre hesabına sokulmaz. Takvim üreticisi ayrıca doğrudan esnek kart
verilmesine karşı korunur; sahte VEVENT veya Google Calendar bağlantısı üretmez.

Yayımlanmış araç adları ve giriş parametreleri korunur. Mevcut saatli kartlar
ISO başlangıç taşımaya devam eder. Esnek kartta null başlangıç sunulması bilinçli
sözleşme düzeltmesidir; istemciler event_date ve timing_kind okumalıdır. MCP
araç açıklamaları, etkinlik prompt'u, yanıt rehberi ve canlı QA denetleyicileri
bu davranışa göre güncellendi. Yeni tablo, migration veya env değişkeni yoktur.

## Regresyonlar ve canlı kanıt

```bash
pytest tests/test_events_flexible_and_unconfirmed.py tests/test_events_source_time.py
```

Kurmacaya dayalı küçük HTML fixture'ları ek JSON saatini ve saat içermeyen
esnek girişi yeniden üretir. Tarih/clock araması, gün içindeki tarih ankoru,
gerçek gece yarısıyla tekilleştirme, seçili kimlik, ayrı esnek liste ve takvim
koruması dış ağa çıkmadan sınanır. İlk koşuda bu yeni gruptaki yedi test eski
kodun davranışı yüzünden düştü; kanıt `.data/events-flexible-before.xml` ve
`.data/events-flexible-before.log` içindedir.

İlk katalog yüklemesinde Biletinial kaydı henüz detaydan geçmemişse, plan
`session_detail_required` ile onu dışlar ve istanbul_event_detail çağrısını
önerir. Böylece esnek giriş türü henüz keşfedilmemiş 23.59 liste damgası da
saatli öneri/takvime giremez. Ticketmaster feed'in kendi saatli gözlemleri bu
Biletinial doğrulama koşulundan etkilenmez.

Tam sonuçlar `.data/events-flexible-*.xml` içinde tutulur. Aynı farklı 50 sorunun
0.7.0 canlı tekrar raporu ve iki bulgunun hedefli MCP kontrolleri, deploy sonrası
`docs/qa/events-flexible-fix-live-0.7.0-2026-11-08.md` içinde kaydedilir. Ham veya
büyük kaynak gövdeleri, anahtarlar ve özel yakalamalar repoya eklenmedi.

Son ağsız doğrulama: etkinlik/ilk-yükleme grubunda 73 test geçti. Tam tekrar
1.788 test topladı; 1.723 geçti, 65 atlandı, 0 hata/başarısızlık. Kanıt
`.data/events-flexible-full-clean.xml` içindedir. Önceki iki başlangıç sürüm
hatası editable kurulum güncellenerek giderildi; ayrı koşuda bir kez gecikme
bildiren 0,2 saniyelik watchdog testi tekil 13-test grubunda ve son tam
koşuda geçti. Başarısız koşuların log/XML dosyaları korunmuştur.
