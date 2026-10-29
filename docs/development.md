# Geliştirme ve doğrulama

Temel kurulum ve tam test paketi için [README](../README.md#geliştirme) yeterlidir. Bu sayfa odaklı test komutlarını ve opt-in canlı kontrolleri toplar.

## Odaklı test komutları

```bash
python -m pip check
# SDK/protokol, yerel discovery ve output schema sözleşmeleri
pytest tests/test_mcp_protocol.py tests/test_mcp_discovery.py tests/test_mcp_structured.py
# İsteğe bağlı anahtarlı mod; değeri terminale yazdırmadan üretin:
export MCP_API_KEYS="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
# 20 soru × fresh/stale/broken × compact/legacy dispatch ve envelope sözleşmesi
pytest tests/test_tool_evals.py
# Tool tanımları, output schema ek maliyeti ve resource/prompt sayıları (byte, token değil)
python -m scripts.eval_tools
# GTFS kaynak/CSV/byte-row-timeout/stale ve gerçek registry regresyonları (offline)
pytest tests/test_gtfs.py tests/test_gtfs_regression.py tests/test_city_service.py tests/test_ckan_bounded.py
# Tam GTFS tarife ZIP, takvim/geceyarısı, bütçe/rollback ve opt-in MCP testleri
pytest tests/test_gtfs_schedule.py
# Ortak hata/kesilme sözleşmesi, durak metadata'sı ve yerel tarife sağlığı
pytest tests/test_response_contract.py tests/test_gtfs_snapshot_status.py
# EV/taksi/pazar/kültür statik katmanları ve pazar takvimi
pytest tests/test_city_open_data.py tests/test_city_service.py
# Resmî pinned registry şeması ve tüm tool yüzeylerinde title/readOnlyHint
pytest tests/test_registry_metadata.py
# SQL güvenlik/tamlık ve bounded HTTP testleri
pytest tests/test_guarded_sql.py tests/test_datastore_sql.py tests/test_ckan_bounded.py
# Araç telemetrisi ve resmî MCP conformance senaryoları
pytest tests/test_tool_telemetry.py tests/test_conformance_runner.py
npm ci --prefix tests/conformance --ignore-scripts --no-audit --no-fund
python -m scripts.check_mcp_conformance
# Tarayıcı CORS, API anahtarı ve kötüye kullanım korumaları
pytest tests/test_cors.py tests/test_api_auth.py tests/test_abuse_guard.py
# Event loop watchdog ve uptime kontrol betiği
pytest tests/test_loop_watchdog.py tests/test_uptime_check.py
# Dış kaynağa bağlanmadan gerçek yerel süreç + auth/kota/restart smoke testi
python -m scripts.smoke_mcp
```

Conformance kapsamı ve raporları: [tests/conformance/README.md](../tests/conformance/README.md). Bu seçilmiş 2025 dönemi profilidir; tam sertifika veya 2026 protokol testi değildir.

## Python ve container doğrulaması

Minimum Python sürümünü temiz ortamda doğrulamak için (opsiyonel `uv`):

```bash
uv run --isolated --no-project --python 3.11 --with-editable '.[dev]' python -m pytest
```

Container kurulumunu doğrulamak için:

```bash
docker build -t istanbul-mcp:local .
```

Python 3.11/3.12, gerçek süreç ve container doğrulama sonuçları [MCP arayüzü belgesinde](mcp-interface.md#6-doğrulama) kayıtlıdır.

## Opt-in canlı testler

Bu komutlar gerçek kaynaklara bağlanır; yalnız kaynaklara erişebilen ortamda çalıştırın.

```bash
RUN_LIVE_MCP_TESTS=1 pytest tests/live
python scripts/live_mcp_uat.py
# Ayrı opt-in: yerel ASGI MCP + gerçek GTFS kaynağı; geçici DB, deploy yok
RUN_LIVE_GTFS_TESTS=1 pytest -s tests/live/test_gtfs_source_live.py
# Tam GTFS ZIP indirir (opt-in; geçici DB kullanır)
RUN_LIVE_GTFS_SCHEDULE_TESTS=1 pytest -s tests/live/test_gtfs_schedule_source_live.py
```
