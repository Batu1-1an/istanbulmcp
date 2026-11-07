# Etkinlik sistemi: farklı kullanıcı sorularıyla iyileştirme

## Amaç ve yöntem

Öğrenci, ebeveyn, turist, sanatçı takipçisi, yakınında etkinlik arayan ve
günlük plan isteyen kullanıcıların farklı soruları canlı MCP üzerinde sınanır.
Sorular `tests/fixtures/events/persona_queries.json` içinde açık tool argümanlarına
eşlenir. Bu, bir LLM'nin doğal dil yönlendirmesinin testi değildir; kaynak ve
tool sonuçlarının kullanıcının ifade ettiği koşullara uyup uymadığı sınanır.
Ham cevaplar ve secret'lar rapora yazılmaz. Yerel makine raporları `.data/`
içindedir; kalıcı bulgular docs içindeki doğrulama raporuna özetlenir.

## Başlangıç ölçümü (0.3.1)

26 canlı senaryoda iki açık semantik hata bulundu:

1. Yalnız `family` isteyen plana `theatre` etkinlikleri girdi.
2. Türkçe `tiyatro` kategori değeri validation_error döndürdü.

Ek kullanıcı deneyimi sorunları:

- Aile araması sıfır sonuç verirken genel tiyatro sonuçlarında çocuk oyunları vardı.
  Biletinial detayındaki ayrı Etkinlik Türü / Yaş Sınırı / Süre bilgileri okunmuyordu.
- Bütçeli ilk sonuçlarda güncel fiyat yoktu; eski detayların yenilenmesi kullanıcının
  sorgusuna bağlı değildi. Arka plan sırası uzak/geçmiş/başarısız serilerde oyalanabiliyordu.
- Başlık niyetli metin sorgusu yalnız mekân adından da eşleşebiliyordu.
- İlk 50/20 aday sınırı sonraki saatleri ve istenen türleri dışarıda bırakabiliyordu.
- performance_id ile seçim tüm seri seanslarına açılıyordu; seçilen saatin korunması
  ve kesin bitiş koşulu için açık kontroller gerekiyordu.

## Uygulama ve kabul koşulları

- Türkçe kategori eşanlamlılarını normalize et; ilgi türleri dışından plana fallback ekleme.
- Aile türü, yaş aralığı ve süreyi yalnız sayfanın ayrı kaynak fact alanlarından çıkar.
  Adından/masal karakterinden çocuk uygunluğu tahmin etme.
- child_age ile yalnız yayımlanmış uyumlu yaş aralığını kabul et.
- Bütçe/aile/ücretsiz sorularında en fazla üç ilgili seri detayını, toplam 12 saniye
  bütçe içinde yenile. Bilinmeyen fiyatlar istenirse açıkça dışlanabilsin.
- Başlık sorgusunu varsayılan title alanına sınırla; venue dahil arama opt-in olsun.
- Seri seçimi ile tek seans seçimini ayır. Tam seans kaybolur/belirsizleşirse yeni seçim iste.
- require_known_end ile bilinmeyen bitişi reddet; programda yayımlanmış süreden türetilen
  bitişin kaynağını ayrıca göster.
- Planlama tüm bounded indeks adaylarını tür filtresinden geçirip saat/seri çeşitliliğiyle
  20 adaya indirgesin; ilk sayfa bias'ı olmasın.
- Başarısız detayların retry zamanını tut; geçmiş kayıtlar arka plan işini tüketmesin.
  SQLite schema ilk kurulumunu eşzamanlı okuyucular için güvenli hale getir.
- Her bulguya ağsız regression testi, yerel gerçek kaynak testi ve yayın sonrası
  aynı persona sorgularıyla doğrulama ekle. Dokümanları ve sürüm manifestlerini güncelle.

## Teknik kaynak

SQLite FTS5 title column filter ve prefix sorgu davranışı Context7 üzerinden
resmî SQLite dokümanıyla kontrol edildi: https://sqlite.org/fts5.html#fts5_column_filters
Biletinial'ın canlı çocuk oyunu detayında ayrı Etkinlik Türü=Çocuk Oyunu,
Yaş Sınırı=3-10, Süre=50 dakika alanları görüldü. GetKidsEvents ucu 500 verdi;
çalışmayan bir uç kaynak olarak eklenmedi.

## Uygulama sonucu

Kontroller, kaynak fact ayrıştırması, fiyat/tükenmişlik kontrolleri, seans
kimliğinin korunması ve saatlere yayılan aday seçimi uygulandı. 0.4.0 production
deployment'ı `3a70f0b2-1a48-4000-a253-4704b4bdcdf4` başarılı. Tam regresyon
1.567 geçti/65 atlandı; son etkinlik+registry grubu 66 geçti. Yerel gerçek
kaynakta 34 senaryo 0 hata verdi. Bulgular, ölçüm sınırları, tekrar komutları
ve yayın sonrası sonuçlar [doğrulama raporunda](../events-persona-validation.md).
Yayın sonrası production koşusu da 34 senaryo/0 hata verdi. Soğuk detay
indeksinin sınırladığı boş/tek duraklı sonuçlar raporda ayrıca kayıtlıdır.
