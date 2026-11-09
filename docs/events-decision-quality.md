# Etkinlik kararı için konum, fiyat, kaynak koşulu ve plan — 0.9.2

9 Kasım 2026. [Kabul koşulları](events-decision-quality-plan.md).

## Konum ve boş sonuç

Katalogdaki saloonName, catalogue_venue_hint olarak yalnız detay kontrolünü
önceliklendirir. Çok salonlu üründe seans mekânı yerine geçmez; doğru sonuç
ancak detayın gerçek mekânı istenen konumla eşleşirse döner. query_scope=all
ipucuyla bir adayı bulabilir, ancak doğrulanmamış metin eşleşmesi sonuçta elenir.
En fazla üç seri/12 saniye detay bütçesi korunur.

Aynı doğrulanmış isimde mekân için tek ve çelişkisiz adres/ilçe/koordinat varsa
eksik alan başka doğrulanmış gözlemden tamamlanabilir. Kullanılamayan kaynak,
çelişkili adres/ilçe/koordinat veya farklı konumdan veri taşınmaz. field_evidence
köken URL'ini ve gözlem tarihini belirtir; koordinattan ilçe tahmini yapılmaz.

excluded_unknown_location ile excluded_outside_location ayrıdır. Biri bilinmeyen
mekân/ilçe/koordinat, diğeri bilinen eşleşmeme/mesafe içindir. Toplamları eski
excluded_location alanını korur. Konum sorguları sınırlı tarih/metin adayları
üzerinden sayıldığından koordinatı bilinmeyen kayıtlar sessiz RTree dışlamasında
kaybolmaz. SQLite RTree indeksi ve doğrudan repository bbox sorgusu korunur.

result_info.empty_reasons ile coverage, kaynak/yer/fiyat/yaş/saat nedenlerini
belirtir. Sayımlar sıralı filtre aşamalarına aittir; şehir toplamı veya bağımsız
nedenlerin toplamı değildir. No match, İstanbul'da etkinlik yok anlamına gelmez.

## Bilet profili ve grup hesabı

Varsayılan minimum_observed_try eski kaynak minimumunu korur; genel giriş,
kişi başı tutar veya grup toplamı değildir. price.unit biletin açık etiketinden
çıkarılabilen kişi sayısı/profilini gösterir; Standard veya 1. Kategori gibi
birim kanıtı taşımayan etiketler normal kişi bileti diye yorumlanmaz.

Arama, detay ve planlamada yeni girişler: party_size=1..50 ve ticket_profile; veya party haritası.
Profiller: general (kısıtsız normal etiket), adult, student, child, senior;
any koşullu gözlemleri araştırmak içindir. Belirli profildeki kullanıcı normal
bilet alabilir; yetişkin bileti çocuk profilinde kullanılamaz. Karma profil ve
çift kişilik paketler birlikte optimize edilir; eksik/fazla kişiyle paket
kullanımına kaynak kanıtı olmadan izin varsayılmaz; aynı genel paket iki ayrı
profil için iki kez alınmış sayılmaz. Uygunluğu açıklanmayan aile/promo paketi
veya belirsiz kişi birimi tahmin edilmez. İndirim hakkı ayrıca doğrulanmalıdır.

Örnek: 6 kişi için öğrenci 50 / Tam 400 / çift kişilik 600 gözlenirse üç çift
paketi 1.800 TL olur; 50×6 normal grup toplamı sayılmaz. Karma 1 yetişkin/1
çocuk için party={"adult":1,"child":1} kullanılır; yaş uygunluğu ayrıca kontrol
edilir. Para hesabı Decimal ile yapılır, sonra JSON sayısına çevrilir.

price_quote bilet adetleri, tam kapsanan giriş sayısı, gözlenen bilet ara
toplamı ve profil dağılımını verir. max_price_try bu bağlamda tüm grubun tek
etkinlikteki tutarı; planda tüm durakların grup tutarıdır. Hizmet bedeli
bilinmiyorsa ayrıca görünür. budget_includes_fees=true ve katı fiyat araması,
ücret dahil tutarı bilinmeyen kaydı doğrulanmış bütçe diye kabul etmez.

Yalnız açık genel hizmet-bedeli-dahil kuralı fees_included alanını doldurur;
öğrenciye/kanala özel ifade tüm biletlere uygulanmaz. checkout_total_verified,
quantity_available_verified ve adjacent_seats_verified false kalır. Bu servis
satın alma, rezervasyon veya canlı sepet/koltuk API'si değildir. Fee-inclusive
gözlem dahi güncel satın alma garantisi sayılmaz.

## Kaynak katılım koşulları

participation_conditions yalnız ilgili açıklama, event-rules-v2__content ve
bilgi tablosundan sınırlı ifadeler taşır. Dil/altyazı, erişilebilirlik,
rezervasyon, iade/değişim, bilet zorunluluğu, malzeme, sertifika, fotoğraf,
oturma, duyusal bilgi ve ücret konuları ayrılır. Footer ve başka ürün metni
kanıt sayılmaz; uzun bir cümle negatif/istisna kaybolacak şekilde kesilmez.

Her ifade kaynak URL'i ve source_section ile published_statement_only olarak
saklanır. Bilgi bulunmayan başlık unverified_topics içindedir; gösterilmeyen
veya süresi geçmiş koşul olumlu onay değildir. source_observed_at ve expired
statüsü zaman kapsamını belirtir. Arama en fazla 12, detay en fazla 60 ifade
verir; truncated alanı korunur. Kısa description'ın kesilip kesilmediği ayrıca
belirtilir. Kaynak ifadesi hukuki hakların veya kişisel uygunluğun kararı değildir;
tek giriş/rampa bilgisi bütün mekânın erişilebilirliği diye genellenmez.

## Tam ve eksik plan

min_events=1..max_events zorunlu minimum; max_events üst sınırdır. Tam iki durak
isteği min_events=2,max_events=2 ile verilir. interests izin verilen türlerdir;
required_categories ise her birinin planda bulunmasını ister. Zorunlu türler
20-aday havuzunun seçiminde de gözetilir; şehir geneli optimum iddiası yoktur.

options, tüm durak/tür koşullarını sağlayan gözlenen fiyatlı seçeneklerdir.
unverified_budget tam durak/tür sayısını karşılayıp bütçesi doğrulanmayan
seçeneklerdir. partial_options eksik durak/türü fulfillment içinde açıklar ve
takvim üretmez. Tek durak iki durak diye, yalnız atölye hem atölye hem sergi
diye sunulmaz. fulfillment.status ve reason_codes eksik/fiyat/zaman/keşif
nedenlerini açıklar; discovery_diagnostics ve combination_diagnostics kapsamı
korur. total_price_scope toplamın hangi gözlem türüne ait olduğunu belirtir.

## Doğrulama ve tekrar koşusu

Fixture regresyonları `tests/test_events_decision_quality.py`; başlangıçtaki
entegrasyon başarısızlıkları `.data/events-decision-quality/` içinde korunur.
README'deki test komutuyla hedefli/tam paket, ardından canlı MCP hedefli ve
100 insan sorusu tekrar koşusu yapılır. Kaynak ya da koşul bilinmiyorsa raporda
bilinmeyen kalır; böyle bir sonuç kullanıcı ihtiyacı çözüldü sayılmaz.

## Canlı aktarım düzeltmesi — 0.9.1

0.9.0 hedefli canlı koşuda grup fiyatı ve eksik plan kontrolleri geçti; yedinci
çağrı, empty_reasons/coverage alanlarının ortak ResultInfo modeli tarafından
MCP sınırında kaldırıldığını gösterdi. Bu koşu başarısızlık olarak saklanır.
0.9.1 alanları sınırlı tipli modele ekler ve gerçek Streamable HTTP regresyonuyla
korur. Salt servis dict kontrolü yayın kanıtı yerine kullanılmaz.

## Bilinen fiyat alt sınırı — 0.9.2

0.9.1'in 100 soruluk tekrarında H012, 600 TL sınırına rağmen en düşük teklifi
1.450 TL olan bir kaydı, kişi birimi belirsiz olduğundan bilinmeyen grup tutarı
olarak tutabildi. Ham minimum fiyat bilgisi grup birimi bilinmese de en az bir
bilet satın almanın gözlenen alt sınırıdır. 0.9.2 budget_lower_bound_try ve
price_quote.observed_lower_bound_try ile bu kanıtı korur. Bilinen alt sınır
bütçeden büyükse include_unknown_prices=true bunu gizlemez; planda alt sınırlar
toplanır, free_only pozitif alt sınırı ücretsiz saymaz. Bu yalnız gözlenen
tekliflere aittir; gözlenmeyen kampanya, kişisel indirim veya canlı sepet iddiası
yapılmaz. İlk hatalı koşu ayrı saklanır; başarısız sonuç silinmez.

## Tamamlanan yayın ve 100 soru doğrulaması

0.9.2 (`43031c0`) tam paketinde 1.783 test geçti, 65 test atlandı, başarısız
veya hata yok; 43 karar-kalitesi regresyonu dahildir. Aynı commit'in
[CI kontrolleri](https://github.com/Batu1-1an/istanbulmcp/actions/runs/42578328171)
geçti. Railway üretim dağıtımı başarılı; 21 araç, uzak MCP sürümü ve iki
checked/stale-olmayan kaynak kontrol edildi. 11 hedefli gerçek MCP çağrısında
grup hesabı/bütçe, kısmi plan, konum açıklaması, kaynak koşulu ve H012 alt sınırı
geçti. İlk ek fiyat kontrolündeki yanlış aynı-adlı kaynak seçimi test hazırlığı
hatası olarak ayrı korunur; fiyatı bilinmeyen Ticketmaster kaydına fiyat atanmamıştır.

Önceden hazırlanan 100 soru değişmeden 145 gerçek senaryo araç çağrısı + 1
hazırlık kontrolüyle tekrarlandı: 19 USEFUL, 25 PARTIAL, 5 ANSWERED_NEGATIVE,
51 NO_MATCH. Araç hatası/sözleşme ihlali yok; eşleşmesiz ve eksik ihtiyaçlar
başarıya çevrilmedi. Bu 100 ayrı model sohbeti veya katılımcı çalışması değildir;
natürel soruların filtrelere aktarımı elle yapıldı, cevaplar gerçek MCP
kayıtlarından biçimlendirildi. Kaynak ve önbellek değişimi nedeniyle eski
koşuya göre sayı farkı yalnız koda atfedilemez.

Yerel ayrıntı: `docs/qa/events-decision-quality-2026-11-09.md`. Kullanıcının
ignore tercihine uygun olarak QA/ham koşu dosyaları izlenmez; izlenen bu belge ve
[kabul kanıtı](events-decision-quality-plan.md) sonuçları özetler. Eksik konum,
bilet birimi, ücret, erişilebilirlik/duyusal koşul ve canlı stok hâlâ kaynak
sınırıdır; yayımlanmış bir kural kişisel uygunluk veya iade garantisi sayılmaz.
Konu etiketleri ilgili kaynak ifadesini buldurur; fotoğraf kredisi/pazarlama
metni çekim izni kanıtı değildir.
