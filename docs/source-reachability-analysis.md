# Kaynak Erişilebilirlik Analizi — Neden Bazı Araçlar Çalışmıyor?

**Tarih:** 2026-08-26
**Kapsam:** İstanbul MCP'nin canlı (Railway) ortamda bazı araçlarının `unavailable` / zaman aşımı dönmesinin kök nedeni.
**Sonuç (tek cümle):** Sorun **kodumuzda değil**; iki dış kaynağın (Şehir Hatları ve İEO) **Railway sunucusuna (Cloudflare/balancer IP aralığı) erişim izni vermemesi** yüzünden.

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
| `istanbul_nobetci_eczane_by_district` | `istanbuleczaciodasi.org.tr` | ❌ `unavailable` | Zaman aşımı (Railway'den bağlantı kurulamıyor) |
| `istanbul_nobetci_eczane_nearby` | `istanbuleczaciodasi.org.tr` | ❌ `unavailable` | Zaman aşımı (Railway'den bağlantı kurulamıyor) |
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

## 4. Sorun 2 — İEO (Nöbetçi Eczane): Zaman Aşımı

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

**Görülen eksik:** İEO (eczane) için relay **yok**. İEO doğrudan Railway'den çekiliyor → bu yüzden engelleniyor.

---

## 7. Çözüm Seçenekleri

### Seçenek A — Relay'i güçlendirmek (önerilen, kalıcı)
Mevcut Cloudflare Worker relay'i her iki sorun için genişletmek:

- **Şehir Hatları:** Relay'in gittiği adresi ve header'ları düzeltmek, cookie-consent postback'ini simüle etmek. Böylece relay, Cloudflare ağından Şehir Hatları'nı asabilir.
- **İEO:** Relay'e `/transport/nobetci-eczane` yolu eklemek. Cloudflare ağından İEO'ya erişim, Railway'den erişimden çok daha güvenilir olur.

**Artı:** Mevcut `workers/iski-relay` kalıbı korunur, tek çatı altında toplanır.
**Eksi:** Cloudflare'e deploy + test etmek zaman alır; Şehir Hatları cookie-consent'i hâlâ sorun olabilir.

### Seçenek B — Alternatif veri kaynağı kullanmak
- **İEO için:** Üçüncü taraf API'ler (`eczaneapi.com`, `nobetecza.com`) — ama API key gerektirir, ticari; mevcut "resmî kaynak" ilkesini zedeler.
- **İBB Şehir Haritası API'si** — **doğrulandı, çalışıyor (2026-08-26):**

  ```text
  Endpoint: https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=
  ```

  - Boş `ilceID=` veya `all` → tüm İstanbul (131 kayıt)
  - `ilceID=<id>` (örn. `1103`) → o ilçe (örn. ADALAR, 5 kayıt)
  - Veri formatı: `{"ArrayOfAramaList": {"AramaList": [...]}}`
  - Her kayıt: `ADI`, `ADRES`, `TELEFON`, `LAT`, `LON`, `ILCEID`, `ILCEADI`, `MESAFE`
  - Kalite testi: 5 ardışık erişim hepsi HTTP 200; tüm `LAT`/`LON` sayısal; 39 ilçe
  - Bu, İBB'nin kendi resmî Şehir Haritası katmanı → Railway'den erişim sorunu yaşama olasılığı çok düşük

  **Not / dikkat:** Bu katman, İEO'nun `get_eczane_markers`'ından daha azdetaylıdır (`nobet_bitis` gibi alan yok; sadece konum + ad + telefon + ilçe). Ama mevcut `istanbul_nobetci_eczane_*` araçları zaten benzer düzeyde veri döndürüyordu. Geçiş için `app/connectors/ieo.py` + `app/services/pharmacy.py` içindeki alan-yeniden adlandırma (`eczane_ad`→`ADI`, `lat/lng`→`LAT/LON`) güncellenmeli.

- **Şehir Hatları için:** Resmi, dokümante edilmiş bir JSON API yok. Alternatif yok.

### Seçenek C — Şimdilik kabul etmek
Bu iki aracın canlıda `unavailable` / açık hata raporlamasını kabul etmek. Zaten araçlar bunu **dürüstçe** `ok=false` + `sources[].coverage_status=unavailable` + `warnings` ile bildiriyor. Kullanıcıya yanlış veri sunulmuyor; sadece veri gelmiyor.

---

## 8. Sonuç

| Sorun | Kök Neden | Çözüm |
|-------|-----------|-------|
| Şehir Hatları (vapur) 403 | Cloudflare bot koruması + cookie-consent | Relay'i güçlendirmek (Seçenek A) |
| İEO (eczane) timeout | Railway IP aralığına erişim engeli | **İBB CBS API'ye geçmek (Seçenek B, doğrulandı)** veya relay eklemek (A) |

**Ana fikir:** Bu iki alan **benim eklediğim Metro Accessibility özelliğinden bağımsız**, deploy'dan önce de vardı. Kaynak sitelerin bulut/balancer IP'lerine izin vermemesi nedeniyle. **İEO için** en temiz ve kalıcı çözüm, İBB'nin kendi resmî `cbsproxy.ibb.gov.tr/?eczanews` katmanına geçmek (doğrulandı). **Şehir Hatları için** ise resmi API olmadığından en güçlü seçenek mevcut Cloudflare Worker relay'ini güçlendirmek.

---

## 9. Ek Not: Testlerin Durumu

- `RUN_LIVE_MCP_TESTS=1 ... -k metro_accessibility` → **geçti** (benim eklediğim araç canlıda çalışıyor) ✅
- `RUN_LIVE_MCP_TESTS=1` (tüm canlı testler) → **3 fail**:
  - `test_live_mcp_ferry_schedule_scope_is_explicit`
  - `test_live_mcp_nobetci_eczane_by_district_tool`
  - `test_live_mcp_nobetci_eczane_nearby_tool`
- Hepsinin sebebi: Railway'den kaynaklara erişim engeli (403 + timeout), kod hatası değil.

---

*Rapor, Exa MCP web araştırması ve Railway loglarının incelenmesiyle hazırlanmıştır.*
