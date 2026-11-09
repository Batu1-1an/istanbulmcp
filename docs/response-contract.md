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

0.8.0 cards add optional admission_window (opens_at, last_entry_at, closes_at,
HH:MM Europe/Istanbul), excluded_weekdays (Monday=0..Sunday=6), and
entry_date_restricted. These are source facts, not a chosen visit time or proof
of full admission eligibility. Discovery excludes explicitly prohibited dates
with filter_counts.excluded_entry_date. Detail keeps restricted records for
inspection; selected plans reject them with entry_date_restricted, and calendars
omit them. Plan checks adds age_compatibility=published_ranges_compatible|
partially_known|unknown and common_published_age_range={minimum,maximum} or null.
An unbounded published maximum is null; missing evidence never means all ages.
age_incompatible_combinations counts candidate combinations with no shared age,
not individual sessions or city totals. A common source range is not proof of
the user's age, accompaniment conditions or ticket eligibility.

In 0.7.0 cards add `timing_kind=scheduled|flexible_entry`, `event_date` and
`source_start_at`. Scheduled sessions retain their ISO start_at. Explicitly
flexible-entry tickets have start_at=null, end_at=null, end_known=false;
event_date is a listed ticket date, not a guaranteed admission date or opening
hour. source_start_at, when present, is the observed source timestamp only.
Clients must not use it as a visit time. start_time_basis may be html_date.
Search clock filters exclude flexible tickets (excluded_unverified_time);
date searches keep them throughout their listed date. Plan data includes
flexible_entries (max 20), flexible_entry_count and flexible_entries_truncated.
These tickets have no timed option/calendar entry; rejected reason
flexible_entry_requires_visit_time explains the required source verification.
result_info.scope=data.options still counts only timed options.

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

0.6.1 event cards add `start_time_basis=provider_datetime|html_session|json_ld`,
`source_time_conflict` and per-card `warnings`. When a Biletinial JSON-LD offset
disagrees with an explicitly matching HTML date/time and venue, start_at uses the
published Istanbul HTML session; the conflicting JSON end is discarded. A real
UTC instant matching an HTML session still keeps its normal converted time.
Search and plan warnings also explain conditional ticket minima, which are not
guaranteed per-person general-admission prices.

`exclude_child_only=true` ile arama sayacı
`result_info.filter_counts.excluded_child_only`, açık üst yaşı 18 altı
kayıtların elendiğini gösterir. Seçili planda `rejected[].reason`
`child_only_age_range` olabilir. Bilinmeyen yaşlar uygun diye işaretlenmez;
uyarı alanı, bu dar elemenin gerçek katılımcı uygunluğu onayı olmadığını açıklar.

### Etkinlik karar kalitesi — 0.9.2

- result_info.empty_reasons ve coverage, sıralı eleme/kapsam nedenlerini taşır.
  excluded_unknown_location + excluded_outside_location = excluded_location.
  Mekân tamamlama kökeni venue.field_evidence içinde açıkça belirtilir.
- price.minimum_observed_try ham tek teklif minimumudur. price.unit ve
  general_admission_quote bunun kişi/grup tutarı sayılmasını önler. Yeni
  price_quote; party, basket adetleri, gözlenen ara toplam, bilinmeyen ücret ve
  stok/yan yana koltuk doğrulanmadı alanlarını içerir. budget_price_basis ve
  plandaki total_price_scope, max_price_try'nin neye uygulandığını belirtir.
- budget_lower_bound_try ve price_quote.observed_lower_bound_try, kişi birimi
  veya hizmet bedeli bilinmese de gözlenen fiyat alt sınırını korur. Bu sınır
  bütçeyi aşıyorsa include_unknown_prices=true kaydı geri getirmez; pozitif alt
  sınır free_only için uygun değildir. Plan alt sınırları birlikte toplar.
- participation_conditions: inspected/unknown/expired, source_observed_at,
  bounded statements, provenance, truncated ve unverified_topics. Bunlar
  yayımlanmış kaynak ifadeleri, kişisel veya hukuki uygunluk onayı değildir.
- Plan options ile unverified_budget yalnız durak/tür koşullarını karşılayan
  seçeneklerdir. partial_options eksik durak/türleri gösterir; takvim içermez.
  fulfillment ve reason_codes ile discovery/combination_diagnostics korunur.

Ayrıntı: [karar kalitesi](events-decision-quality.md). Eski araçlar ve varsayılan
min_events=1 korunur; yeni sayısal/profil girişleri sınırlandırılır.

### Etkinlik konusu — 0.9.3

Her etkinlik kartının `about` nesnesi: `text` (string/null, en fazla 500 karakter),
`status` (available/not_checked/not_published), `kind=source_excerpt`, `truncated`,
`source_url`, `observed_at`, `is_untrusted_source_text=true`. Kaynak alıntısıdır;
özgün özet veya katılım uygunluğu kararı değildir. Arama, detayın performances
listesi ve planın tüm performans kartlarında aynı sözleşme kullanılır. Detayın
mevcut 1.200 karakterlik `description` alanı korunur. Kaynak metni eksikse konu
başlıktan/kategoriden türetilmez. [Ayrıntı](events.md#etkinliğin-konusu--093).
