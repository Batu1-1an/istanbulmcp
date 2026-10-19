# Kompakt MCP yüzeyine geçiş

Varsayılan yüzey 15 araçtır (14 konsolide araç + `istanbul_datastore_query`).
Bu bir MCP protokol sınırı değildir. Amaç, aynı yeteneğin birden fazla adla
sunulmasını azaltmaktır. Eski 30 araçtan yalnızca tarife kaynağı engellenen ferry
ayrı bir opt-in kapısı arkasındadır. Diğer yetenekler servislerini, envelope
alanlarını, kaynaklarını, tazelik ve hata davranışlarını korur.

## Eski → yeni

| Eski tool | Yeni çağrı |
|---|---|
| `istanbul_bbox_search` | `istanbul_nearby(bbox=[min_lon,min_lat,max_lon,max_lat], types=...)` |
| `istanbul_parking_nearby` | `istanbul_nearby(kind="parking", lat=..., lon=...)` |
| `istanbul_parking_by_district` | `istanbul_nearby(kind="parking", district="Kadıköy")` |
| `istanbul_nobetci_eczane_nearby` | `istanbul_nearby(kind="pharmacy", lat=..., lon=...)` |
| `istanbul_nobetci_eczane_by_district` | `istanbul_nearby(kind="pharmacy", district="Kadıköy")` |
| `istanbul_istanbulkart_centers_nearby` | `istanbul_nearby(kind="istanbulkart", lat=..., lon=...)` |
| `istanbul_sosyal_tesis_nearby` | `istanbul_nearby(kind="social_facility", lat=..., lon=...)` |
| `istanbul_metro_stations_nearby` | `istanbul_nearby(kind="metro_station", lat=..., lon=...)` |
| `istanbul_air_quality_nearby` | `istanbul_nearby(kind="air_quality", lat=..., lon=...)` |
| `istanbul_iski_nearby_faults` | `istanbul_nearby(kind="water_fault", lat=..., lon=...)` |
| `istanbul_iski_active_faults` | `istanbul_water_status(kind="faults", district=...)` |
| `istanbul_iski_fault_by_number` | `istanbul_water_status(kind="faults", fault_number=...)` |
| `istanbul_iski_dam_occupancy` | `istanbul_water_status(kind="dams", dam_name=..., min_occupancy=...)` |
| `istanbul_transit_line_info` | `istanbul_transit_line(line_code="34A", action="info")` |
| `istanbul_stops_for_line` | `istanbul_transit_line(line_code="34A", action="stops")` |
| `istanbul_planned_departures` | `istanbul_transit_line(line_code="34A", action="departures", limit=...)` |
| `istanbul_transit_disruptions` | `istanbul_transport_disruptions(operator="iett", line=...)` (birleşik kayıt şeması ve coverage metadata'sı) |

Mevcut `istanbul_nearby(lat,lon,types,...)` kullanımı korunur.
`kind` verilmezse `city_feature` seçilir. Bu mod hava istasyonu konumunu getirir;
**son okumalar** için `kind="air_quality"` kullanın. Bilinmeyen türler ve
birbirini dışlayan argümanlar sessizce yok sayılmaz.

## Uyumluluk modu

```bash
MCP_LEGACY_TOOLS_ENABLED=true python -m app.main
```

17 eski ad kompakt araçlara **ek olarak** yayımlanır (toplam 32; ferry açılırsa 33). İstemcilerin tool listesini
yeniden keşfetmesi gerekir. İptal-duyurusu relay ayarı ferry tarifesini açmaz;
`FERRY_SCHEDULES_ENABLED` ayrı ve varsayılan olarak kapalıdır.

## Ölçüm

`tests/fixtures/evals/city_questions.json` konsolidasyondan önce tanımlanan
20 Türkçe soru, eski/yeni çağrı, beklenen servis çağrısı ve fixture kayıtlarını içerir.
`pytest tests/test_tool_evals.py`, gerçek SDK/HTTP yolunda kompakt ve legacy
çağrıların fresh/stale/broken envelope'larını kayıpsız taşıdığını kontrol eder.

Bu bir **deterministik sözleşme eval'idir**, LLM'nin Türkçe sorudan doğru tool'u
seçtiği ölçülmez. `python -m scripts.eval_tools --predictions predictions.json`
ile dışarıdan alınan seçimler ayrı, exact-match olarak puanlanabilir.
Dosya biçimi: `{"parking-nearby":{"tool":"istanbul_nearby","arguments":{...}}}`.
Eksik tahminler başarısız sayılır.

`baseline_footprint.json` ferry kapatıldıktan sonra, konsolidasyondan önce
kaydedildi: 29 tool, 13.796 UTF-8 byte. Byte ölçüsü **token değildir**; SDK sürümü,
şemalar ve açıklamalarla değişir. Bir model çağrısı yapılmadan seçim başarısı
iyileşti iddiası kurulmaz.
