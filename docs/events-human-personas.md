# İnsanların günlük etkinlik ihtiyaçları — 100 soruluk tur

9 Kasım 2026. Bu çalışma kurmaca 20 kişinin beşer isteğini gerçek üretim MCP
üzerinde yürütür. Katılımcı araştırması veya 100 gerçek kişinin görüşmesi değildir.
Önce doğal dilde soru listesi kaydedilir; ardından soruların koşulları araç
parametrelerine çevrilir. Kullanıcıya verilebilecek yanıtlar gerçek yapılandırılmış
çıktılardan oluşturulur; ayrı modelin 100 bağımsız sohbetindeki routing kalitesi
ölçülmez. Önceki 100 sözleşme testindeki PASS, kullanıcının işinin çözüldüğü
anlamına gelmediği için bu tur ayrı sonuç sınıfları kullanır.

## Karar ihtiyacı

Öğrenci, ebeveyn, çalışan, turist, çift, yaşlı izleyici, engelli kullanıcı, arkadaş
grubu, sergi ziyaretçisi ve atölye katılımcısı gibi farklı ihtiyaçlar bulunur.
Soru listesi `docs/qa/events-human-100-questions-2026-11-09.md`; sonuç raporu
`docs/qa/events-human-100-results-2026-11-09.md` konumundadır. Yerel QA dosyaları
kullanıcının mevcut Git ignore tercihine tabidir.

- USEFUL: kaynaktan gelen seçenek, kontrol edilen çekirdek keşif ihtiyacını karşılar.
- PARTIAL: seçenek vardır; bütçe türü, grup stoku, erişilebilirlik, dil veya başka
  istenen özellik tam doğrulanamaz. İstenen iki durak yerine bir durak da bu sınıftır.
- ANSWERED_NEGATIVE: yayımlanan yaş/gün koşuluyla kesin bir olumsuz karar açıklanır;
  yalnızca boş katalog sonucu değildir.
- NO_MATCH: koşullara uyan doğrulanabilir kayıt bulunamadı; şehirde yok anlamına gelmez.
- TOOL_ERROR / CONTRACT_FAILURE: altyapı/çağrı veya sözleşme sorunu ayrı kaydedilir.

Bu sınıflar otomatik müşteri memnuniyet puanı değildir. Fiyat türü, ücretlerin
kapsamı, yaş, süre, bitiş bilgisi ve bilet bağlantıları yanında çözülemeyen ihtiyaç
kullanıcıya açıkça söylenir. Başarısız çağrı veya ilk koşu sonradan silinmez.

## İlk turda bulunan bağlam açığı ve 0.8.2

100 soruluk ilk turdaki yetişkin arkadaş grubunun H050 planı 4–7 ve 4–6 yaş
atölyelerini ilk seçenekler olarak döndürdü. H005/H035/H080'de de benzer çocuk
üst yaş aralıkları vardı. Genel plan aracı katılımcı bağlamını almadığından
mevcut davranış çocukları da kapsıyordu; yetişkin bağlamı aday havuzu oluşmadan
ifade edilemiyordu. Sunum katmanında bu kartları sonradan atmak, sınırlı
20-aday/5-seçenek havuzunda yetişkin alternatiflerin kaybolmasını engellemiyor.

0.8.2, arama ve planlamaya isteğe bağlı `exclude_child_only` ekler. Yalnızca
kaynakta açık bir üst yaş sınırı olup 18 altında kalan aralıkları eler.
6–9/7–17 elenir; 6+/18+ veya bilinmeyen yaş için üst sınır uydurulmaz.
Default false aile keşfini korur. Üst sınırı bilinmeyen kayıtlar yetişkine kesin
uygun diye işaretlenmez; kullanıcı sayısal yaşı tahmin edilmez.

Eleme sonuç/20-plan adayı sınırından önce çalışır. Arama sayacı
excluded_child_only, seçilmiş planda ret nedeni child_only_age_range olur.
Yetişkin senaryolarında istemci bu bayrağı kullanır; çocukla katılımda bağlam
korunur. API ve prompt yönergeleri güncellendi; yayımlanan araç adları değişmedi.

Fixture regresyonları: çocuk/ergen üst sınırını eleme, minimum-only ve bilinmeyen
yaşı koruma, varsayılan davranış, seçili seansı açıklayarak reddetme ve 25 çocuk
adayının yetişkin adayını plan bütçesinden düşürmemesi. Yeni özelliği kullanan
üç test eski kodda başarısız oldu (`.data/events-adult-before.xml`); varsayılan
keşif testi zaten geçiyordu. Komut:

```bash
pytest tests/test_events_adult_discovery.py
```

## İstemci koşusu ve kalan kapsam

İlk istemci hızlı ardışık çok adımlı çağrılarda 37 HTTPStatusError kaydetti.
Bu koşu `.data/events-human-100-2026-11-09/initial-results.json` içinde tutulur;
başarı olarak sayılmaz. İlk sürüm exception status/header ayrıntısını saklamadığı
için bu 37 hatanın her birine geriye dönük 429 etiketi eklenmez. Yerel sunucu
hız sınırı 60 token/1 token saniye varsayılanını kullanır; istemci yeniden
çalıştırmada en az 1,1 saniye aralık bırakır, HTTP durumunu kaydeder ve varsa
Retry-After'a uyar. Üretim koruması kapatılmaz, anahtar/IP değiştirilerek aşılmaz.

Erişilebilir giriş/tuvalet, dil/altyazı, fotoğraf izni, malzeme/sertifika, yan yana
koltuk, sepet fiyatı, iade ve ulaşım gibi alanlar veri yokken onaylanmaz. Bu
verilerin eklenmesi, yalnız bool filtre ekleyerek yapılmış sayılmaz. Gerçek
kaynak/işletmeci kanıtı gereken geliştirme alanları raporda ayrı izlenir.

## Yerel doğrulama

Hedefli paket: 42 test başarılı. Tam paket: 1.805 test, 1.740 başarılı,
65 atlanan, sıfır hata (`.data/events-082-full.xml`). Anahtarlar veya env
ayarı değiştirilmedi. pyproject.toml ve server.json sürümü birlikte 0.8.2.
Canlı yeniden koşu, CI ve yayın kanıtı yerel QA sonuç raporuna eklenir.
