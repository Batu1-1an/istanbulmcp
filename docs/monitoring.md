# Araç bazlı izleme — 0.2.6

Mevcut `/status` yanıtındaki `tool_metrics.tools` her kayıtlı araç için bir satır
verir. Yeni MCP aracı eklenmez. Gizli eski araç adları da çalıştırılırsa ölçülür;
bilinmeyen adlar tek `__unknown__` satırında toplanır.

```bash
curl -fsS http://localhost:8000/status
pytest tests/test_tool_telemetry.py tests/test_source_cache.py
python -m scripts.smoke_mcp
```

Anahtarlı modda `/status` için de geçerli Bearer anahtarı gerekir. Anahtarı günlük,
issue veya komut çıktısında paylaşmayın. Herkese açık modda sayaçlar da herkese açıktır.

## Alanlar

| Alan | Anlamı |
|---|---|
| `calls`, `in_flight` | Başlayan ve henüz tamamlanmayan araç çağrıları |
| `duration_ms_total/mean/max` | Tamamlanan çağrıların sunucu tarafı süresi; p95 değil |
| `slow_calls` | En az 1000 ms süren çağrılar; hata/iptal süreleri de dahil |
| `outcomes.success` | MCP çalışması hata üretmedi ve okunabilen envelope `ok:false` değildi |
| `outcomes.domain_error` | Çalışan araç veri/kapsam/doğrulama hatasıyla `ok:false` döndürdü |
| `outcomes.tool_error/exception/cancelled` | SDK araç hatası, beklenmeyen hata veya iptal |
| `errors` | Sabit kategori sayıları; tanınmayan kod `other_error` |
| `returned_total` | Okunabilen envelope `data` liste uzunluklarının toplamı; hata satırları da dahil |
| `stale_responses` | Envelope tazeliği `stale` olan cevaplar |
| `partial_responses` | `checked` ve `unavailable` kaynakları birlikte taşıyan cevaplar |
| `last_*` | Son tamamlanan çağrının sonucu, süresi ve UTC zamanı |

HTTP 200 tek başına başarılı şehir verisi demek değildir. `domain_error`, stale
ve kısmi kaynak kapsamı ayrı izlenir. `success` veri doğruluğu/tamlığı garantisi
değildir. Yapısal envelope yoksa alanlar bilinmeyen kalır. Eski JSON metin
çıktıları en fazla 1.048.576 karaktere kadar incelenir; metin saklanmaz.

## Önbellek sayaçları

Yalnız ortak `SourceTTLCache` görünür. Veritabanı, connector içi başka cache'ler,
upstream ve CDN cache davranışı hakkında iddia içermez. Olaylar birbirini dışlamaz:

- `hit`: taze veri kullanıldı; bekleyen çağrı kilit sonrası hit alabilir.
- `miss`: ilk kontrolde taze veri yoktu veya snapshot peek kabul edilebilir veri bulamadı.
- `load`: kaynak yükleyici başlatıldı; başarılı indirme anlamına gelmez.
- `wait`: aynı cache anahtarının kilidi doluyken bekleme başladı.
- `error`: cache yükleme yolu hata üretti.
- `stale`: eski veri döndürüldü; yalnız snapshot peek de bunu artırabilir.

Bir çağrıda birden fazla kaynak kullanılabilir. Bu nedenle bunlar çağrı yüzdesi
değil olay sayılarıdır. Araç dışında çalışan warm-up/arka plan işlemleri hiçbir
araca yazılmaz; çağrı tamamlandıktan sonraki miras alınmış bağlam da kapatılır.

## Sınırlar ve gizlilik

Sayaçlar her sunucu örneğinde ayrıdır; restart/deploy ile sıfırlanır. Kalıcı zaman
serisi, alarm, trace, istemci bazlı ölçüm veya dashboard eklenmedi. Sabit araç ve
hata kategorileri bellek büyümesini sınırlar. Süre; araç çalışması, cache beklemesi
ve SDK dönüşümünü kapsar, ağ aktarımı veya HTTP auth/kota reddini kapsamaz.

Her tamamlanan çağrı `istanbul_mcp.tools` logger'ında `mcp_tool_call` adlı JSON
olayı üretir. Argüman, konum, sorgu, anahtar, cache anahtarı, ham cevap veya
exception mesajı içermez. SDK/ASGI/altyapı günlükleri ayrı kapsamdır; bunların
aynı gizlilik sözleşmesini taşıdığı iddia edilmez. [Gizlilik notu](privacy.md).
Log handler hatası asıl araç sonucunu veya hatasını değiştirmez.

Kontrol edilen SDK belgesi (2026-10-25): Context7
`/modelcontextprotocol/python-sdk/v2.3.0`,
[araç hata davranışı](https://github.com/modelcontextprotocol/python-sdk/blob/v2.3.0/docs/servers/handling-errors.md).
Sunucu tarafı override yolu ayrıca kurulu SDK kaynak kodu ve gerçek HTTP testleriyle doğrulandı.

Yerel doğrulama (2026-10-25): **1405 test geçti, 25 canlı test atlandı**.
Gerçek süreç smoke testi, üretim kaynağına gitmeden başarı/domain-error sayaçlarını
doğruladı. Gerçek süreç günlüğünde `mcp_tool_call` JSON olayı görüldü.
Sabitlenen resmî profildeki beş senaryonun tamamı geçti.

## Otomatik uptime izleme

[`.github/workflows/uptime.yml`](../.github/workflows/uptime.yml) canlı endpoint'i 10 dakikada bir `/healthz` ve gerçek bir MCP `initialize` + `tools/list` çağrısıyla kontrol eder; tek ağ aksaklığında alarm vermemek için 3 kez dener. Endpoint ulaşılamazsa repo sahibini etiketleyen tek bir `uptime-incident` issue'su açılır; servis düzelince issue'ya süre yazılıp kapatılır. Kesinti sürerken yeni issue açılmaz. GitHub zamanlanmış çalışmaları birkaç dakika geciktirebilir.

```bash
python -m scripts.uptime_check                     # production
python -m scripts.uptime_check --url http://127.0.0.1:8000
gh workflow run uptime.yml                          # elle tetikleme
```

Public repoda standart GitHub runner kullanımı ücretsizdir. Repo private yapılırsa her çalışma en az 1 dakika sayılır; 10 dakikalık aralık ücretsiz kotayı aşacağından aralığı 30 dakikaya çıkarın.

Event loop donarsa `EVENT_LOOP_WATCHDOG_SECONDS` (varsayılan 60) sonunda süreç tüm thread stack'lerini stderr'e yazıp `70` koduyla çıkar; Railway `ON_FAILURE` politikası servisi yeniden başlatır. Dökümü `railway logs` içinde `event_loop_stalled` ile arayın.
