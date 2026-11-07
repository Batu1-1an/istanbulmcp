# Etkinlik sistemi: kullanıcı senaryoları ve iyileştirmeler

## Yöntem

Öğrenci, ebeveyn, turist, sanatçı takipçisi, mekân/ilçe odaklı kullanıcı ve
günlük plan isteyen kişiler için farklı sorular hazırlandı. Bunlar gerçek
kullanıcı oturumları değildir. Sorular açık tool argümanlarına eşlenir;
bu çalışma LLM'nin doğal dil yönlendirmesini değil, tool sonucunun kullanıcı
koşullarına uyumunu sınar.

Başlangıç ölçümü production 0.3.1 üzerinde 26 soruyla yapıldı. Ardından
soru seti yeni yaş, fiyat ve bitiş kontrolleriyle genişletildi. Aynı sorular
gerçek kaynakları kullanan yerel aday sunucuda yeniden çalıştırıldı.
Kaynaklar zamanla değişir; sonuç sayıları kontrollü bir A/B deneyi veya
şehir kapsamı ölçümü değildir. Ağsız regresyonlar davranışı sabit fixture'larla
ayrıca kanıtlar. Boş ama dürüst bir sonuç, etkinlik bulunduğu anlamına gelmez.

Dosyalar:

- `tests/fixtures/events/persona_queries.json`: sorular, persona ve explicit argümanlar.
- `scripts/events_persona_uat.py`: preflight, gerçek MCP çağrıları ve semantik denetimler.
- `tests/test_event_personas.py`: bulgulardan çıkarılan ağsız regresyonlar.
- `.data/events-persona-*.json`: yalnız yerel özet raporlar; ham cevap ve secret yok.

## Başlangıç bulguları

| Kullanıcı ihtiyacı | 0.3.1 gözlemi | Yapılan düzeltme |
|---|---|---|
| Yalnız aile etkinliklerinden plan | Plan theatre ile dolduruldu | İlgi türleri keşiften önce uygulanır; ilgisiz fallback yok |
| Türkçe tiyatro kategorisi | validation_error | Türkçe kategori eşanlamlıları normalize edilir |
| Çocukla gündüz etkinliği | Family araması boş; çocuk oyunları theatre içindeydi | Kaynağın ayrı Etkinlik Türü alanı okunur |
| Çocuğun yaşına uygun seçim | Yayımlanmış yaş aralığı sunulmuyordu | child_age yalnız kaynak yaş aralığına göre filtreler |
| Bütçeyle seçim | İlk sonuçlarda güncel fiyat yoktu | En fazla üç ilgili detay 12 saniye içinde kontrol edilir; unknown fiyat dışlanabilir |
| Bitiş saati zorunluluğu | Bilinmeyen bitiş yalnız uyarıyla kalabiliyordu | require_known_end bilinmeyen bitişi reddeder |
| Belirli seansı seçme | performance_id tüm seri seanslarına açılıyordu | Seçilen performans korunur; belirsiz eşleşmede yeni seçim istenir |
| Gün içine yayılmış plan | İlk sayfa/saatler sonraki etkinlikleri dışlıyordu | Bounded gün indeksi türden geçirilir; saat ve seri çeşitliliğiyle 20 aday seçilir |
| Başlıkta metin arama | Yalnız mekân adına da eşleşebiliyordu | Varsayılan title kapsamı; all kapsamı ayrıca seçilir |
| Gidilebilecek çocuk gösterisi | İkinci turda bazı sonuçlar açıkça tükenmişti | SoldOut varsayılan dışlanır; incelemek isteyen opt-in açar |
| Kaynak yakınlık yorumu | Boğaz'ın karşısı kuş uçuşu yakındı | distance_kind ve karşı yaka/ulaşım uyarısı açıklaştırıldı |

Biletinial'ın canlı [Çizmeli Kedi sayfasında](https://biletinial.com/tr-tr/tiyatro/cizmeli-kedi-sariyer-snt)
ayrı çocuk oyunu türü, 3–10 yaş aralığı ve 50 dakikalık süre görüldü. Çocuk
uygunluğu masal başlığından veya kategori tahmininden üretilmez. GetKidsEvents
ucu bu kontrolde 500 verdi; çalışmayan bir kaynak eklenmedi.

## Yerel gerçek-kaynak yeniden testi

Son tamamlanan aday koşusunda 33 sabit soru ve bir seçilen-seans workflow'u,
toplam 34 senaryo, 0 semantik/protokol hatası:

| Senaryo | Başlangıç | Yerel aday gözlemi |
|---|---|---|
| Aile gündüz araması | 0 sonuç | 10 family sonucu, 10 gözlenen fiyat |
| Aile planı | theatre içeriyordu | Üç seçenek; yalnız family, ikişer durak |
| Ücretsiz arama | 0 doğrulanmış fiyat | İlk 10 sonuçta gözlenen fiyat 0 |
| Tiyatro + konser planı | Yalnız theatre | İki türü içeren ikişer duraklı seçenekler |
| 500 TL toplam bütçe | Yalnız unverified_budget | Üç gözlenen-minimum bütçe seçeneği; bilinmeyenler ayrı |
| 90 dakika boşluk | Tek duraklı seçenekler | Üçer duraklı seçenekler, minimum boşluk korunuyor |
| 5 yaşındaki çocuk | Kontrol yoktu | İlk 10 sonuç yayımlanmış uyumlu yaş aralığında, açık tükenmişlik yok |
| Yalnız bilinen fiyat ≤1000 TL | Kontrol yoktu | İlk 10 sonucun tamamı gözlenen fiyatlı |

Bazı test argümanları yeni yeteneği açıkça istemek için değişti:
erken bitişe require_known_end, sıfır bütçeye include_unknown_prices=false,
sanatçı/konser sorusuna category=concert eklendi. Bunlar aynı argümanlarla
ölçülmüş bug-fix karşılaştırması diye sunulmaz. Değişmeyen aile-planı ve Türkçe
kategori sorularındaki hatalar ayrıca doğrudan regresyonlarla kanıtlandı.

Bir ilk yerel koşu sunucu başlamadan sorguları gönderdi; ConnectError sonuçları
ürün hatası sayılmadı, koşu kabul edilmedi. Runner'a preflight eklendi ve aynı
çalışan aday sunucuda senaryolar yeniden çalıştırıldı.

Son aday raporunun zamanı 2026-11-07 19:43 UTC; Ticketmaster snapshot'ında
704, Biletinial snapshot'ında 3.391 kabul edilen kaynak kaydı vardı.
Seçilen-seans workflow'u search → detail(performance_id) → plan zincirinde
aynı başlangıç saatini ve doğrulanmış kimliği koruyan tek seçenek döndürdü.
Öğrenci/Kadıköy/300 TL, Sıla/Sila konser ve kasıtlı bulunmayan başlık
soruları boş döndü; bunlar pozitif etkinlik bulma başarısı sayılmadı.

## Korunan sınırlar

Gözlenen minimum fiyat son ödeme tutarı değildir; öğrenci/indirim hakkı ve
hizmet bedeli ayrıca kontrol edilmelidir. Kaynakta yaş belirtilmemişse uygunluk
uydurulmaz. Yayımlanmış süreyle türetilen bitişin end_source alanı ayrı gösterilir;
bu gerçek gecikmesiz bitiş garantisi değildir. Kuş uçuşu yakınlık yürüyüş/feribot
süresi değildir. Örneğin ada gezisinin kaynak mekânı kalkış iskelesi olabilir;
etkinlik adından hedef adanın koordinatı uydurulmaz.

Sıla/Sila sorgusunda ilgili hafta için konser bulunmaması normaldir. İlk
ölçümde category verilmeden yapılan prefix aramasının Silahşör adlı tiyatroyla
eşleşmesi sanatçı kimliği kanıtı değildi; query_match ve doğru kategoriyle
arama bu ayrımı açıklar. Şehirde hiç etkinlik olmadığı sonucu çıkarılmaz.

## Test ve yayın kaydı

2026-11-07, production `0.4.0`, Railway deployment
`3a70f0b2-1a48-4000-a253-4704b4bdcdf4` (`SUCCESS`). MCP initialize sürümü
0.4.0 ve tools/list 21 araç doğrulandı. Yeni arama/plan parametreleri gerçek
inputSchema içinde görüldü. `/healthz` ve `/readyz` 200; WAL, schema_version=3.

- Tam regresyon: 1.632 toplandı, 1.567 geçti, 65 dış kaynak testi atlandı;
  0 hata/başarısızlık (`events-persona-full-regression.xml`).
- Son saat çeşitliliği ve argüman kontrollerinden sonra etkinlik grubu:
  54 geçti (`events-persona-final-regressions.xml`).
- Son prompt/manifest ile etkinlik + registry grubu: 66 geçti
  (`events-persona-publish-regressions.xml`).
- Değişen/eklenen dosyalarda Ticketmaster anahtarı bulunmadı;
  secret değeri belgelerde veya fixture'larda tutulmaz. `git diff --check` temiz.

JUnit dosyaları ve canlı raporlar ignore edilen `.data/` altındadır. Tam suite,
son iki küçük değişiklikten önce; hedefli son koşu bu değişiklikleri kapsar.

### Production persona sonucu

2026-11-07 19:45 UTC'de başlayan yayın sonrası koşu: **34 senaryo, 0
semantik/protokol hatası**. Ticketmaster son başarılı snapshot'ı 19:44:51 UTC
(699 kabul edilen kayıt), Biletinial 19:45:20 UTC (3.390 kayıt).
Seçilen-seans zinciri `matched` ve bir seçenekle aynı 2026-11-08 11:00 +03:00
başlangıcını korudu. Yeni kontrol parametreleri gerçek production araçlarına
gönderildi; bunlar yalnız yerel Python fonksiyon testleri değildir.

| Yayın sonrası senaryo | Gözlem |
|---|---|
| Aile gündüz araması | 4 family sonucu; 4 gözlenen fiyat |
| Aile planı | Üç seçenek, yalnız family, ikişer durak; bitişlerinin tümü henüz bilinmiyordu |
| Ücretsiz arama | Gözlenen fiyatı 0 olan üç sonuç |
| 5 yaş filtresi | 10 sonuç; yayımlanmış uyumlu yaş koşulu, açık tükenmişlik yok |
| 1000 TL bilinen fiyat filtresi | 10 sonuç; tamamı gözlenen fiyatlı ve sınır içinde |
| 5 yaş + 18.00 kesin bitiş | Üç tek duraklı family seçeneği; bitiş koşulu doğrulandı |
| Minimum 90 dakika ara | Üçer duraklı üç seçenek; aralar korundu |
| Tükenmişlik opt-in | İlk 10 içinde beş açık sold_out kaydı; varsayılan sorularda yok |
| Seçilen tek seans | Aynı kimlik/saatle bir plan seçeneği |

Üretim indeksi yeni deploy nedeniyle soğuk başladı. Listeler hazır olsa da
arka planın seri detayları henüz tamamlanmamıştı. Bu nedenle yerel, daha çok
detayı doğrulanmış adayın sayıları üretimle aynı değildir. Karma tiyatro/konser
sorusu üretimde yalnız tek duraklı tiyatro seçenekleri döndürdü; bu koşu iki
türü birlikte içeren planın üretimde bulunduğu kanıtı değildir. Bilinmeyen
bitişler çok duraklı plan sayısını, henüz doğrulanmamış mekân/yaş bilgileri
ilgili filtrelerin kapsamını azaltabilir. Bu sınırlar kaynak/detail kapsamıyla
birlikte yorumlanmalıdır; tüm şehir veya tüm kaynak detayları hazır denmez.

Öğrenci/Kadıköy/300 TL, Moda mekânı, Moda title-or-venue, Sıla/Sila konser ve
kasıtlı bulunmayan başlık soruları boş döndü. Semantik kontrolün geçmesi, bu
sorularda etkinlik bulunduğu anlamına gelmez. Her sorguda azami üç detay
yenileme ve host başına 1 istek/s sınırı korunur; daha geniş doğrulama arka
planda ilerler. Doğal dil yönlendirmesi ve gerçek yolculuk yetişilebilirliği
bu çalışmanın ölçtüğü başarılar değildir.

## ChatGPT yayımlanmış eklenti kontrolü

2026-11-07 19:57 UTC: ChatGPT'de bağlı İstanbul MCP eklentisinin health aracı
gerçek çağrıyla `ready=true`, WAL ve schema_version=3 döndürdü. Ancak bu
oturumda eklentinin sağladığı araçlar arasında `istanbul_events_search`,
`istanbul_event_detail` ve `istanbul_events_plan` bulunmuyordu. Production
endpoint'inin güncel olması, yayımlanmış ChatGPT araç tanımlarının aynı anda
güncellendiğini kanıtlamaz. Ekrandaki eklenti 1.0.0 sürümü de MCP initialize
sürümü 0.4.0 ile aynı sürüm alanı değildir. Ekran görüntüsündeki listelemenin
bağlantı URL'i ve yayın inceleme durumu bu kontrollerde görülemedi.

OpenAI'nin [yayımlanmış MCP metadata bakım rehberine](https://developers.openai.com/plugins/deploy/app-review#ongoing-maintenance)
göre mevcut uyumlu tool sonuçları canlı sunucudan gelir; yeni/değişen araç
tanımları periyodik tarama ve otomatik kontrollerden sonra kullanıcılara açılır.
Custom MCP Refresh işlemiyle yayımlanmış eklentinin continuous review akışı
ayrıdır. Bu oturumda yeni etkinlik araçlarının ChatGPT dağıtımı doğrulanamadı;
dashboard'daki ilgili araç inceleme durumu ayrıca kontrol edilmelidir.

### Git push sonrası kontrol

2026-11-07: uygulama, fixture, test ve doküman değişiklikleri
`5995c42ad4a35b2c67efb39e0d98a897ef63d7da` commit'iyle origin/main'e
pushlandı; uzak dal SHA'sı doğrulandı. Secret taramasında sızıntı yok;
büyük snapshot veya .env commit'e eklenmedi. Sonraki doğrudan production
kontrolü initialize=0.4.0, tools/list=21 ve üç etkinlik aracını doğruladı.
Bu oturumdaki bağlı ChatGPT tanımlarında üç yeni ad hâlâ yoktu.

Yayın paneli için Chrome DevTools bağlantısı denendi; araç, profilin başka bir
çalışan browser tarafından kullanıldığını bildirerek sayfa listesini alamadı.
Başka oturumun tarayıcısı kapatılmadı. Yayın paneli veya inceleme durumu
görülemedi, tarama/yeniden yayın yapılmış sayılmadı. Sonraki işlem, açık ve
erişilebilir geliştirici panelinde mevcut eklentinin araç incelemesini
kontrol etmektir; [işletim adımları](deploy-railway.md#chatgptde-yayımlanmış-eklentiye-yeni-araçların-geçmesi).
