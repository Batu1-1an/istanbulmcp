# İstanbul etkinlik keşfi ve günlük planlama

## Etkinleştirme ve kapsam

0.6.0 başlamış seansları varsayılan dışlar; `include_past=true` halen aktif
yerel geçmiş kayıtlara izin verir. Fiyat zaman aşımı korunur. Sayaçlar ve
detay yaşam döngüsü [ücretsiz etkinlik incelemesinde](events-free-lifecycle.md).

0.5.1 müzikal türünün yanlışlıkla konser sayılmasını ve diskteki snapshot
yeniden kullanılırken TTL'in baştan başlamasını düzeltir.
[Kanıt ve regresyonlar](events-musical-refresh-fix.md).

0.5.3, eşit fiyattaki tükenmiş bir teklifin satıştaki biletin tür/indirim
etiketini belirlemesini düzeltir. Birleşik filtreler, zaman sınırları ve
eşzamanlı okuma/yenileme kontrolleri [ayrı rapordadır](events-cross-validation.md).

`istanbul_events_search`, `istanbul_event_detail`, `istanbul_events_plan` aynı
ResponseEnvelope sözleşmesini kullanır. `EVENTS_ENABLED=true` araçları açar;
varsayılan kapalıdır. Kapalı araçlar listelenmez ama `feature_disabled` ile
çağrılabilir kalır. Ticketmaster için `TICKETMASTER_API_KEY`, Biletinial için
ayrıca `EVENTS_BILETINIAL_ENABLED=true` gerekir. Anahtar tek başına açmaz.

| Kaynak | Görev | Sınır |
|---|---|---|
| Ticketmaster TR feed | Biletix bağlantılı katalog, saat, mekân ve program durumu | Fiyat ve bilet bulunabilirliği bilinmiyor; bitiş sıklıkla yok |
| Biletinial kategori JSON'u | İstanbul keşfi, listelenen başlangıçlar | Temsili/eksik seans; mekân/fiyat için detay gerekir |
| Biletinial HTML + JSON-LD | Seans kimliği, mekân, fiyat türü, açık tükenmişlik | HTML tarihi tam kaynak tarihiyle eşleşmelidir; belirsiz seans atlanır |

Biletix web sayfaları/iç API/sitemap çağrılmaz. Discovery API, DTO, İBB ŞT,
Zorlu, Etkinlik.io, Passo ve sinema bu sürümün connector'ları değildir.
Araştırmada incelenmiş olmak uygulandığı anlamına gelmez. Otomatik erişim,
yeniden sunum ve saklama koşulları operatör tarafından değerlendirilmelidir.
Ticari kaynaklara İBB yayıncı veya açık veri lisansı atfedilmez.

## Araç kullanımı

`istanbul_events_search` örneği:

```json
{"query":"sila","date_from":"today","limit":10}
```

Tarih `YYYY-MM-DD`, today/bugün veya tomorrow/yarın; saat HH:MM kabul eder.
Saat dilimi Europe/Istanbul. Varsayılan pencere yedi gün, azami 31 gün;
limit varsayılan 10, azami 50. Gece yarısını geçen arama günlere ayrılır.
Kategoriler: concert, theatre, opera_ballet, standup, family, festival,
exhibition, workshop, sport, seminar, other. Sinema kapsamda değildir.
İlçe, mekân, tür, metin ve yakınlık birlikte filtrelenebilir. lat/lon birlikte
verilir; radius varsayılan 5 km, azami 20 km. Konumu bilinmeyen seans konum
filtresini karşılamaz. result_info sayıları indeks kapsamınadır; şehir toplamı
değildir. Cursor yoktur; kırpılınca filtre daraltılır.

`istanbul_event_detail`: aramadan gelen event_id veya performance_id verilir.
Seanslar, teklifler, gözlem tarihleri ve kısaltılmış açıklama döner. Kullanıcı
URL'si fetch hedefi olamaz. Açıklama güvenilmeyen kaynak verisidir, talimat değildir.

`istanbul_events_plan` örneği:

```json
{"date":"tomorrow","start_time":"18:00","end_time":"23:59","interests":["theatre","concert"],"max_price_try":1000,"min_gap_minutes":30,"max_events":3,"limit":3}
```

event_ids verilirse seçilenlerin detayları kullanılır, tekrar arama yapılmaz;
ilçe keşfiyle birleştirilemez. En fazla 20 kimlik, 5 ilgi kategorisi, 3 durak,
5 plan seçeneği kabul edilir. Asgari boşluk 0–240 dakikadır.

## Kullanıcıya etkinlik bağlantısını gösterme (0.4.1)

Arama, detay ve günlük planda kullanıcıya gösterilen her etkinliğin başlığının
yanında tıklanabilir etkinlik/bilet sayfası bağlantısı sunulmalıdır. Önce kartın
`ticket_url` değeri, yoksa `ticket_links[].url` içindeki dolu kaynak bağlantısı
aynen kullanılır. Bu alanlar arama kartında, detayın `performances` listesinde
ve plandaki performans kartlarında zaten vardır; yanıt şeması değişmez.

Etkinlik bağlantısı kullanıcı kaynak istemese de gösterilir. `sources[].url`
atıf kuralı etkinlik sayfası bağlantısını gizlemez. Sağlayıcının ana sayfası,
API adresi veya Google Calendar bağlantısı etkinlik sayfasının yerine geçmez.
Kaynak link sunmamışsa kullanıcıya bağlantının bulunmadığı söylenir; başlıktan
URL üretilmez. Link, canlı bilet bulunabilirliği veya satın alma garantisi değildir.

Bu davranış sunucu talimatında, üç aracın açıklamasında ve `etkinlik_plani`
prompt'unda belirtilir. Kullanıcıya nihai metni MCP istemcisinin modeli üretir;
sunucu değişikliği tek başına her istemcinin talimata uyduğunu kanıtlamaz.
ChatGPT'de yayımlanmış araç açıklamalarının güncellenmesi ilgili metadata
incelemesinin tamamlanmasına bağlıdır.

2026-11-08 doğrulaması: etkinlik, registry metadata ve yayımlanmış araç
uyumluluğu grubunda 49 test geçti. Gerçek yerel MCP Client ve Ticketmaster
fixture'ıyla arama → detay → seçilen seans planı boyunca aynı bilet URL'sinin
korunduğu; üç aracın açıklaması ve etkinlik prompt'unda link talimatının
sunulduğu doğrulandı. Kullanıcıya üretilen nihai LLM cevabı bu kontrolde
ölçülmedi. Tekrar komutu:

```bash
pytest tests/test_events.py tests/test_registry_metadata.py tests/test_tool_compatibility.py
```

## Fiyat, satış ve program durumu

Program durumu iptal/ertelemeden, satış penceresi onsale/offsale bilgisinden,
bilet uygunluğu teklif kanıtından gelir. transactable=false ve offsale
tükenmişlik değildir. Kaynaktan kaybolmak da iptal anlamına gelmez.
Öğrenci/tam/kampanya teklifleri ayrı tutulur. Kart gözlenen en düşük TRY fiyatını
gösterir; indirim hakkı veya ödeme tutarı garanti edilmez. Dahil olduğu
doğrulanmadığında fees_included=null kalır; tek bir hizmet bedeli oranı genellenmez.

Bilinmeyen fiyat ücretsiz değildir. free_only yalnız gözlenen sıfır fiyatı
kabul eder, max_price_try ile birleştirilmez. Aramada bilinen bütçe aşımı elenir,
bilinmeyen fiyat budget_status=unknown ile sonra sıralanır. Planda bütçe toplam
gözlenen minimumlara uygulanır; bilinmeyenler unverified_budget içine ayrılır.
Bilet durumu gözlemdir; canlı koltuk ve checkout garantisi yoktur.

## Katalog, kimlik ve arama

SQLite WAL içinde seri, seans, mekân, teklif, dış kimlik ve kaynak snapshot
tabloları bulunur. Aynı kaynak kimliğinin saat değişimi iç kimliği değiştirmez.
Biletinial liste seansları geçici tarih kimliğine, detay gerçek HTML seans
kimliğine sahiptir; güven düzeyleri aynı değildir.

Kaynak snapshot'ı tek transaction içinde yayımlanır. Ayrıştırma, sayfa, boyut
ve kayıt bütçesi hatası önceki sağlam snapshot'ı bozmaz. Kaybolan kayıt pasif
olur; başarılı yayınlarda iki günlük pasif içerik saklama penceresi temizlenir.
Foreign key denetimi her bağlantıda açıktır. FTS5 trigger'larla eşzamanlıdır;
RTree kutusundan sonra kesin kuş uçuşu mesafesi kontrol edilir.

Görünen Türkçe başlık korunur, indeks metni katlanır: Sıla/sila, İclal/iclal.
Kullanıcı FTS operatörleri çalıştırılmaz; normalize kelimelerden parametreli
tam kelime sorgusu kurulur (`match_mode=words`, 0.5.0 varsayılanı).
Kök/otomatik tamamlama için `match_mode=prefix` açıkça seçilir; örneğin
`sıla` yalnız prefix modunda `Silahşör` kelimesine eşleşebilir. Boş query,
filtre verilmemiş gibidir. Typo düzeltmesi/vektör arama uygulanmaz. Tekilleştirme
aynı başlık/başlangıç/bilinen mekândaki farklı sağlayıcılara uygulanır. Aynı
sağlayıcının farklı seans kimlikleri birleştirilmez; Biletix seq alanının her
zaman teklif türü olduğu varsayılmaz.

## Tazelik

Lifespan açık kaynakları ayrı arka plan döngülerinde yeniler. Uzun Biletinial
taraması Ticketmaster sonuçlarını bekletmez. İlk katalog yoksa araç sınırlı
ilk yüklemeyi deneyebilir. TTL sonrası azami yaş içindeki snapshot stale döner;
aşırı eski kaynak sorguya katılmaz. İndirme zamanı kaynak yayın zamanı değildir.
Kaynak kontrol/başarı ve kapsam sayıları sources içinde, detay gözlem zamanı
karttadır. Boş sonuç şehirde etkinlik olmadığı anlamına gelmez.

`sources[].refresh_status` süreç içindeki idle/refreshing/failed/unavailable
durumunu, `serving_stale` halen kullanılabilir son iyi snapshot'ın stale
sunulduğunu gösterir. Başarısız yenileme TTL içinde olsa da freshness stale
olur. Yenileme sürerken son kullanılabilir snapshot okunabilir; yeni snapshot
transaction sonunda bütünüyle görünür. Hiç başarılı snapshot yoksa veya azami
fallback yaşı aşılmışsa veri varmış gibi davranılmaz. Farklı çağrılar aynı
snapshot'a sabitlenmez; kaynak ve detay güncellemeleri sonuçları değiştirebilir.

## Planlama ve takvim

En fazla 20 adayda deterministik tam sayım yapılır. İlgi, bitiş, fiyat,
detay doğrulaması ve uygunluk puanları score_breakdown içindedir. Puan yüzde
değildir. candidate_truncated/evaluated_candidates aday sınırını açıklar;
şehir genelinde en iyi plan bulunduğu iddia edilmez.

Bitişi bilinmeyen seans yalnızca son durak olur; pencere içinde biteceği
doğrulanmaz. İptal, erteleme, açık tükenmişlik ve kapalı satış elenir. Saat
çakışması/minimum boşluk kontrol edilir; ulaşım süresi hesaplanmaz. Yaka değişimi
uyarılır. Mekânlar arasında yetişilebilirlik garantisi verilmez.

Her durak ayrı ICS VEVENT olur: kararlı UID, UTC tarihler, metin kaçışları ve
UTF-8 satır katlama. Bitiş yoksa sahte DTEND yazılmaz; o seans için Google
Calendar bağlantısı üretilmez. Dış takvime yazma yapılmaz.

## Ayarlar

| Değişken | Varsayılan |
|---|---:|
| EVENTS_ENABLED | false |
| TICKETMASTER_API_KEY | boş, secret |
| EVENTS_BILETINIAL_ENABLED | false |
| EVENTS_CACHE_TTL_SECONDS | 3600 |
| EVENTS_STALE_IF_ERROR_SECONDS | 86400 |
| EVENTS_DETAIL_TTL_SECONDS | 900 |
| EVENTS_MAX_FEED_BYTES | 8388608 |
| EVENTS_MAX_UNCOMPRESSED_BYTES | 33554432 |
| EVENTS_MAX_ROWS | 10000 |
| EVENTS_BILETINIAL_MAX_PAGES | 40, kategori başına |

Detay gövdesi en fazla 2 MB, açılmış içerik 4 MB. HTTP indirmesi süreyle
sınırlıdır. Anahtar yalnız ilk resmî Ticketmaster isteğine gider; doğrulanmış
S3 feed yoluna orijinal parametreler aktarılmaz. Yapılandırma sınırları
uygulama başlangıcında doğrulanır.

## Doğrulama kaydı ve teknik kaynaklar

2026-11-07 geliştirme kontrolü: Ticketmaster TR feed 1.748 kayıt; yeni parser
718 İstanbul kaydı kabul etti, ayrıştırma nedeniyle 0 kayıt atladı. Bir
Biletinial detayında dört HTML seansı ve öğrenci/tam fiyatları ayrıştırıldı.
Bunlar tarihli örneklerdir; bütün katalog kabulü veya sabit kapsam garantisi değildir.
Fixture/servis/depolama/plan/MCP testleri tests/test_events.py içindedir.
Tam test/yayın sonuçları uygulama tamamlanırken burada güncellenir.
[Kabul koşulları](plans/2026-11-07-events-implementation.md).

Kontrol edilen kaynaklar: [Ticketmaster feed](https://developer.ticketmaster.com/products-and-docs/apis/discovery-feed/),
[sürüm notları](https://developer.ticketmaster.com/products-and-docs/apis/discovery-feed/release-notes/),
[HTTPX streaming](https://www.python-httpx.org/async/), [SQLite FTS5](https://sqlite.org/fts5.html),
[MCP SDK](https://github.com/modelcontextprotocol/python-sdk).

### Arka plan zenginleştirme ve doğrulama komutu

Biletinial açıksa her kaynak döngüsü en fazla 10 eksik/eski seri detayını
yeniler; detay istekleri arasında bir saniye beklenir. Bütün seansların
anında doğrulandığı varsayılmaz. Güncel detaylar sonraki katalog taramasında
24 saate kadar korunur; fiyat/uygunluk kendi detay TTL süresini aşınca
bilinmiyor olur. Kullanıcı detay çağrısı ilgili seriyi ayrıca yenileyebilir.

Etkinlik açıkken `etkinlik_plani` workflow prompt’u da listelenir. HTTPX
kayıtlarındaki apikey sorgu değerleri maskelenir. Yeni tekilleştirme kuralı
ilçe/koordinat çelişkisi olan aynı adlı mekânları birleştirmez.

Canlı kabul: `railway run .venv/bin/python scripts/check_events.py`. Gerçek feed,
geçici SQLite ve üç MCP aracını kullanır; deploy veya production DB yazımı yoktur.

Bugünden başlayan arama, başlamış seansları gelecek seçenek gibi sunmaz.
Aynı seansın farklı sağlayıcıları eşleştiğinde bilet linkleri ve sağlayıcı
uygunluğu ayrı kalır: bir sağlayıcı tükenmiş, diğeri bilinmiyorsa birleşik
uygunluk bilinmiyor olur; bütün platformlarda tükenmiş varsayılmaz.

Biletinial canlı katalog kontrolü (2026-11-07): canonical uç
`https://biletinial.com/tr-tr/List/GetMoreItems`, cityId=147. Dört kategoride
1.153 seri ve 3.435 listelenen başlangıç ayrıştırıldı. Liste seansları
provisional olduğundan bu sayı doğrulanmış mekân/fiyat kapsamı değildir.
Eski www/List yolu iki yönlendirme gerektirdiği için canonical uç kullanılır.

Geniş regresyon kontrolü 2026-11-07 tarihinde başarılı tamamlandı; dış ağ
gerektiren opt-in testler varsayılan olarak atlandı. Gerçek Ticketmaster kaynağıyla
`railway run .venv/bin/python scripts/check_events.py` arama, detay ve plan
çağrılarını başarıyla doğruladı. HTTPX loglarında API anahtarı maskelendi.
Ek Streamable HTTP, workflow prompt, eski fiyat ve kaynağın azami yaşını
aşması testleri etkinlik test grubundadır.

### Railway yayını — 2026-11-07

Sürüm 0.3.0, production/istanbulmcp servisine
`cadd3921-90af-48c1-a3ed-2426cf052599` deployment ile yayımlandı (SUCCESS).
EVENTS_ENABLED ve EVENTS_BILETINIAL_ENABLED açık; değişkenler skip-deploys ile
ayarlanıp tek deploy yapıldı. Initialize sürümü 0.3.0; tools/list 21 araç
(üç etkinlik aracı dahil); healthz 200 doğrulandı.

Üretim araması ilk kontrol anında Ticketmaster 718/1.748 İstanbul/TR kayıt ve
Biletinial 3.423 listelenen başlangıç bildirdi. Bunlar tarihli snapshot
sayılarıdır, sabit kapsam değildir. Üretimde bir detay çağrısı 23 seans döndürdü.
Son yerel hedefli doğrulamada etkinlik, metadata ve depolama grubunda 45 test
başarılıydı; geniş regresyon da geçti. Gerçek python -m app.main süreciyle
healthz/readyz 200, WAL ve schema_version=2 kontrol edildi.

### Kaynak isteği hız sınırı (0.3.1)

Katalog ve kullanıcı detay istekleri süreç içinde host başına ortak token
bucket kullanır: burst=1, saniyede 1 istek. Kuyruk beklemesi indirme zaman
bütçesine dahildir. HTTP 429, Retry-After değerini (en fazla 3600 saniye)
ortak cooldown’a uygular; geçersiz başlıkta 60 saniye kullanılır. Paralel
istemciler ve arka plan taraması ayrı sınırsız istek bütçeleri alamaz.

Üretim kabulünde yarın için üç plan seçeneği, 20 değerlendirilmiş aday ve
açık aday kırpma bilgisi döndü. Her seçenekte en fazla üç durak, çakışmasız
saatler ve durak sayısıyla eşit VEVENT sayısı doğrulandı. Kadıköy filtresi
beş doğru ilçe sonucu verdi. limit=0 validation_error döndürdü; eski
istanbul_parking_nearby adı doğrulama yanıtıyla çağrılabilir kaldı.

### 0.3.1 doğrulama kapsamı

Etkinlik/registry/structured-output/uyumluluk grubunda 117 test, 0 hata;
son HTTP cooldown değişikliğinden sonra etkinlik grubunda 32 test tekrar
başarılı tamamlandı. Yeni testler HTTP akışı, prompt, 429 cooldown, gizli
anahtar maskeleme, seans HTML sınırları, snapshot koruma, bayat teklifler ve
sağlayıcıya özel tükenmişlik durumlarını kapsar.

Ana uygulama ve test/fixture değişiklikleriyle birlikte README, tool-reference,
configuration, development, response-contract, monitoring, privacy, deploy-railway,
CHANGELOG, .env.example ve sürüm manifestleri güncellendi. Secret taramasında
değişen/eklenen dosyalarda API anahtarı bulunmadı; .env ignore kapsamında.

### 0.3.1 üretim kaydı

Kaynak hız sınırı düzeltmesi `15ebad61-bcce-4b67-953d-c60722fdde3e`
deployment ile yayımlandı. Gerçek initialize yanıtı 0.3.1, tools/list 21 araç;
healthz ve readyz 200. 2026-07-28 protokol metadata’sıyla arama sonucu
ResponseEnvelope doğrulamasından geçti. Detay dört seans, günlük plan üç
seçenek döndürdü.

İlk yüklemede Biletinial için bir OperationalError loglandı; sonraki arka plan
yenilemesiyle kaynak kendiliğinden checked durumuna geldi. Son kontrolde
Ticketmaster 718/1.748 İstanbul/TR kayıt, Biletinial 3.395 listelenen başlangıç
ile checked idi. Araştırma ve önceki kontrol sayılarının farklı olması
normaldir: bunlar değişen kaynak snapshot’larıdır.

İstemcide yeni araçlar görünmüyorsa MCP bağlantısı/tools-list önbelleği
yenilenmelidir. Sinema, canlı koltuk ve gerçek ulaşım süresi bu sürümün
kapsamında değildir; bütün sonuçlarda kaynak ve belirsizlik korunur.

## 0.4.0: kullanıcı sorularından gelen iyileştirmeler

[Persona doğrulama raporu](events-persona-validation.md) bulguları ve ölçüm
sınırlarını içerir. Üç yayımlanmış tool adı ve ResponseEnvelope korunur.

### Yeni arama kontrolleri

- Türkçe kategori adları: tiyatro, konser/müzik, çocuk/aile, opera/bale,
  stand-up, sergi, atölye, spor, seminer kabul edilir; çıktı canonical kalır.
- `child_age=0..17`: yalnız family türü ve yayımlanmış uyumlu yaş kuralı kabul
  edilir. Kaynak yaş belirtmiyorsa sonuç dışlanır. Bu sanat zevki/ilgi düzeyi
  tahmini değil, kaynaktaki yaş kuralı kontrolüdür.
- `include_unknown_prices=false`: bilinmeyen fiyatlar sonuçlardan çıkarılır.
  Varsayılan true olarak geriye uyumludur; bilinmeyen fiyat bütçeye uygun sayılmaz.
- `include_sold_out=false` varsayılanıyla açıkça tükenmiş seanslar dışlanır.
  İncelemek isteyen kullanıcı true verebilir. Unknown stok hâlâ bilet garantisi değildir.
- `query_scope=title` varsayılandır; `all` mekân adlarını da arar. Prefix eşleşmesi
  exact title token eşleşmesinden ayrılır; bu sanatçı kimliği çözümlemesi değildir.
- Fiyat/ücretsiz/aile sorularında ilgili en fazla üç Biletinial seri detayı, toplam
  12 saniye bütçe içinde kontrol edilir. Kaynak listesi fiyat/free ipuçları yalnız
  hangi detayın kontrol edileceğini önceler; kartta doğrulanmış fiyata dönüşmez.
- Kart price nesnesi en düşük teklifin adını ve olası indirim/uygunluk koşulunu
  taşır. Öğrenci fiyatı tam bilet/son ödeme tutarı gibi sunulmamalıdır.
- `distance_kind=straight_line`; karşı yaka yarıçapa girebilir. Yürüyüş/ulaşım
  süresi hesaplandığı varsayılmaz. Turun kaynak mekânı kalkış iskelesi olabilir.

### Yaş ve süre kaynağı

Biletinial'ın ayrı Etkinlik Türü, Yaş Sınırı ve Süre fact alanları okunur.
Çocuk Oyunu/Tiyatrosu/Konseri family olarak işaretlenir; masal başlığından
çocuk uygunluğu tahmin edilmez. Açık Stand Up başlığı/genre bilgisi sınıflandırılır.
Seansın doğrudan endDate değeri yok ama seri süresi yayımlanmışsa bitiş hesaplanır
ve `end_source=published_duration` olur. Doğrudan bitiş `source_end`, bilinmeyen
bitiş `unknown` kalır. Bunlar program saatidir, gerçek gecikmesiz bitiş garantisi değildir.

### Planlama kontrolleri

`interests` istenen türlerin dışına çıkmaz. Önce tür filtresi uygulanır; ilk
arama sayfası yerine bounded gün indeksi değerlendirilir. Günün saatlerine ve
ayrı serilere yayılan 20 aday seçilir. Category diversity puanı görünürdür;
yine şehir genelinde optimal plan veya ulaşım garantisi verilmez.

`child_age` plana da uygulanır. `require_known_end=true` bilinmeyen bitişleri
reddeder; false iken önceki son-durakta-belirsiz-bitiş davranışı korunur.
`event_ids` içinde event_id tüm seri seanslarına, performance_id seçilen tek
seansa karşılık gelir. Geçici liste kimliği doğrulanınca tek eşleşmeye
bağlanabilir; eşleşme yok/belirsiz ise `selection_changed` ile yeni seçim istenir.

### Depolama ve arka plan

Schema version 3, event_detail_checks ile seri bazlı son deneme/başarı ve
next_check_at tutar. Başarısız detay beş dakika geri çekilir. Geçmiş seanslar
arkadaki yenileme işini tüketmez; önümüzdeki 31 günün yakın seansları önce gelir.
Onluk batch sonrası iş varsa beş saniye, yoksa en fazla 60 saniye beklenir.
Host başına ortak 1 istek/s sınırı korunur. Şema ilk kurulumu dosya başına
serialize edilir; sıradan okumada her defasında DDL çalıştırılmaz.

### Tekrar çalıştırma

```bash
pytest tests/test_event_personas.py tests/test_events.py
railway run .venv/bin/python scripts/events_persona_uat.py --output .data/events-persona-uat.json
```

Sorular ve explicit argüman eşlemeleri fixture içindedir. Startup/source preflight
başarısızlığı ayrı raporlanır; boş sonuç etkinlik bulunduğu anlamına gelmez.

`etkinlik_plani` prompt'u isteğe bağlı `child_age` ve `end_time` metin
argümanlarını kabul eder. Yaş koşulunu, kesin bitişte `require_known_end=true`
kullanımını, bilinen fiyat filtresini ve seçilen `performance_id` değerinin
korunmasını istemciye açıklar. Prompt kendisi araç çağırmaz.

### 0.4.0 üretim kaydı

2026-11-07, deployment `3a70f0b2-1a48-4000-a253-4704b4bdcdf4` başarılı.
Initialize 0.4.0, tools/list 21; healthz/readyz 200, WAL ve schema_version=3.
Yeni environment değişkeni gerekmedi. Bu sürümdeki tüm test sonuçları ve
üretim persona kontrolü [doğrulama raporunda](events-persona-validation.md).

## 0.5.0: 100 senaryolu QA incelemesi

[Bulgu bazlı inceleme](events-100-review.md), ilk raporun gerçek kusurlarıyla
test/kanıt hatalarını ayırır. Kaynak türü tüm desteklenen kategorilere eşlenir.
Genel Etkinlik kovasındaki açık Atölyesi/Sergisi/Festivali/Seminer başlık
işaretleri `category_source=title_marker`, ayrı kaynak türü `provider`, kanıt
yoksa `unknown` olur. Bu sınıflandırma çocuk yaş uygunluğu değildir.
Kategori filtresinde kayıt gözlenmediyse `limits` içinde
`category_coverage=not_observed` ve tarih/sorgu/indeks kapsamı belirtilir;
bu alan şehir toplamı veya kategorinin kalıcı olarak desteklenmediği anlamına gelmez.

Tür/bütçe/ücretsiz soruları azami üç ilgili seriyi aynı 12 saniye bütçesinde
doğrulayabilir; title-marker yalnız doğrulanacak adayı önceliklendirebilir,
fiyat veya yaş kanıtı üretemez. Fazladan doğrulama gecikmeyi artırabilir.

Plan alternatifleri bilinen gözlenen toplamları öne alır ve gösterilmiş seri
kümeleriyle örtüşmeyi azaltır. Aynı seri kümesinin farklı seans varyantları
tekilleştirilir; limit üst sınırdır. Ham score/score_breakdown korunur, seçim
sırası yalnız ham score'a göre değildir. `total_observed_minimum_try` tüm
fiyatlar gözlenmişse toplam, aksi halde null'dır. Mevcut
`known_minimum_total_try` eksik toplamda yalnız ara toplamdır; son ödeme tutarı değildir.

Seçilen seans da verilen tarih ve 18:00–23:59 varsayılan penceresine uyar.
Dışarıda kalırsa kullanılan pencere ve start_time/end_time/tarih onarımı döner;
istemcinin verdiği pencere sessizce genişletilmez. Plan ID'lerinin çevre
boşluğu seçilen tek seansı bütün seriye dönüştürmez.

```bash
pytest tests/test_events_qa_findings.py
railway run .venv/bin/python -m scripts.events_100_uat --output .data/events-100-current.json
```
