# Veri işleme ve gizlilik notu

Son güncelleme: 2026-10-25. Bu belge depodaki uygulama davranışını açıklar;
isteminizi kullandığınız MCP istemcisinin veya barındırma sağlayıcısının
politikalarının yerine geçmez.

## İşlenen veriler

- MCP istemcisi yalnızca seçtiği araç çağrısını ve argümanlarını sunucuya gönderir.
  Bu argümanlar arama metni, ilçe/mahalle, hat/durak veya koordinat içerebilir.
  Uygulama bu işlem için sohbet geçmişinin tamamını istemez.
- Kaynağa göre gerekli arama/filtre parametreleri İBB, İETT, İSKİ veya diğer
  resmî kaynaklara iletilebilir. Tam kaynak listesi `istanbul://sources` içindedir.
- Statik GTFS tarife sorguları tam dosya alındıktan sonra yerel SQLite'ta çözülür;
  bu sorgu yolunda kullanıcının durak/koordinat argümanları kaynağa gönderilmez.
- IP adresi/sunucunun doğrulanmış istemci kimliği, süreç içi kötüye kullanım
  sınırlayıcısında tutulur. API anahtarlı modda günlük kullanım sayacı UTC gününe
  göre SQLite'a yazılır; sayaç ham anahtar yerine anahtar hash'i kullanır.

## Günlükler ve saklama

Araç bazlı `istanbul_mcp.tools` günlüğü kayıtlı araç adı, süre, sonuç türü,
sabit hata kategorisi, dönen liste uzunluğu, tazelik/kısmi cevap işareti ve ortak
önbellek sayaçlarını içerir. Argümanlar, koordinatlar, sorgu metni, anahtarlar,
yanıt metni, önbellek anahtarı veya exception mesajı bu kayda eklenmez.
Bilinmeyen araç adları `__unknown__`, bilinmeyen hata kodları `other_error`
olarak birleştirilir. Toplamlar süreç belleğinde sınırlı alanlarda tutulur;
yeniden başlatmada sıfırlanır. Günlüklerin saklanması ise sağlayıcıya bağlıdır.

`/status`, bu toplamları ve son tamamlanan çağrı zamanını gösterir. Herkese açık
modda bu operasyon bilgileri herkese açıktır; anahtarlı modda mevcut `/status`
kimlik doğrulaması korunur. Kullanıcı/istemci bazında izleme yapılmaz.
[Ölçüm kapsamı](monitoring.md).

Uygulamanın `JsonRequestLogMiddleware` günlüğü HTTP yöntemi, path, durum kodu ve
süreyi kaydeder; istek gövdesini, Authorization başlığını veya sorgu string'ini
bu kayda eklemez. ASGI sunucusu, SDK ve barındırma altyapısı ayrıca işletim/hata
ve erişim günlükleri üretebilir. Bu belge bunların hiç veri saklamadığını veya
belirli bir sürede sildiğini iddia etmez. İşletmeci yayın öncesi bu ayarları ve
barındırma sağlayıcısının saklama politikasını ayrıca gözden geçirmelidir.

Şehir verileri ve kaynak yanıtları süreç içi önbellekte ve ilgili katalog/geo/
tarife tablolarında tutulabilir. Bu sunucuya şifre, kimlik belgesi, sağlık bilgisi,
özel adres veya hassas sohbet metni göndermeyin. Yakınlık sorgusu için kesin
ev adresi yerine yaklaşık konum kullanabilirsiniz.

## Erişim ve destek

Sunucu varsayılan olarak herkese açık ve salt okunurdur; istek/sonuç sınırları
uygular. API anahtarı ve kota isteğe bağlıdır; [erişim rehberi](api-access.md).
Veri güncelliği/servis kapsamı garanti edilmez; tool sonuçlarının `freshness`,
`sources`, `limits`, `warnings` alanları geçerlidir.

Genel destek: [GitHub Issues](https://github.com/Batu1-1an/istanbulmcp/issues).
**Hassas içerikleri public issue'ya eklemeyin.** Güvenlik bildirimi için,
etkinse [private vulnerability reporting](https://github.com/Batu1-1an/istanbulmcp/security/advisories/new)
kanalını kullanın; özel kanalın etkinliği bu oturumda doğrulanmamıştır.
