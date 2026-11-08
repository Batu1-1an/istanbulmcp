# Ücretsiz etkinlik ve gün içindeki seans kaybı incelemesi

2026-11-08; kullanıcı raporu sonrası, düzeltme sürümü 0.6.0.

## Doğrulanan mekanizmalar

Raporda 02:13'te 0 TL görülen, 13:00 başlangıçlı Kardan Adamın İnadı ve
Mouse Ailesi'nin 15:26'da bulunamadığı bildirildi. Verilen kimlikler
`event_c98c9b41bec68dbe7ce9c458` ve `event_5141341da6e94a46452401eb`.
İnceleme başlangıcında production bu iki ID için not_found, aynı tarihte
free_only için 0 sonuç döndürdü. Sabahki production snapshot'ı ve değişim
geçmişi saklanmadığı için tam kaybolma anı veya tek sebep belirlenemedi.

- 0.5.3 arama, date_from bugün olduğunda start_at < now kayıtlarını gizliyordu.
  15:26'da ilk seansın 16:00 olması bununla uyumludur.
- Detay saat filtresi kullanmaz; aktif/kullanılabilir kaynak kaydı ister.
  Detayda kaybolmayı yalnız başlangıç saati açıklamaz.
- Kaynak/seri yenilemesi önceki seansları pasifleştirebilir. Mevcut DB'de
  pasif kayıtlar iki güne kadar saklanır; bu tam bir arşiv değildir.
- Railway kontrolünde 12:25:51 UTC (15:25:51 İstanbul) deploy'u ve sıfır
  volume görüldü. Deploy yerel kataloğu yeniden oluşturabilir. Bu durum
  iki özel kaydın kesin nedeni diye sunulmaz.
- Yerel eski test DB'lerinde Mouse Ailesi kimliği vardı; bunlar production
  geçmişinin veya kaybolma zamanının kanıtı değildir.
- Fiyat teklifleri detail TTL'inden (varsayılan 15 dakika) sonra unknown
  olur. Sabahki 0 TL fiyat öğleden sonraki ücretsiz giriş kanıtı değildir.
- Free koşulu public limitten önce uygulanır. Detay doğrulaması en fazla
  üç seridir; bütün kaynak fiyatlarının veya şehrin tarandığı söylenemez.

## Uygulanan açıklık ve tutarlılık düzeltmeleri

`include_past=false` bütün tarih pencerelerinde başlamış seansları eler;
önceden geçmiş günle başlayan pencere bu kontrolü atlayabiliyordu.
`include_past=true` yalnız halen aktif yerel geçmiş kayıtları açar; silinmiş
veriyi veya eski fiyatın geçerliliğini geri getirmez. Planlama geçmiş gün
için seçilmiş ID verilse de başlamış seansı önermez.

`include_sold_out=true` ile bütün teklifleri tükenmiş bir seansın taze
gözlenen fiyatı (0 dahil) inceleme için gösterilebilir; availability=sold_out
kalır. Varsayılan önerilerde tükenmiş fiyat kullanılmaz. Aktif/tükenmiş
eşit fiyatlı tekliflerde aktif bilet etiketi korunur.

`result_info.filter_counts` aşamaları açıklar: initial_indexed_candidates
(detay doğrulama öncesi), indexed_candidates (yeniden okuma sonrası),
usable_observations, deduplicated_sessions; excluded_started/program/category/
age/clock/location/sold_out; known_price_sessions, unknown_price_sessions,
excluded_unknown_price, excluded_price; expired_offer_observations,
detail_checks_attempted/succeeded; verified_free, matched, returned.
verified_free son filtrelerden geçen limit öncesi sayıdır. Ham gözlem ile
tekilleştirilmiş seans sayıları farklı birimlerdir; tüm sayaçlar tek toplam
gibi toplanmaz. Bunlar sınırlı sorgu indeksinin sayılarıdır, şehir toplamı değildir.

Detay hata kodları:

- catalogue_retired: bu DB'de saklanan gözlem var ama aktif seans yok.
- source_unavailable: aktif yerel kayıt var ama kaynak snapshot'ı kullanılamıyor.
- not_found: bu DB'de saklanan geçmiş yok; kesin kaldırma nedeni bilinmiyor.

Hata zarfında retained_sessions, active_sessions, last_seen_at ve kaynaklar
bulunur. last_seen_at kaldırma zamanı değildir. İptal veya sağlayıcının
silmesi sonucu çıkarılmaz. Yeni migration/env yoktur. Kalıcı volume veya
deploylar arası arşiv bu değişiklikte eklenmedi.

## Doğrulama

```bash
pytest tests/test_events_free_lifecycle.py
```

Sabit 15:26 saatinde aynı snapshot'ın normal/ücretsiz alt kümesi, 13:00
seansı opt-in, fiyat zaman aşımı, tükenmiş ücretsiz opt-in, ilk 60 ücretli
adaydan sonraki ücretsiz kayıt, geçmiş detay erişimi, pasif/unknown-history/
kaynak erişimi ayrımı ve geçmiş ID'li plan sınanır. Dış ağ kullanılmaz.


Geniş regresyon: 1.767 toplandı, 1.702 geçti, 65 dış kaynak testi atlandı;
0 hata (`.data/events-free-lifecycle-full.xml`). Son küçük plan/sayaç
düzeltmeleri hedefli 206 test ve en son yaşam döngüsü grubundaki 10 testle
kontrol edildi. Bu son gruplar da hatasızdır; geniş koşu son küçük
değişikliklerden önce başlamıştı. İlk production snapshot'ları yeniden
oluşturulmadı ve tarihsel kaybolma zamanı varmış gibi raporlanmadı.
