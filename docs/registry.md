# MCP Registry yayını

`server.json`, resmî **2025-12-11** şemasına sabitlenmiş remote-only manifesttir.
Paket kurmaz; Streamable HTTP URL'ini tanımlar. Dosyanın mevcut olması registry
kaydı, directory kabulü veya remote sunucunun bu commit'i çalıştırdığı anlamına
gelmez. Gerçek yayın sonucu aşağıda ayrıca kaydedilmiştir.

## Doğrulanmış yayın — 2026-10-25

- Ad: `io.github.Batu1-1an/istanbul-mcp`
- Sürüm: **0.2.4**
- Durum: **active**, ilk doğrulamada `isLatest:true`
- Registry yayın zamanı: `2026-10-25T15:06:16.615963Z`
- Transport: `streamable-http`
- Remote URL: `https://istanbulmcp-production.up.railway.app/mcp/`
- [Sürüme özgü resmî kayıt](https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Batu1-1an%2Fistanbul-mcp/versions/0.2.4)

Kayıt, `mcp-publisher` **v1.8.4** ile yayımlandı. Yayından sonra Registry API'sinden
ad, sürüm, durum ve remote URL tekrar okundu. Yayın öncesi canlı sunucunun 0.2.4
çalıştırdığı ve 18 araç sunduğu doğrulandı. `search=istanbul&version=latest`
aramasında da kayıt görüldü. Bu, her şehir kaynağının o anda sağlıklı
olduğu, belediye onayı veya Claude/ChatGPT directory kabulü anlamına gelmez.

Bu çalışma dokümantasyon ve metadata yayınıdır; uygulama sürümü artırılmadı.
Kod lisansı seçilmediği için LICENSE eklenmedi ve lisans hakkı iddia edilmedi.
Şehir verilerinin koşulları ayrı değerlendirilir. [Sürüm geçmişi](../CHANGELOG.md).

## Yerel doğrulama

```bash
pytest tests/test_registry_metadata.py
python -m scripts.smoke_mcp
```

İlki vendored resmî şemayla offline manifest + public/legacy/optional tool
metadata'sını doğrular. İkincisi gerçek yerel subprocess üzerinden `tools/list`
`title` / `readOnlyHint` alanlarını ve iki protokol dönemini sınar. Canlı kaynak
API'lerini çağırmaz. Bu komutlar README'de de listelenir.

## Yayın öncesi

1. Yeni metadata'nın deploy edildiğini remote `tools/list` üzerinden doğrulayın.
2. Manifest sürümünü `pyproject.toml` ve MCP `serverInfo.version` ile eşleştirin;
   mevcut registry sürümüyle çakışma varsa sürümü açıkça artırın.
3. Namespace `io.github.Batu1-1an` için GitHub sahipliğini doğrulayın.
4. Resmî [publisher quickstart](https://modelcontextprotocol.io/registry/quickstart)
   ve [release](https://github.com/modelcontextprotocol/registry/releases/tag/v1.8.4)
   üzerinden sürümü sabitlenmiş `mcp-publisher` indirin. İndirilmiş script'i doğrudan
   çalıştırmayın. Bu yayında Linux amd64 arşivi, GitHub release metadata'sındaki
   SHA-256 değeriyle doğrulandı:
   `5dc2fd415369c73551259f31cd33e2aacc9e0d1021e7f08fef1492d93b781628`.
   Diğer mimariler için kendi arşivinin hash'ini kullanın.
5. Repo kökünde doğrulayın ve GitHub sahipliğiyle yayınlayın:

   ```bash
    mcp-publisher validate server.json
    mcp-publisher login github
    mcp-publisher publish server.json
   ```

6. Yayın sonucunu Registry'den ayrıca okuyup namespace, sürüm ve URL'i doğrulayın.
   Registry preview olduğundan şema/komutlar değişebilir. Örnek:

   ```bash
   curl -fsS 'https://registry.modelcontextprotocol.io/v0.1/servers/io.github.Batu1-1an%2Fistanbul-mcp/versions/0.2.4'
   ```

### Kimlik bilgileri

GitHub device-flow normal etkileşimli yoldur. CLI v1.8.4 ayrıca belgelenmiş
`MCP_GITHUB_TOKEN` ortam değişkeniyle GitHub kimliğini Registry token'ına çevirebilir.
Token'ları komut argümanına, loga, manifest dosyasına veya Git'e koymayın. Bu yayında
mevcut GitHub oturumu kullanıldı; yeni GitHub token'ı veya ek GitHub yetkisi oluşturulmadı. Registry token'ı
repo dışında, özel izinli geçici HOME altında tutuldu ve iş bitince `logout` ile kaldırıldı.
Normal CLI token konumu `~/.config/mcp-publisher/token.json`'dır.

Kaynaklar: [remote server rehberi](https://modelcontextprotocol.io/registry/remote-servers),
[resmî şema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json),
[MCP SDK 2.3 tool metadata](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/servers/tools.md).

## Directory ayrı bir süreçtir

Registry kaydı Claude connector directory başvurusu değildir. Her tool'da `title`
ve `readOnlyHint` sağlanır; tool açıklamaları yeteneği tarif eder. Eczane sunum
rehberi server instructions içinde korunur; kullanıcıya güvenlik/güncellik
uyarılarının gizlenmesi istenmez.

Başvuru için README'deki kurulum/örnekler, [veri işleme notu](privacy.md) ve destek
kanalı kullanılabilir. **İkon ve işletmeci gizlilik/saklama onayı henüz başvuru
engelleridir.** Bunları ve deploy'daki tüm tool'ların geçerli parametrelerle
çalıştığını doğrulamadan directory'ye hazır olunduğu iddia edilmemelidir.

Kontrol edilen kriterler (2026-10-23):
https://claude.com/docs/connectors/building/review-criteria

Registry belgeleri ve resmî yayıncı v1.8.4 `login` / `validate` / `publish`
davranışı 2026-10-25'te Context7, resmî belgeler, CLI yardımı ve auth kaynak koduyla
kontrol edildi. Yeni sürüm yayımlamadan önce mevcut kayıtla çakışmayı kontrol edin;
Registry yayını uygulamayı deploy etmez. Yalnız doküman değişikliği için yeni bir
Registry sürümü oluşturmayın.
