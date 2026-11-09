# Etkinlik karar kalitesi — dört açığın tamamlanması

9 Kasım 2026 · Kullanıcı hedefi: “fix them all”. Önceki insan senaryolarının
bulguları kapsamı belirler; bu belge tamamlanma kanıtı olmadan işaretlenmez.

## Kabul koşulları

- [x] Konum: kaynak katalog mekân ipucu yalnız detay adayını önceliklendirir;
  seansın doğrulanmış mekânı yerine geçmez. İlçe/mekân/koordinatı bilinmeyen ile
  gerçek alan dışı kayıtlar ayrı sayılır. Boş sonuç nedeni ve kapsam açık döner.
  Aynı doğrulanmış mekândan güvenilir eksik alan tamamlama varsa kökeni belirtilir;
  farklı adres/koordinat ve çelişkilerde tahmin yapılmaz.
- [x] Fiyat: normal/öğrenci/çocuk/paket türleri ve fiyatın kapsadığı kişi sayısı
  ayrılır. Grup için seçilen bilet adetleri, gözlenen ara toplam, bilinmeyen ücret
  ve canlı stok ayrımı görünür. Koşullu minimum normal kişi fiyatı sayılmaz.
  Genel/belirtilmiş bilet profili ve grup bütçesi arama/planlamaya taşınabilir.
- [x] Katılım: sağlayıcının yalnız ilgili açıklama/kurallar bölümündeki dil,
  erişilebilirlik, rezervasyon, iade, malzeme, sertifika, fotoğraf, oturma ve
  duyusal koşul ifadeleri kaynak ve kapsamıyla döner. Eksik bilgi bilinmeyen
  kalır; footer/tavsiye/diğer ürün veya pazarlama cümlesi olumlu onay sayılmaz.
- [x] Plan: minimum durak ve zorunlu etkinlik türleri ifade edilir. Eksik plan
  tam seçenek listesine karışmaz; ayrı kısmi seçenek, eksik koşullar ve tamamlanma
  durumu açık döner. Mevcut yayımlanmış araçlar çağrılabilir ve varsayılanları
  uyumlu kalır.
- [x] Her dört alan için fixture regresyonları ve uygun mevcut kontroller geçer.
- [x] Sürüm/araç şeması/response contract/prompt/README/changelog belgelenir.
- [ ] Tam paket, CI ve yayın doğrulaması; gerçek MCP ile hedefli ve insan
  sorularının tekrar çağrıları yapılır. Başarısız ilk koşular saklanır; veri
  bulunamaması veya bilinmeyen kaynak bilgisi başarı diye yazılmaz.

## Kaynak incelemesi

Mevcut kod, `docs/qa/events-human-100-results-2026-11-09.md` ve gerçek MCP
sonuçları incelendi. Biletinial'ın 9 Kasım HTTP yanıtı katalogda saloonName ve
saloonCount; detayda event-card-v2__description ile event-rules-v2__content
bloklarını gösterdi. Katalog mekânı çok salonlu ürünlerde seans gerçeği değildir.
Bi Şaka/Go Kart birincil sayfaları da açıldı. Web okuyucudaki Niloya sonucu eski
önbellek olduğundan güncel seans/yaş kanıtı sayılmaz. Güncel entegrasyon için
sınırlı HTTP kaynak kontrolü ve fixture kullanılacak; yeni SDK davranışı veya
kaynakta olmayan canlı sepet/koltuk API'si varsayılmayacak.

## Sınırlar

Salt okunur kapsam korunur: bilet satın alınmaz veya ayrılmaz. Kaynak koşulları
hukuki hak veya işletmecinin fiili uygunluk garantisi değildir. Bilinmeyen
bilgiyi açık sunmak, veri varmış gibi yeni alanı doldurmak değildir. .env,
anahtarlar ve büyük ham sağlayıcı gövdeleri depoya eklenmez. Kullanıcının
.gitignore değişikliği korunur.

## Yerel uygulama kanıtı

38 karar-kalitesi regresyonu ve mevcut etkinlik/protokol/metadata/uyumluluk
kontrolleriyle 266 test geçti (`release-checks.xml`). Önceki tam paket de geçti;
paket/fiyat uç durumlarının son düzeltmesinden sonraki tam doğrulama exact
commit üzerinde CI ile tamamlanacak. Canlı yayın/100 soru kanıtı elde edilmeden
son kabul maddesi tamamlanmış sayılmaz.

## 0.9.0 canlı kontrolü ve 0.9.1

İlk yedi canlı çağrıda fiyat ve kısmi plan doğrulandı; arama diags alanlarının
ortak ResultInfo modelinde tanımlı olmadığı için MCP sınırında kaybolduğu
görüldü. Başarısız koşu live-targeted-090-failed.json/log olarak saklandı.
0.9.1 alanları ortak tipe ekler; servis→envelope ve Streamable HTTP testleri
bu aktarımı ayrıca korur. Hedefli 88 kontrol geçti; tüm paket ve canlı/100 soru
onayı son kabul maddesine tabidir.

## 0.9.1 insan soruları ve 0.9.2

100 soru tamamlandı; H012'de tek ihlal bulundu: toplam birimi belirsiz teklifin
gözlenen minimumu 1.450 TL iken 600 TL bütçede bilinmeyen tutar olarak tutuldu.
Koşu human-091-results-failed.json içinde korunur. 0.9.2 gözlenen alt sınırı
arama/plan/ücretsiz filtrede korur; arama ve seçilmiş plan regresyonları önce
başarısız oldu. Yeni canlı ve yüz soru onayı beklenmeden son madde tamamlanmaz.
