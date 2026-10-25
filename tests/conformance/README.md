# Seçilmiş resmî MCP uyumluluk testleri

Bu profil, gerçek `python -m app.main` sürecini geçici SQLite ve temiz ortamla
açar. Şehir API çağrısı, production anahtarı veya production adresi kullanmaz.
Üretime sahte örnek araç eklenmez. Root npm projesinden ayrıdır.

```bash
npm ci --prefix tests/conformance --ignore-scripts --no-audit --no-fund
python -m scripts.check_mcp_conformance
```

Python uygulama bağımlılıkları önceden kurulmalıdır. CI Node 22 ve Python 3.12
kullanır. Paket tam sürümü ve transitif bağımlılıklar lockfile ile sabitlenir.

Varsayılan çıktı `.artifacts/conformance/`; mevcut kanıtın üzerine yazılmaz.
Tekrar çalıştırırken başka boş çıktı dizini verin:

```bash
python -m scripts.check_mcp_conformance --output .artifacts/conformance-second
```

## Kapsam

`profile.json`: `@modelcontextprotocol/conformance@0.1.16` ile `server-initialize`,
`ping`, `tools-list`, `resources-list`, `prompts-list`. Bunlar yayımlanan uygulama
yüzeyine uygulanabilir, örnek fixture ismi istemeyen beş senaryodur.

**Tam resmî paket, sertifika veya 2026 protokol doğrulaması değildir.** Sabitlenen
paket 2025 dönemi protokolünü test eder. `main` dalındaki daha yeni alpha paketle
aynı değildir. Şehir verisi doğruluğu veya upstream servis sağlığı ölçülmez.

`tools-call-*`, resource-read ve prompt-get örnek senaryoları `test_simple_text`,
`test://static-text` gibi özel fixture'lar bekler. Bunlar bizim araç/URI adlarımız
değildir. Uygulamaya özel araç çağrısı, resource okuma, prompt render ve 2026 MCP
yolu kendi pytest ve gerçek süreç smoke testlerimizde ayrıca denetlenir.
OAuth, sampling, elicitation ve stateful session gibi isteğe bağlı yetenekler bu
salt okunur/stateless uygulama profilinin kapsamı dışındadır.

## Başarı koşulu ve kanıt

Her senaryo ayrı resmî CLI çağrısıdır. Hem sıfır çıkış kodu **hem** dolu
`checks.json` içindeki tüm kontrollerin `SUCCESS` olması gerekir. Eksik, bozuk,
boş, uyarılı veya başarısız rapor geçmez. Expected-failure baseline kullanılmaz.
Bir senaryo başarısız olsa bile diğerleri çalışır. Her çağrının bütçesi 60 saniyedir.

`summary.json`, senaryo raporları, tam `cli.log` ve sunucu günlüğü saklanır.
CI job'u zorunlu sonuç üretir, `continue-on-error` kullanmaz; artifact'lar hata
durumunda da 14 gün tutulur. Bunlar yalnız yerel, sahte olmayan uygulama
yüzeyinden gelen operasyon kanıtlarıdır.

Kontrol edilen resmî kaynaklar (2026-10-25):
- [Sabitlenen sürüm README](https://github.com/modelcontextprotocol/conformance/blob/v0.1.16/README.md)
- [Lifecycle](https://github.com/modelcontextprotocol/conformance/blob/v0.1.16/src/scenarios/server/lifecycle.ts),
  [tools](https://github.com/modelcontextprotocol/conformance/blob/v0.1.16/src/scenarios/server/tools.ts),
  [resources](https://github.com/modelcontextprotocol/conformance/blob/v0.1.16/src/scenarios/server/resources.ts),
  [prompts](https://github.com/modelcontextprotocol/conformance/blob/v0.1.16/src/scenarios/server/prompts.ts)
- Kurulu `0.1.16` paketinin `server --help` çıktısı ve gerçek çalıştırma raporları.
