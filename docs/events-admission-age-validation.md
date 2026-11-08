# Giriş aralığı, geçersiz kullanım günü ve ortak yaş

9 Kasım 2026 · 0.8.0.

## Kanıt ve kapsam

0.7.0 canlı sunucuda önce 60 yeni etkinlik sorusu, ardından altı takip çağrısı
çalıştı. Parametre kontrolleri geçti fakat kaynak çapraz kontrolü üç ürün
sorununu gösterdi. Yerel rapor: `docs/qa/events-60-results-2026-11-09.md`;
çağrı özetleri `.data/events-60-2026-11-09/` dizinindedir.

- Frida için kaynak gün içi giriş aralığı ve son giriş/kapanış bilgisi yayımlarken
  MCP 19.00'u scheduled başlangıç ve takvim zamanı yapıyordu.
- Go Kart kaynağının pazar kullanımını hariç tutan açık kuralı detay açıklamasında
  bulunuyordu; ancak 15 Kasım kaydı aramada ve ayrı esnek plan listesinde kalıyordu.
- Aynı üç-duraklı plan 6–9, 4–7 ve 12+ koşullarını birleştirdi. Ortak bir yaş yoktu.
  Katılımcı yaşı verilmemiş olması bu fiziksel uyumsuzluğu ortadan kaldırmaz.

Kontrol edilen kaynaklar: [Frida](https://biletinial.com/tr-tr/etkinlik/frida-kahlonun-gunlukleri-sergisi),
[Go Kart](https://biletinial.com/tr-tr/etkinlik/olimpik-go-kart),
[6–9 atölye](https://biletinial.com/tr-tr/muzik/kopuk-baski-atolyesi-akm),
[4–7 dans](https://biletinial.com/tr-tr/muzik/modern-dans-atolyesi-rockn-roll-yas-grubu-4-7-akm),
[12+ konser](https://biletinial.com/tr-tr/muzik/3-basses-ayca-varlier-konseri).
Giriş/yaş bilgisi başlıktan veya mekân türünden tahmin edilmedi.

## Kaynak giriş aralığı

Ayrıştırıcı, açık katılım/giriş aralığını ve ürünün açıklama bloğunda yayımlanan
ziyaret saatlerini okur. Footer veya diğer ürün metinleri bu kanıtın yerine
geçmez. opens_at, last_entry_at ve varsa closes_at `admission_window` içinde
HH:MM olarak tutulur; saat dilimi Europe/Istanbul'dur. Eksik kapanış null kalır.

Esnek bilette start_at=null ve end_at=null korunur. Son giriş 19.00 ile kapanış
20.00, kullanıcının 19.00'da başlayıp bir saat kalacağı anlamına gelmez.
Ziyaret seçilmeden saatli seçenek veya takvim üretilmez. Normal aramanın saat
filtresi hâlâ gerçek başlangıç ister; esnek aralık bir saat eşleşmesi diye sunulmaz.

## Açık hafta günü istisnası

Kaynağın genel ve olumsuz bilet kuralı, Monday=0..Sunday=6 biçiminde
`excluded_weekdays` alanına çevrilir. Pozitif geçerlilik cümlesi veya yalnız
öğrenci gibi belli bilet türüne ait istisna herkese uygulanmaz. Bu deterministik
ayrıştırıcı tüm doğal dil koşullarını veya tatil istisnalarını çözdüğünü iddia etmez.

Kartta entry_date_restricted, listedeki tarihin bu bilinen kurala takıldığını
belirtir. Arama bunu `excluded_entry_date` ile eler; include_past veya
include_sold_out izin vermek için kullanılamaz. Detay tarih/teklif geçmişini
korur ve kısıtı açıkça gösterir. Seçilmiş planda ret nedeni
entry_date_restricted olur; ayrı flexible_entries içine veya takvime de girmez.
Kural bilet içindir; işletmenin o gün kapalı veya etkinliğin iptal olduğu çıkarılmaz.
Başka rezervasyon, refakat, boy ve uygunluk koşulları ayrıca kaynaktan kontrol edilir.

## Ortak yayımlanmış yaş aralığı

Plan kombinasyonlarının bilinen yaş aralıklarının kesişimi alınır. 6–9 ve 4–7
birlikte yalnız 6–7 aralığını verir; 12+ da eklenince kesişim boş olur ve bu
kombinasyon elenir. 18+ üst sınır uydurmaz, maximum=null kalır.

checks.common_published_age_range kesişimi; age_compatibility ise tüm aralıklar
biliniyorsa published_ranges_compatible, bazıları bilinmiyorsa partially_known,
hiçbiri bilinmiyorsa unknown gösterir. Bilinmeyen bir durak, bilinen iki
uyumsuz koşulu geçerli yapmaz. Ortak kaynak aralığı, kullanıcının gerçek yaşının
veya bilet uygunluğunun doğrulandığı anlamına gelmez; istemci yaş profilini varsaymamalı.

age_incompatible_combinations, değerlendirilen adaylardan yaş nedeniyle
elenen kombinasyonları sayar. Bireysel seans veya şehir toplamı değildir;
zaman/bütçe eleme sayaçlarıyla tek toplam gibi toplanmaz. Mevcut child_age'nin
family türü sözleşmesi korunur; bu sürüm genel katılımcı profili veya grup
üyelerinin ayrı duraklara katılımı için yeni bir parametre eklemez.

## Doğrulama

```bash
pytest tests/test_events_admission_and_age.py
```

İlk altı fixture testi eski kodda başarısız oldu (`.data/events-admission-age-before.xml`).
Pencere anlamı, kapalı hafta günü, detayda inceleme, seçilmiş plan, takvim koruması,
yaş kesişimi, bilinmeyen yaşlar, sınırsız üst yaş ve footer kapsamı sınanır.
Hedefli etkinlik kontrolleri 220/220, protokol/sürüm/uyumluluk kontrolleri 37/37 geçti.
Tam paket: 1.800 test, 1.735 başarılı, 65 atlanan, sıfır hata
(`.data/events-080-full.xml`). Büyük/ham sağlayıcı gövdeleri veya anahtarlar depoya eklenmedi.

Yayımlanmış araç adları ve giriş parametreleri korunur; pyproject/server sürümü
0.8.0'dır. Yeni tablo, migration veya env ayarı yoktur. Yeni alanlar mevcut
payload'lara varsayılanlarla uyumludur. Değişiklikler canlıda hedefli çağrılarla
kontrol edildikten sonra kullanıcı tarafından istenen 100 yeni soru hazırlanıp
tek tek gerçek MCP'ye gönderilir. Kanıt raporu:
`docs/qa/events-100-results-2026-11-09.md`.


## Canlı ilk sorgu düzeltmesi — 0.8.1

0.8.0 dağıtımı sonrası hedefli canlı kontrol, Go Kart isim aramasının soğuk
katalogdaki geçici kaydı detail_checks_attempted=0 ile verdiğini gösterdi.
Kaynak kuralı henüz indirilmediği için pazar filtresi uygulanamıyordu.
Frida giriş aralığı ve ayrı plan kontrolleri aynı koşuda geçti.
İlk beş çağrı `.data/events-080-targeted-live.json` içinde korundu.

0.8.1 isim içeren aramaları da mevcut en fazla üç seri/12 saniyelik detay
doğrulamasına dahil eder. Genel keşif tüm kataloğu indirmez. Detay başarısızsa
geçici bilgi ve kapsam uyarıları korunur; bilinmeyen koşul geçerli diye onaylanmaz.
Soğuk katalog regresyonu eski kodda başarısız oldu
(`.data/events-081-before.xml`). İlk 100 soru bu canlı düzeltmeden sonra çağrılır;
soru listesi daha önce hazırlanmıştır.

0.8.1 tam paket: 1.801 test, 1.736 başarılı, 65 atlanan, sıfır hata
(`.data/events-081-full.xml`). Önceki hedefli koşudaki changelog başlık
biçimi düzeltilip sürüm metadata kontrolü tekrar geçti; ürün testleri aynı
koşuda geçti. Canlı kontrol ve 100 soru sonuçları yerel QA raporuna yazılır.
