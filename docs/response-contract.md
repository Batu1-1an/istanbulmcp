# Ortak hata ve sonuç sözleşmesi — 0.2.4

Değişiklikler ek alanlardır. Mevcut `ok`, `data`, `warnings`, `pagination`, kaynak ve
tazelik alanları korunur. `data[].error_code` kullanan eski istemciler çalışmaya devam eder.
SQL aracı, sorgu motoru ve allowlist değiştirilmedi; ortak zarfın ek alanları onun
yanıtlarında da görülebilir. SQL sonucu için yeni bir toplam veya sayfalama garantisi yoktur.

## Hata

Başarıda `error:null`; standart hata zarfında:

```json
{
  "code": "warming_up",
  "temporary": true,
  "retry_after_ms": 60000,
  "field": null,
  "repair": {
    "next_step": "Check snapshot status again after warm-up.",
    "tool": "istanbul_gtfs_snapshot_status",
    "arguments": {}
  }
}
```

- `code`: eski hata kodu varsa korunur. Yaygın kodlar `validation_error`, `not_found`,
  `source_unavailable`, `source_rate_limited`, `source_timeout`, `warming_up`,
  `feature_disabled`, `snapshot_unavailable`, `outside_calendar`.
- Sınıflandırılmamış hata `request_failed` olur; uyarı metninden kod tahmin edilmez.
- `temporary:true`, tekrar denemenin anlamlı olabileceğini söyler; başarı garantisi değildir.
- `retry_after_ms` yalnız bilinen, sonlu ve negatif olmayan gecikmeler için verilir.
  Eski `retry_after_seconds` alanı varsa korunur. Kalıcı hatalarda gecikme `null` kalır.
- `repair.tool` / `arguments` yalnız somut ve geçerli bir sonraki çağrı biliniyorsa doludur.
  Örneğin bilinmeyen kaynak kolonu için `istanbul_get_resource_schema(resource_id=...)`.
  Aksi halde yalnız `next_step` metni bulunur. Gizli exception metni eklenmez.
- SDK'nin şema dışı argüman/protokol hataları MCP hatasıdır; bu domain zarfı değildir.

## Sonuçların kesilmesi

```json
{
  "returned": 1,
  "matched": 27,
  "truncated": true,
  "scope": "stop_name_matches",
  "next_step": "Increase limit within the advertised maximum or narrow the filters. This is not a complete total."
}
```

- `returned`: belirtilen kapsamda döndürülen kayıt sayısı.
- `matched`: yalnız bilinen tam eşleşme sayısı; bilinmiyorsa `null`.
- `truncated:true`: limit nedeniyle kayıt bırakıldı. `false`: belirtilen sonuç
  kapsamında limit nedeniyle kayıt bırakılmadı. `null`: tamamlık bilinmiyor.
- `scope`: sayımın kapsamı. Örneğin `next_24_hours_at_selected_stops` yalnız seçilen
  en fazla beş durağı kapsar; İstanbul'un tüm seferleri değildir.
- `matched` ve `truncated`, kaynak kapsamı/sağlığı ile aynı şey değildir. Kısmi kaynak
  kapsamındaki kayıtlar kesilmemiş olsa bile diğer kaynaklarda veri olabilir.
- Kaynak toplamı zaten biliniyorsa kullanılır. Coğrafi sorgular ve kalkışlarda sınırlı
  bir ek adayla kesilme belirlenebilir; bu durumda tam `matched` sayısı bilinmeyebilir.
- Toplam yalnız tahminse `pagination.total_estimate` içinde kalır, kesin `matched` olmaz.
- Aracın kabul etmediği `offset` veya cursor önerilmez. Limit üst sınırına ulaşıldıysa
  filtreyi daraltın. Bu değişiklik yeni sayfalama parametresi eklemez.
- Bileşik ulaşım/şehir-hizmeti yanıtlarında `data[0].result_info` bölüm adlarından
  sayım bilgisine eşler. Metro ekipman sonucunda iç `result_info.scope=faults` olur.
  Üst düzey bir özet satırı, iç listelerin tam olduğunu göstermez.
- Hata verisinin sayım kapsamı `error_details` olur; boş hata verisi boş şehir sonucu değildir.

`istanbul://schema/catalog`, güncel `ResponseEnvelope` şemasını sunar. Şemalı araçlarda
JSON metni ve `structuredContent` aynı alanları taşır.

## Doğrulama

```bash
pytest tests/test_response_contract.py tests/test_gtfs_snapshot_status.py
pytest
python -m scripts.smoke_mcp
```

GTFS fixture'ları canlı kaynağa erişmeden metadata, migration/rollback, takvim,
stale süresi, snapshot değişimi, kesilme ve iki MCP protokolünü kontrol eder.

Kontrol edilen güncel belge: Context7 `/modelcontextprotocol/python-sdk/v2.3.0`,
[Tools ve structured output](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/servers/tools.md).
