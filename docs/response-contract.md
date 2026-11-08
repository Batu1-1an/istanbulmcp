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

## Kaynak linkleri

- `sources[].url` yalnız insanların okuyabileceği bir sayfadır (ör. Şehir Hatları duyuru
  sayfası, İBB Açık Veri dataset sayfası, e-Devlet). Kullanıcı cevabında link olarak
  verilebilecek tek kaynak alanı budur.
- API uçları (`api.*`, `*api.*`, `*proxy.*` host'ları, `/api/` veya `/download/` yolları),
  ham veri dosyaları (`.json`, `.geojson`, `.csv`, `.zip`, `.xls(x)`, `.xml`, `.asmx`),
  HTTPS olmayan adresler `null` döner. Kural `Source` serileştirmesinde uygulanır; yeni
  kaynaklar da otomatik kapsanır. Özel relay adresleri kaynak URL'i olarak hiç yazılmaz.
- `url:null`, kaynağın bilinmediği anlamına gelmez. `name`, `publisher`, `dataset_id`,
  `resource_id` ve `freshness` korunur; cevapta kaynak yayıncı adıyla ("İBB verisi") anılır.

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

## Optional event results

Event tools retain the same ResponseEnvelope, including list-valued data.
Search data contains session cards. Detail data contains one object with
performances and observed offers. Plan data contains one object with options,
unverified_budget and rejection reasons; result_info.scope=data.options counts
plan options rather than the enclosing data object. Unknown prices/availability
are explicit. Provider ticket_links retain separate availability observations.
See [events](events.md) for limits, timing and source semantics.

Event cards in 0.4.0 additionally expose `age_limit`, `duration_minutes`,
`end_source` and `distance_kind=straight_line`. Price includes the observed ticket
type and eligibility uncertainty; catalogue hints never populate the price.
Detail may include requested_performance_id, selected_performance_ids and
selection_status for exact session selection. Plan echoes requested_categories,
child_age and require_known_end. Existing tool names and envelope remain callable.

In 0.4.1, client presentation guidance requires a clickable event/ticket-page
link beside each presented event title in search, detail and plans. Use the
existing ticket_url or non-null ticket_links[].url exactly as returned; a missing
link stays explicitly unavailable. These are event destinations, separate from
sources[].url citations and calendar links. No result schema or tool name changes.

In 0.5.0 event cards add category_source=provider|title_marker|unknown.
Source metadata adds optional refresh_status=idle|refreshing|failed|unavailable
and serving_stale; other source domains may leave these null. Event fallback
after refresh failure is explicitly stale, even if its snapshot TTL has not expired.
Plan options add total_observed_minimum_try: null if any session price is unknown,
otherwise the sum of observed minima. The old known_minimum_total_try still
contains a partial subtotal when total_price_known=false. Tool names and
list-valued data shapes are preserved; search's default is now complete words.

0.6.0 adds optional result_info.filter_counts (event search only; null elsewhere).
Counters describe sequential filtering of a bounded index and are not city totals.
Search accepts include_past=false by default. Detail may return catalogue_retired
with retained inactive local evidence or source_unavailable for active but unusable
source data; not_found without retained history does not establish cancellation.
See [free search and lifecycle semantics](events-free-lifecycle.md).
