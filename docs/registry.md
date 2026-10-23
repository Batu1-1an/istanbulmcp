# MCP Registry yayın hazırlığı

`server.json`, resmî **2025-12-11** şemasına sabitlenmiş remote-only manifesttir.
Paket kurmaz; Streamable HTTP URL'ini tanımlar. Dosyanın mevcut olması registry
kaydı, directory kabulü veya remote sunucunun bu commit'i çalıştırdığı anlamına
gelmez. Bu değişiklikle registry'ye yayın/deploy yapılmadı.

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
   üzerinden güncel `mcp-publisher` kurulumunu ve desteklenen komutları kontrol
   edin. CLI bu çalışma ortamında kurulu değildi. Kurulum için indirilmiş script'i
   incelemeden çalıştırmayın.
5. Hazır olunca, repo kökünde etkileşimli sahiplik onayıyla:

   ```bash
   mcp-publisher login github
   mcp-publisher publish
   ```

6. Yayın sonucunu Registry'den ayrıca okuyup namespace, sürüm ve URL'i doğrulayın.
   Registry preview olduğundan şema/komutlar değişebilir.

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
