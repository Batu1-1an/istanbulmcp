# 50 gerçek MCP sorusundan sonra: kaynak saati ve fiyat sunumu düzeltmesi

8 Kasım 2026 · 0.6.1.

## Kanıt ve kök neden

17.02'de production 0.6.0 üzerinde 50 soru için 50 ayrı MCP tools/call çalıştı:
35 arama, 7 detay, 8 plan. 36 soru veri, 9 soru boş sonuç ve 5 soru beklenen
hata döndürdü. Parametre/yanıt denetimlerinde ihlal yoktu. Bu denetimler HTML
ile JSON-LD'yi karşılaştırmıyordu; sıfır kontrol hatası, kaynak içi saat
çelişkisi bulunmadığını kanıtlamıyordu.

Q37/Q49'da Emaar Akvaryum için ertesi gün 00.15 seansı seçilmişti.
Ardından gerçek MCP detay yanıtında aynı seri için 23 HTML kimlikli 21.15
seansı ile 10 JSON kaynaklı 00.15 seansı birlikte gözlendi. Gece yarısındaki
kayıt kimliği `json:2026-11-09T00:15:00+03:00:Emaar Akvaryum` üzerinden
üretilen `perf_bbf23a288e2a42f59914f240` idi. Genel giriş ürününde gece
ziyaretinin uygun olduğu bundan çıkarılamaz.

[Sağlayıcı sayfasının](https://biletinial.com/tr-tr/etkinlik/emaar-akvaryum-sualti-hayvanat-bahcesi)
güncel yerel indirmesinde HTML 21.15 ve JSON-LD +03:00 ile 21.15 yayımlıyordu.
Production'ın o indirmesinin ham HTML'i saklanmadığından iki indirme arasındaki
kaynak varyasyonunun nedeni kesinleştirilmedi. Saat farkı ürün başlığından veya
varsayılan çalışma saatlerinden tahmin edilmedi.

Kontrollü fixture, ayrıştırıcının somut kusurunu yeniden üretti: JSON-LD
`2030-11-08T21:15:00Z` ile aynı mekânın HTML `08 Kasım 21:15` seansı birlikte
geldiğinde, eski kod hem HTML kimlikli 21.15 hem ertesi gün JSON kimlikli
00.15 kaydı oluşturuyordu. Liste tarihleri yoksa yalnız yanlış güne kayan JSON
kaydı kalıyordu. Bu, geniş sorgunun başarılı görünmesine rağmen fazladan seans
ve ayrı bir fiyat sunulabilmesini açıklayan doğrulanmış ayrıştırma kusurudur.
Production ham gövdesinin tam offset yazımı yeniden oluşturulmuş sayılmaz.

## 0.6.1 davranışı

- HTML seansının açık gün/ay, saat ve mekânı JSON'un ham tarih/saat bileşenleriyle
  eşleşiyor, fakat normal offset dönüşümü HTML'deki hiçbir seansa eşleşmiyorsa
  HTML'nin yayımladığı İstanbul saati kullanılır. Yıl tam kaynak tarihinden gelir.
- Normal UTC dönüşümü başka bir HTML seansına tam eşleşiyorsa o gerçek an korunur.
  JSON-only kayıtlar normal timezone dönüşümünü korur. Tüm 00.xx seansları silinmez.
- Aynı kaynak kaydı ikinci JSON seansı olarak eklenmez. Başka mekânın saati
  eşleşme kanıtı değildir. Birden çok olası kaynak yılı varsa yıl uydurulmaz.
- Çelişen JSON bitişi kullanılarak yapay bir süre oluşturulmaz. Ayrı yayımlanmış
  süre varsa mevcut duration politikası geçerlidir; aksi hâlde bitiş unknown kalır.
- Kartlar `start_time_basis=provider_datetime|html_session|json_ld`,
  `source_time_conflict` ve `warnings` içerir. Arama/plan uyarıları da çelişkiyi taşır.
  Bu bilgi, işletmenin o saatte açık olduğu garantisi değildir.
- Detay yenilemesi eski fazladan JSON kaydını pasifleştirir. Kullanıcı eski
  performance_id'yi seçtiyse plan onu farklı seansa sessizce taşımaz;
  `selection_changed` ile yeni seçim ister.
- Öğrenci, çocuk, kategori, çift kişilik gibi koşullu minimum teklif varsa
  arama ve plan açık fiyat uygunluğu uyarısı verir. `ticket_type` ve
  `eligibility_may_apply` korunur; tutar kişi başı genel giriş fiyatı sayılmaz.

Yeni tablo, migration, environment değişkeni veya araç adı yoktur. Mevcut payload
alanları geriye uyumlu varsayılanlarla okunur. Fiyat gözlemi TTL'i, ücretsiz
filtre, geçmiş seans politikası ve 21 araç yüzeyi korunur.

## Diğer 50-soru bulgularının kararı

Festival/spor kategorilerindeki sıfır gözlem, dünün arşiv verisinin olmaması,
ikisi eski kimlik olan beklenen not_found yanıtları ve yaş/bütçe/pencere
koşullarındaki boş sonuçlar ayrı ayrı incelendi. Bunlar filtre bozukluğu veya
iptal kanıtı değildi; sırf sonuç üretmek için fiyat/yaş/saat sınırları gevşetilmedi.
Kalıcı tarih arşivi veya yeni sağlayıcı bu düzeltmenin yerine geçen çözüm değildir.

Custom ChatGPT bağlantısı için eski “yayın incelemesini bekle” ifadesi ana
etkinlik rehberinde düzeltildi. Bağlantı ChatGPT Plugins üzerinden Refresh
edilip yeni sohbet açılmalıdır. Bu oturumda plugin yönetim araçlarında metadata
yenileme yeteneği yoktur. Tarayıcıdan bağlantı sayfası denendi; Cloudflare insan
doğrulamasında kaldı, Refresh yapılmış sayılmadı. Canlı endpoint'in güncel olması
istemcinin listesinin yenilendiğini kanıtlamaz.
[Resmî OpenAI metadata yenileme akışı](https://developers.openai.com/plugins/deploy/connect-chatgpt#refresh-metadata).

## Doğrulama

```bash
pytest tests/test_events_source_time.py
```

Sekiz ağsız test; HTML/JSON-LD çelişkisi, katalog tarihi olmaması, doğru UTC gece
seansı, aynı mekândaki gerçek iki farklı seans, başka mekân, yıl belirsizliği,
takvim saati ve repository → detay → arama → plan boyunca eski JSON seansının
pasifleşmesini sınar. Koşullu fiyat uyarıları da bu akışta kontrol edilir.
Fixture kurmacadır; tam sağlayıcı HTML gövdesi depoya eklenmedi.

İlk beş test düzeltmeden önce başarısızdı; iki test yanlış seans sayısı/günü
üzerinden, diğerleri yeni açıklayıcı alanların eksikliği üzerinden düştü.
Kanıt `.data/events-source-time-before.xml` içinde. Düzeltme sonrası ilk hedefli
etkinlik grubunda 172 test, son kaynak-saati grubunda 8 test geçti. Tam koşu:
1.777 toplandı, 1.712 geçti, 65 atlandı, 0 hata/başarısızlık. Sonuçlar yerel
`.data/events-source-time-*.xml` dosyalarında tutulur. Canlı 50-soru tekrarının ayrı raporu, tamamlandığında
`docs/qa/events-real-mcp-50-after-0.6.1-2026-11-08.md` içinde tutulur.

Railway uzaktan tanı denemesinde hesapta kayıtlı SSH anahtarı olmadığı görüldü;
yeni anahtar eklenmedi ve erişim ayarı değiştirilmedi. Production ayrıntıları
halka açık gerçek MCP araçlarından okundu. CLI davranışı için
[Railway SSH belgesi](https://docs.railway.com/cli/ssh) kontrol edildi.
