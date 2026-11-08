# Etkinlik tekrar testi: müzikal ve yenileme düzeltmeleri

Tarih: 2026-11-08. İlk bulgular yerel
`docs/qa/events-my-100-results-2026-11-08.md` raporundadır.

## Doğrulanan kategori hatası

Konser sorgusunda Hayal Adası Müzikali, category=concert ve
category_source=provider ile döndü. Kaynağın ayrı Etkinlik Türü alanı
“Müzikal, İnteraktif Oyun, Dans”, yaş sınırı 2+ idi:
[kaynak sayfası](https://biletinial.com/tr-tr/tiyatro/hayal-adasi-muzikali).

category_for içindeki music/muzik alt dize eşleşmesi musical/müzikal
kelimesini de konser yapıyordu. 0.5.1, bu yayımlanmış türü theatre'a eşler;
açık çocuk/aile ve festival türlerinin mevcut önceliğini korur. Yalnız 2+
yaş sınırı aile türü üretmez. Türkçe/İngilizce müzikal kategori eşanlamlıları
theatre'a yönelir.

Kaynak türünü içeren fixture regresyonu, Türkçe/İngilizce tür örnekleri ve
normal Music/Müzik konser eşleşmesinin korunması test edilir. Bu kontrol
yalnız dönen kategori etiketini istektekiyle karşılaştıran 100'lü koşucunun
yakalayamadığı hatayı ayrıca sınar.

## Doğrulanan yenileme gecikmesi mekanizması

Tekrar testinde Biletinial snapshot'ı stale idi. Örnek 500 production logu
10:51:34–10:56:07 UTC aralığını kapsadı; bu aralıkta Event source refresh
failed kaydı görülmedi. Bu örnek, önceki tüm kaynak/işletim olaylarını
açıklamaz ve stale gözleminin tek nedenini kanıtlamaz.

Kodda bağımsız bir hata yeniden üretildi: süreç önbelleği boşaldığında veya süresi dolduğunda
SQLite'taki henüz TTL'i dolmamış snapshot tekrar kullanılıyor ve ona yeni
tam TTL veriliyordu. Örneğin 60 dakikalık snapshot'ın son beş saniyesinde
yeniden kullanım, bir 60 dakika daha yenilemeyi geciktirebiliyordu.

0.5.1 yeniden kullanılan kayıt için SourceLoadResult.max_cache_age_seconds
alanına yalnız kalan TTL'i verir. Kontrol edilen yerel sözleşme
`app/core/source_cache.py` içindedir; ortak cache algoritması değiştirilmez.
Sahte saatli test, beş saniye kalan kaydın en fazla beş saniye tutulduğunu
ve altıncı saniyede connector'ın gerçekten tekrar çağrıldığını kanıtlar.
Kaynak isteği başarısız olursa mevcut bounded stale fallback korunur.

## Doğrulama ve kullanım

```bash
pytest tests/test_events_qa_findings.py tests/test_events.py tests/test_event_personas.py tests/test_registry_metadata.py tests/test_tool_compatibility.py tests/test_source_cache.py
```

Yeni env veya migration gerekmez. Üç yayımlanmış etkinlik aracının isimleri
korunur. Sürüm pyproject.toml/server.json içinde birlikte 0.5.1'dir.
Spor/festival için boş sonuçlar ve tam kelime/önek arama tercihi bu doğrulanmış
iki kusurla karıştırılmaz; kaynak kapsamı olmayan kayıtlar üretilmez.

Son hedefli koşu: 116 test, 0 hata/başarısızlık/skip; rapor
`.data/events-musical-fix-final.xml`. Secret taraması ve git diff --check temiz.

0.5.1 canlı tekrarında La La La Fontaine Müzikali sayfasındaki ayrı türün
Müzikli Oyun olduğu görüldü. 0.5.2 bu eşdeğer türü de theatre'a yöneltir;
çocuk/aile önceliği korunur. İlgili regresyon örnekleri eklendi. Bu ikinci
kaynak etiketi ilk düzeltmeden sonraki canlı denetimde bulunmuştur.

Son doğrulama: 0.5.2 canlıda, commit 35604d9, deployment
da781fc6-1de6-42e6-8c46-4d8718b3b05f SUCCESS. 118 hedefli test ve GitHub CI
test/conformance/Docker işleri geçti. Aynı 100 soru 0 kontrol hatası verdi.
İki kaynak müzikalinin toplam 10 seansı theatre döndü; aynı başlıkların konser
aramasında Biletinial yanlış eşleşmesi kalmadı. Ayrıntılı yerel tekrar raporu
`docs/qa/events-my-100-after-fix-0.5.2.md` içindedir. Kalan TTL, sahte saatli
regresyonla doğrulandı; kısa canlı test tüm bir saatlik döngüyü ölçmez.
