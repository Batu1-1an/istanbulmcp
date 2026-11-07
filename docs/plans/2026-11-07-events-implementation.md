# Etkinlik keşfi ve günlük planlama uygulaması

## Kapsam ve kabul koşulları

İstanbul MCP'ye `istanbul_events_search`, `istanbul_event_detail` ve
`istanbul_events_plan` eklenir. Mevcut yayımlanmış araçlar çağrılabilir kalır.
Araçlar aynı ResponseEnvelope sözleşmesini, kaynak/tazelik/sınır/uyarı alanlarını
ve salt okunur MCP annotations kullanır. Özellik kapalıyken listelenmez, eski
istemcilerin çağrıları kontrollü `feature_disabled` yanıtı alır.

- Ticketmaster TR feed: toplu katalog; Biletix'e otomatik istek yok.
- Biletinial: ayrı yapılandırma bayrağı, İstanbul katalog sayfalaması ve seans
  detayı. Fiyat/uygunluk yalnız eşleşen seansa uygulanır.
- Seri, seans, mekân ve teklifler ayrı tutulur. Kaynak kimliği ve gözlem tarihi
  korunur; saat değişimi kimliği değiştirmez. Belirsiz benzerlik birleştirmez.
- SQLite WAL, normalize Türkçe FTS5 ve RTree. Tamamlanmamış kaynak yenilemesi
  son sağlam anlık görüntünün üzerine yazmaz. Kaynak kaybı iptal/tükenme değildir.
- Arama: tarih/saat, metin, tür, ilçe/mekân, yakınlık ve bütçe. Bilinmeyen fiyat
  bütçeye uygun sayılmaz; sayılar ve kırpma açıkça bildirilir.
- Detay: kaynak gözlemleri, seanslar, teklifler, kısaltılmış açıklama; canlı
  koltuk veya kesin toplam ödeme tutarı iddiası yok.
- Plan: tek gün, en fazla üç etkinlik, deterministik tam sayım; aday sınırı ve
  bilinmeyen bitiş/bütçe/ulaşım açıkça belirtilir. Takvim linkleri ve ICS çıktısı.
- Kaynak indirmesi, açılmış gzip, kayıt, süre ve sonuç boyutları sınırlıdır.
  Harici URL'ler kullanıcı tarafından fetch hedefi yapılamaz; anahtar sızmaz.
- Fixture testleri, kaynak hatası/yenileme atomikliği, Türkçe arama, kimlik,
  filtreler, plan değişmezleri ve MCP protokolü doğrulanır. Canlı kaynak
  doğrulamaları unit testlerden ayrıdır.

## Araştırmadan düzeltilen kararlar

Ticketmaster fiyat alanları kullanılmaz; `transactable=false` tükenmişlik değildir.
JSON-LD seans kapsamı tam varsayılmaz. Trigram yazım hatası motoru değildir.
RapidFuzz eklenirse ham fuzz skorları 0–100 ölçeğindedir. FTS external-content
kolonları gerçek içerik tablosuyla eşleşmelidir. `data` her zaman listedir;
ticari kaynaklara İBB yayıncı/lisans varsayılanları uygulanmaz. Foreign key
denetimi her SQLite bağlantısında etkin olmalıdır.

## Dokümantasyon ve yayın

Davranış, ayarlar ve kullanım örnekleri `docs/events.md`, README,
`docs/tool-reference.md`, `docs/configuration.md`, `docs/development.md` ve
CHANGELOG'a işlenir. Uygulama sırasında bulunan yeni sınırlar ve doğrulama
sonuçları etkinlik belgesinde kaydedilir. `pyproject.toml` / `server.json`
sürümleri birlikte yükseltilir. Railway durumu yayın öncesi kontrol edilir.

## Kontrol edilen teknik kaynaklar

- Ticketmaster feed ve fiyat alanlarının kaldırılması:
  https://developer.ticketmaster.com/products-and-docs/apis/discovery-feed/
  ve https://developer.ticketmaster.com/products-and-docs/apis/discovery-feed/release-notes/
- SQLite FTS5 external content, trigger ve trigram: https://sqlite.org/fts5.html
- RapidFuzz skor ölçeği: https://rapidfuzz.github.io/RapidFuzz/Usage/fuzz.html
- MCP kaydı mevcut `mcp>=2.3,<3` uygulamasına ve protokol testlerine uyar.

Araştırma klasöründeki belgeler tarihli kanıttır; bu plan uygulanmış/test edilmiş
olduğunu tek başına göstermez. Güncel durum ve sonuçlar `docs/events.md` içindedir.

## Uygulama sonucu

2026-11-07: üç araç ve isteğe bağlı etkinlik prompt’u uygulandı; Ticketmaster
ve Biletinial production üzerinde doğrulandı. Bu aşamanın sürümü 0.3.1; kaynaklar
checked, toplam araç sayısı 21. Geniş regresyon geçti; son hedefli grupta
117 test ve son HTTP değişikliği sonrası etkinlik grubunda 32 test başarılı.
Tarih/saat, snapshot atomikliği, Türkçe arama, bilinmeyen fiyatlar, seans
kimliği, ICS ve eski araç çağrıları doğrulandı. Ayrıntılı ölçümler ve
özellikle provisional Biletinial kapsamı docs/events.md içindedir.

Ardından farklı kullanıcı sorularından çıkarılan 0.4.0 geliştirmeleri
[ayrı plan](2026-11-07-events-persona-improvements.md) ve
[doğrulama raporunda](../events-persona-validation.md) izlenir.
