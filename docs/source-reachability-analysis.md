# Kaynak Erişilebilirlik Analizi — Neden Bazı Araçlar Çalışmıyor?

**Tarih:** 2026-08-26 (İBB eczane geçişi öncesi gözlem)
**Kapsam:** İstanbul MCP'nin canlı (Railway) ortamda bazı araçlarının `unavailable` / zaman aşımı dönmesinin kök nedeni.
**Sonuç (tek cümle):** Bu tarihli raporda iki dış kaynağın (Şehir Hatları ve eski İEO adapter'ı) Railway erişim sorunları kaydedilmiştir; eczane adapter'ı artık resmi İBB City Map kaynağını kullanır.

---

## 1. Kısa Özet

İstanbul MCP, İstanbul'a dair kamu verisini **gerçek İnternet kaynaklarından** çekiyor. Bu kaynakların bazıları, bizim Railway sunucumuzdan gelen istekleri kabul etmiyor. Bu yüzden ilgili araçlar `ok=false` / `unavailable` / zaman aşımı döndürüyor.

Bu analiz, **benim eklediğim Metro Arıza aracından bağımsız** olan iki alanı inceler:
- **Vapur saatleri** (`istanbul_ferry_schedules`)
- **Nöbetçi eczane** (`istanbul_nobetci_eczane_nearby`, `istanbul_nobetci_eczane_by_district`)

> ⚠️ **Önemli ayrım:** Yeni eklenen `istanbul_metro_accessibility_status` aracı **canlıda sorunsuz çalışıyor** ve bu rapordaki sorunlardan etkilenmiyor. Aşağıdaki tüm sorunlar, deploy'dan **önce de var olduğu** için bu feature ile ilgili değildir.

---

## 2. Etkilenen Araçlar ve Kaynakları

| Araç | Kaynak (upstream) | Canlı Durum | Kök Neden |
|------|-------------------|-------------|-----------|
| `istanbul_ferry_schedules` | `sehirhatlari.istanbul` | ❌ `unavailable` | HTTP 403 + cookie-consent (bot koruması) |
| `istanbul_nobetci_eczane_by_district` | `cbsproxy.ibb.gov.tr` | ✅ local adapter | İBB City Map roster (`ilceID=all`) |
| `istanbul_nobetci_eczane_nearby` | `cbsproxy.ibb.gov.tr` | ✅ local adapter | İBB City Map roster (`ilceID=all`) |
| `istanbul_metro_accessibility_status` | `api.ibb.gov.tr` + `metro.istanbul` | ✅ `fresh` | — (çalışıyor) |

---

## 3. Sorun 1 — Şehir Hatları (Vapur): HTTP 403

### Ne oluyor?
Railway'den `sehirhatlari.istanbul`'a istek atıldığında site **403 Forbidden** dönüyor. Aynı isteği kendi bilgisayarımdan (local) gönderdiğimde site **HTTP 200** dönüyor.

### Neden?
Araştırma (Exa MCP + kaynak analizi) gösterdi ki:

1. **Site Cloudflare bot koruması kullanıyor.** Cloudflare, "normal web tarayıcısı" gibi görünmeyen istekleri (sunucudan gelen script istekleri) otomatik olarak 403 ile engelliyor. Bizim Railway sunucusundan gelen istek, bu bot-detection filtrelerine takılıyor.
2. **Sayfa cookie-consent önüne takılıyor.** `/tr/iptal-seferler` sayfası, içeriği yüklemeden önce `__doPostBack('ctl00$Cookie$btnCerezler','')` şeklinde bir çerez onayı istiyor. Çerez kabul edilmeden gerçek veri gelmiyor.

### Relay hâlâ neden çalışmıyor?
Projede bir Cloudflare Worker relay var (`istanbul-iski-relay.batuaa70.workers.dev`), İSKİ için kurulmuş. Şehir Hatları için de bir `/transport/sehir-hatlari` yolu var. Ancak:

- Relay, `www.sehirhatlari.istanbul/tr/iptal-seferler` adresine gidiyor.
- O sayfa **cookie-consent** + bot koruması yüzünden, relay bile düzgün içerik alamıyor → **502 Bad Gateway**.
- Yani relay'in kendisi de aynı site engeline takılıyor.

---

## 4. Tarihsel Sorun 2 — İEO (Nöbetçi Eczane): Zaman Aşımı

> Bu bölüm eski İEO entegrasyonunun 2026-08-26 gözlemidir. İEO entegrasyonu kaldırıldı; mevcut araçlar `https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=all` endpoint'ini kullanır.

### Ne oluyor?
Railway'den `istanbuleczaciodasi.org.tr`'ye istek atıldığında **30 saniye boyunca hiç yanıt gelmiyor** (timeout). Ama kendi bilgisayarımdan aynı istek **0.05 saniyede HTTP 200** dönüyor.

### Neden?
1. **İEO'nun resmi bir JSON API'si yok.** Proje, İEO'nun web sayfasına `POST` isteği yapıyor (`get_eczane_markers` parametresiyle). Bu, resmi API olmayan, sayfaya dayalı bir kazıma (scraping) yöntemi.
2. **İEO sunucusu Railway'in IP aralığına erişim vermiyor.** İstek TCP/HTTP katmanında tamamlanamıyor — yani bağlantı hiç kurulmuyor. En olası neden: İEO sunucusu, Cloudflare/balancer IP aralığından gelen istekleri coğrafi veya güvenlik nedeniyle engelliyor.
3. **Aynı siteye local'den ulaşmak** (benim IP'mlə) sorunsuz — yani site kendisi çalışıyor; sorun **bizim sunucudan** erişimde.

---

## 5. Ortak Kök Neden

Her iki sorunun da ortak noktası şu: **Kaynak siteler, kendi sunucuları dışındaki (özellikle bulut/balancer) IP aralıklarından gelen otomatik istekleri engelliyor.** Bu, İnternet'te çok yaygın bir "bot koruması" davranışı:

- Şehir Hatları → Cloudflare bot koruması (403)
- İEO → IP/coğrafi erişim engeli (timeout)

Bu, kendi kodumuzda bir hata olduğu anlamına gelmez; **dış kaynakların bizim sunucuya izin vermemesi** anlamına gelir.

---

## 6. Mevcut Çözüm Altyapısı: Cloudflare Worker Relay

Projede zaten bir "köprü" var: `workers/iski-relay` bir **Cloudflare Worker**.

### Relay nedir?
Relay = aracı/köprü servis. Bizim sunucu bazı sitelere doğrudan gidemiyor. Relay, **araya girip o siteye bizim yerimize gidip** veriyi getiren küçük bir servis.

### Neden Cloudflare Worker?
Cloudflare'in kendi ağından çıkan istekler (`*.workers.dev`), Cloudflare'in bot korumasını **neredeyse her zaman aşabilir** çünkü Cloudflare kendi trafiğine güvenir. Bu yüzden İSKİ için kurulmuş.

### Şu anki relay neleri karşılıyor?
```
UPSTREAMS:
  /iski/faults  → harita.iski.gov.tr/data/mahallelerKesinti.geojson
  /iski/dams    → harita.iski.gov.tr/data/baraj.json

TRANSPORT_UPSTREAMS:
  /transport/sehir-hatlari → www.sehirhatlari.istanbul/tr/iptal-seferler
```

**Tarihsel eksik:** Eski İEO adapter'ı için relay yoktu. Bu bağımlılık kaldırıldı.

---

## 7. Çözüm Seçenekleri

### Seçenek A — Relay'i güçlendirmek (önerilen, kalıcı)
Mevcut Cloudflare Worker relay'i her iki sorun için genişletmek:

- **Şehir Hatları:** Relay'in gittiği adresi ve header'ları düzeltmek, cookie-consent postback'ini simüle etmek. Böylece relay, Cloudflare ağından Şehir Hatları'nı asabilir.
- **İEO (tarihsel):** Relay'e `/transport/nobetci-eczane` yolu eklemek. Bu seçenek artık gerekli değildir; İBB City Map resmi kaynağı kullanılmaktadır.

**Artı:** Mevcut `workers/iski-relay` kalıbı korunur, tek çatı altında toplanır.
**Eksi:** Cloudflare'e deploy + test etmek zaman alır; Şehir Hatları cookie-consent'i hâlâ sorun olabilir.

### Seçenek B — Alternatif veri kaynağı kullanmak
- **İEO için:** Üçüncü taraf API'ler (`eczaneapi.com`, `nobetecza.com`) — ama API key gerektirir, ticari; mevcut "resmî kaynak" ilkesini zedeler.
- **İBB Şehir Haritası API'si** — **doğrulandı, çalışıyor (2026-08-26):**

  ```text
  Endpoint: https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=all
  ```

  - `ilceID=all` → tüm İstanbul (runtime satır sayısı sabit değildir)
  - `ilceID=<id>` (örn. `1103`) → o ilçe (örn. ADALAR, 5 kayıt)
  - Veri formatı: `{"ArrayOfAramaList": {"AramaList": [...]}}`
  - Her kayıt: `ADI`, `ADRES`, `TELEFON`, `LAT`, `LON`, `ILCEID`, `ILCEADI`, `MESAFE`
  - Kalite testi: 5 ardışık erişim hepsi HTTP 200; tüm `LAT`/`LON` sayısal; 39 ilçe
  - Bu, İBB'nin kendi resmî Şehir Haritası katmanı → Railway'den erişim sorunu yaşama olasılığı çok düşük

  **Not / dikkat:** Bu katman, eski İEO `get_eczane_markers` akışından daha az detaylıdır (`nobet_bitis` gibi alan yok; yalnızca konum + ad + telefon + ilçe). İBB geçişi tamamlandı; `app/connectors/ibb_pharmacy.py` ve `app/services/pharmacy.py` alan eşlemesini yürütür.

- **Şehir Hatları için:** Resmi, dokümante edilmiş bir JSON API yok. Alternatif yok.

### Seçenek C — Şimdilik kabul etmek
Bu iki aracın canlıda `unavailable` / açık hata raporlamasını kabul etmek. Zaten araçlar bunu **dürüstçe** `ok=false` + `sources[].coverage_status=unavailable` + `warnings` ile bildiriyor. Kullanıcıya yanlış veri sunulmuyor; sadece veri gelmiyor.

---

## 8. Sonuç

| Sorun | Kök Neden | Çözüm |
|-------|-----------|-------|
| Şehir Hatları (vapur) 403 | Cloudflare bot koruması + cookie-consent | Relay'i güçlendirmek (Seçenek A) |
| Eski İEO (eczane) timeout | Railway IP aralığına erişim engeli | **İBB CBS API'ye geçiş (uygulandı)** |

**Ana fikir:** Bu tarihsel rapor Metro Accessibility özelliğinden bağımsızdır. Eczane erişim sorunu, resmi İBB `cbsproxy.ibb.gov.tr/?eczanews&ilceID=all` katmanına geçişle giderilmiştir; Şehir Hatları için relay araştırması ayrı konudur.

---

## 9. Ek Not: Tarihsel Test Durumu

> Aşağıdaki canlı test sonuçları İBB eczane geçişinden önceki 2026-08-26 çalıştırmasına aittir; yeni adapter için opt-in testler `tests/live/test_mcp_live.py` içinde tutulur.

- `RUN_LIVE_MCP_TESTS=1 ... -k metro_accessibility` → **geçti** (benim eklediğim araç canlıda çalışıyor) ✅
- `RUN_LIVE_MCP_TESTS=1` (tüm canlı testler) → **3 fail**:
  - `test_live_mcp_ferry_schedule_scope_is_explicit`
  - `test_live_mcp_nobetci_eczane_by_district_tool`
  - `test_live_mcp_nobetci_eczane_nearby_tool`
- Hepsinin sebebi: Railway'den kaynaklara erişim engeli (403 + timeout), kod hatası değil.

---

*Rapor, Exa MCP web araştırması ve Railway loglarının incelenmesiyle hazırlanmıştır.*
