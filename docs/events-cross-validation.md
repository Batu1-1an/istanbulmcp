# Etkinlik modülü: farklı açılardan doğrulama

2026-11-08; 0.5.3 düzeltmesi. Bu tur önceki 100 sorunun tekrarı değildir.

## Test eksenleri

| Eksen | Kanıt yöntemi |
|---|---|
| Birleşik filtreler | Tür × bütçe × ilçe × saat × yarıçap için 72 kombinasyon; sabit 36 kayıttan bağımsız beklenen ID kümesi |
| Sonuç ilişkileri | Küçük limitin büyük listenin başı olması; küçük yarıçapın büyük yarıçapın alt kümesi olması |
| Teklif anlamı | Tükenmiş/aktif aynı fiyatlı bilet türü; EUR teklifinin TRY minimumuna karışmaması |
| Eşzamanlı yenileme | 12 eşzamanlı çağrının mock connector'a yalnız bir indirme yaptırması |
| Planlama | 12 ilgi/bütçe/bitiş kombinasyonunda toplam, tür ve pencere koşulları |
| Tarih/saat/yaş sınırı | UTC 21:30'un İstanbul'da ertesi gün 00:30 olması ve ICS UTC çıktısı; artık gün, ay sonu ve yaş aralığı uçları |
| Canlı birleşik kullanım | 28 farklı filtre/plan çağrısı ve dört thread üzerinde sekiz salt okunur arama |

Fixture testleri dış ağa çıkmaz. Canlıdaki farklı çağrılar aynı snapshot'a
sabitlenmediğinden canlı veride iki sonuç kümesinin eşitliği bir garanti gibi
sınanmaz; her yanıtın kendi argümanlarına uygunluğu kontrol edilir.
Eşzamanlı canlı bölüm kapasite/yük testi değildir.

## Bulunan ve düzeltilen sorun

Aynı 100 TL fiyatta tükenmiş Öğrenci ve satıştaki Tam teklifi olduğunda,
minimum fiyat hesaplaması tükenmiş teklifi doğru dışlıyordu. Bilet türü için
yapılan ikinci seçim ise yalnız fiyata bakıp Öğrenci etiketini seçebiliyordu.
İndirim hakkı açıklaması da yanlış tekliften geliyordu.

İlk koşuda bu davranış regression testini gerçekten düşürdü:
`.data/events-cross-baseline.xml`. 0.5.3 bilet türünü seçerken de tükenmiş
teklifi dışlar. Yanıt modeli ve yayımlanmış araç isimleri korunur.
Bu kusur kontrollü fixture'da doğrulandı; canlıda aynı iki teklifin bulunduğu
iddia edilmez.

## Tekrar komutları

```bash
pytest tests/test_events_cross_checks.py
railway run .venv/bin/python -m scripts.events_cross_uat --output .data/events-cross-live.json
```

Canlı koşucu her çağrının argümanını, özet sonucunu, tazeliğini ve süresini
kaydeder. Boş sonuç bulma başarısı sayılmaz; beklenmedik araç/protokol hataları
başarısızlıktır. Varsa MCP_API_KEYS yalnız Authorization için bellekte kullanılır.
Ham yanıt veya secret rapora yazılmaz. Doğal dil yönlendirmesi ve nihai LLM
sunumu bu turun kapsamı değildir.

İlk düzeltme sonrası hedefli koşu: 174 test, 0 hata/başarısızlık/skip;
`.data/events-cross-final.xml`. Kaynakların gerçek içeriği ve şehir kapsamı
bu ağsız sayılardan çıkarılmaz.
