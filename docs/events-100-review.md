# 100 etkinlik senaryosu raporunun kod ve kanıt incelemesi

Tarih: 2026-11-08. İncelenen yerel rapor:
`docs/qa/events-100-user-scenarios-2026-11-08.md` (394 satırlık ilk sürümün tamamı),
iki `.data/events-100-results*-2026-11-08.json` özeti ve özgün yerel koşucu.
`docs/qa/` kullanıcının ignore kuralı altında kalır; rapor yerelde düzeltildi,
ham ölçümler değiştirilmedi. Kalıcı kod, fixture ve bu inceleme ayrı tutulur.

## Kanıttaki düzeltmeler

69 `ok=true` ve 31 validation_error, 31 ürün hatası değildir. Olumsuz/esnek
beklentilerden 30'u bu yanıtı kabul eder. İki checks_failed kaydı S29 ve S31'dir:
S29 tırnaklı başlığın whitespace ile bölünmesinden gelen kontrol hatası, S31 boş
optional query davranışıdır. İlk koşucuda 67 pozitif, 26 kesin negatif, 7 esnek
senaryo vardır. Ana raporun 36.536 saniyesi çağrı gecikmeleri toplamıdır;
250 ms aralıklar ve preflight dahil toplam duvar süresi değildir.

İlk koşucu initialize sürümünü, seans/teklif ayrıntılarını veya ek 31 günlük
kategori taramasının tam yanıtlarını saklamamıştır. Bu yüzden sürüm 0.4.0,
14 seans/7 teklif ve ek dağılımlar ham özetten bağımsız doğrulanmış sayılmaz.
Tarihli gözlem ile bundan çıkarılan ürün garantisi raporda ayrıldı.

## F1–F12 değerlendirmesi

| Bulgu | Kod/kanıt sonucu | Yapılan işlem |
|---|---|---|
| F1 kategori | Ayrı kaynak türleri family/standup dışında kullanılmıyordu. Bazı gerçek atölyelerde kaynak türü yalnız Etkinlik | Bütün desteklenen kaynak türleri eşlenir; genel kovadaki açık Atölyesi/Sergisi/Festivali/Seminer işaretleri title_marker kanıtıyla ayrılır; kategori gözlenmediğinde sınırlı kapsam uyarısı |
| F2 yenileme | Eski snapshot zaten azami fallback yaşına kadar sunuluyor ve yayın transaction içinde. İki koşudaki fark neden/atomiklik hatasını kanıtlamaz | TTL içindeki yenileme hatası da stale; refresh_status/serving_stale; yenileme sürerken eski bütün snapshot'ı okuma regresyonu |
| F3 seçilen seans | Tarih ve varsayılan 18:00–23:59 penceresi seçilmiş seansa da uygulanır | Pencere sessiz değiştirilmez; dışarıda kalan sayısı, tarih/saat ve açık start_time/end_time onarımı |
| F4 Sıla/Silahşör | Varsayılan önek davranışının gerçek yan etkisi | match_mode=words yeni varsayılan; prefix açık opt-in, ilgili sonuç uyarısı korunur |
| F5 kimlik | Örneklerin biçimi bozuk. Geçerli ama eksik ID zaten not_found | Çalışan validasyon korunur; D63/D64 doğru biçimli eksik kimlikler. Detaydaki trim davranışı korunur, planın da trimlenmiş perf ID'yi tek seans olarak tutması düzeltildi |
| F6 plan çeşitliliği | Ham puan sırası aynı durakların varyantlarını öne alabiliyor | Aynı seri kümeleri tekilleşir, gösterilenlerle örtüşme sonraki seçimi azaltır |
| F7 boş query | Optional alanın boş serialize edilmesi hata yaratıyordu | Boş/whitespace metin filtre yok sayılır; uzunluk sınırı korunur |
| F8 sıfır bütçe | include_unknown_prices=false ve free_only zaten var; unknown sonucu ücretsiz diye etiketlenmiyor | Mevcut max_price davranışı korunur; ücretsiz/kesin bütçe için doğru parametre ve sunum talimatı, regresyon |
| F9 eksik toplam | Bütçe istenmemişse unknown toplam normal seçenek olabilir | Bilinen gözlenen toplam önceliği; eksik toplamda total_observed_minimum_try=null, eski alan yalnız ara toplam |
| F10 gece penceresi | Açıkça belgelenmiş aynı gün sınırı | Değiştirilmedi; iki tarihe bölme onarımı korunur |
| F11 detay | İki yakın çağrıdaki eşitlik gözlemi; seri ID'de selection_status zorunlu değil | Rapordaki genelleme düzeltildi; kalıcı koşucu seans/teklif sayısını kaydeder |
| F12 hata zarfı | Beklenen negatif yanıtlar kabul ölçütüdür | Koşucu beklenen hata kodunu tam karşılaştırır; beklenmedik kaynak hatası geçemez |

## Kaynak ve tasarım kararları

Kaynak kontrolünde Biletinial `GetMoreItems` sayfası categoryName=Etkinlik
yayınladı. Parfüm ve Mozaik Lamba Atölyesi detaylarında ayrı Etkinlik Türü
değeri de yalnız Etkinlik idi. Bu yüzden başlıktaki açık tür işareti bir
dedicated genre olarak sunulmaz; `category_source=title_marker` olur.
Çocuk yaşına uygunluk başlıktan üretilmez. Sağlayıcının açık türü önceliklidir;
diğer türdeki oyunlar başlık benzerliğiyle atölyeye çevrilmez.

Kaynakta doğrulanan sayfalar:

- [Parfüm Atölyesi](https://biletinial.com/tr-tr/etkinlik/parfum-atolyesi-film-gosterimi-ve-sufi-ritim-nefes-deneyimi)
- [Mozaik Lamba Atölyesi](https://biletinial.com/tr-tr/etkinlik/mozaik-lamba-atolyesi-ayasofya-karsisinda-film-gosterimli)

FTS5 tam kelime, quoted term, prefix yıldızı ve column-filter davranışı
`npx ctx7@latest docs /websites/sqlite_docs` ile
[resmî SQLite FTS5 belgesinden](https://www.sqlite.org/fts5.html) kontrol edildi.
Yeni SDK veya bulut API davranışı eklenmedi.

## Tekrar çalıştırma

```bash
pytest tests/test_events_qa_findings.py tests/test_events.py tests/test_event_personas.py
railway run .venv/bin/python -m scripts.events_100_uat --output .data/events-100-current.json
# Önceden çalıştırılmış yerel aday sunucu
.venv/bin/python -m scripts.events_100_uat --url http://127.0.0.1:8770/mcp/ --output .data/events-100-local.json
```

100 niyet `tests/fixtures/events/user_scenarios_100.json` içinde kalıcıdır.
Tarihler çalışma gününden çözülür. İlk iki ölçüm aynen bırakılmıştır; D63/D64
ve kontrol düzeltmeleri nedeniyle yeni koşu birebir aynı argümanlarla A/B
deneyi değildir. Kaynaklar ve detay indeksi de zamanla değişir. Yeni rapor
sürüm, source snapshot/durum, gerçek plan seçenek sayısı ve çağrı/duvar
süresini ayırır. Normalizasyon tırnak/noktalama hatasını düzeltir. Dış ağ
kontrolü CI'ın ağsız testlerinin otomatik parçası değildir.

## Yerel gerçek-kaynak yeniden ölçümü

0.5.0 adayında 100 senaryo, 0 semantik/protokol kontrol hatası. D63/D64
beklenen not_found, S31 ok=true, S29 yanlış alarm olmadan tamamlandı.
Arama → detay → plan akışlarında seçilen performans ve başlangıç korundu.
Ölçüm sayıları ve son test/yayın kanıtı tamamlanan koşulardan aşağıya eklenir.

Aday koşusu 02:34:11–02:36:23 +03:00: Ticketmaster 694, Biletinial 3.385
kabul edilen katalog kaydıyla checked. S14 sergi 8 sonuç; S15 atölye 10
sonuç (22 eşleşme), S24 Türkçe atölye 10 (25 eşleşme) döndürdü. Sıla/Sila
0, S29 çocuk 10, boş query 10 sonuç verdi. Kaynak ve detaylar bu çağrılar
arasında güncellendiği için 22/25 farkı aynı ana sabitlenmiş bir A/B ölçümü değildir.

Spor, seminer ve festival 0 kaldı. P83–P85 seçilen ID'lerin varsayılan
tarih/pencere dışında kalması nedeniyle 0; yeni onarım açıklaması mevcut.
P98 dar aile penceresi de 0. Bunlar pozitif etkinlik bulma başarısı sayılmaz.
W99/W100 gerçek seçilen seansla birer seçenek ve matched döndürdü.

Çağrı toplamı 106.303 s, duvar 131.573 s; medyan 44 ms, p95 4.903 ms,
en yavaş 7.421 ms. Kaynağa bağlı tür doğrulaması ilk rapordan daha fazla
detay çağrısı yapabilir; yeni kapsamın gecikme maliyeti vardır. 12 saniyelik
arama detay bütçesi ve host başına ortak 1 istek/s sınırı korunur.

## Ağsız test ve sürüm kaydı

- Geniş regresyon: 1.659 test toplandı; 1.594 geçti, 65 opt-in dış kaynak
  testi atlandı, 0 hata/başarısızlık (`.data/events-qa-full-regression.xml`).
- Son iki plan kimliği/alternatif seçimi düzeltmesi ve koşucu tarih kontrolleri
  sonrasında etkinlik + registry + yayımlanmış isim uyumluluğu grubu:
  98 geçti (`.data/events-qa-publish-targeted.xml`). Geniş koşu bu son küçük
  değişikliklerden önceydi; hedefli son koşu onları kapsar.
- Değişen/eklenen dosyalarda yerel secret taraması 0 eşleşme verdi;
  büyük snapshot yok, git diff --check temiz. Orijinal yerel kanıtlar korunur.
- Sürüm pyproject.toml ve server.json içinde birlikte 0.5.0; yayımlanmış
  MCP isimleri korunur. Yeni environment variable veya migration gerekmez.

Rapor düzeltmesi, custom ChatGPT bağlantısında güncel araç metadata'sı
alındığını tek başına kanıtlamaz. Custom bağlantı değişikliklerden sonra
Refresh ile yenilenip yeni sohbetten sınanmalıdır.
