import httpx
import pytest
import json
from datetime import datetime, timezone

from app.connectors.http_retry import request_with_retries, retry_after_seconds
from app.connectors.iski import IskiClient, IskiPayloadError
from app.connectors.ispark import IsparkClient
from app.connectors.metro import MetroClient
from app.connectors.traffic import TrafficClient
from app.core.rate_limit import SourceRateLimitExceeded


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


class ExhaustingLimiter(RecordingLimiter):
    def __init__(self, allowed: int):
        super().__init__()
        self.allowed = allowed

    async def acquire(self, source: str) -> None:
        await super().acquire(source)
        if len(self.acquired) > self.allowed:
            raise SourceRateLimitExceeded(source=source, retry_after_seconds=1.0)


async def no_sleep(_delay: float) -> None:
    return None


def test_retry_after_seconds_defaults_and_clamps() -> None:
    assert retry_after_seconds(None) == 1.0
    assert retry_after_seconds("not-a-number") == 1.0
    assert retry_after_seconds("-2") == 0.0
    assert retry_after_seconds("2.5") == 2.5


@pytest.mark.asyncio
async def test_retry_helper_retries_transient_transport_failure() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("temporary timeout", request=request)
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await request_with_retries(
            http_client,
            "GET",
            "https://example.test/retry",
            attempts=2,
            sleep=no_sleep,
        )

    assert response.json() == {"ok": True}
    assert calls == 2


@pytest.mark.asyncio
async def test_retry_helper_penalizes_retry_after_on_429_then_retries() -> None:
    limiter = RecordingLimiter()
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"Retry-After": "3.25"})
        return httpx.Response(200, json={"ok": True})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        response = await request_with_retries(
            http_client,
            "GET",
            "https://example.test/rate-limited",
            attempts=2,
            rate_limiter=limiter,
            sleep=no_sleep,
        )

    assert response.status_code == 200
    assert calls == 2
    assert limiter.penalties == [3.25]


@pytest.mark.asyncio
async def test_standardized_connectors_accept_injected_clients_and_limiters() -> None:
    limiter = RecordingLimiter()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/Park"):
            return httpx.Response(200, json=[{"parkName": "Moda Otopark"}])
        if request.url.path.endswith("/GetStations"):
            return httpx.Response(200, json={"Data": [{"Description": "Kadikoy"}]})
        if "/TrafficIndexHistory/1/" in request.url.path:
            return httpx.Response(200, text='[{"TrafficIndex":63}]')
        if request.url.path.endswith("/mahallelerKesinti.geojson"):
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        if request.url.path.endswith("/baraj.json"):
            return httpx.Response(200, json={"data": [{"kaynakAdi": "Alibey", "dolulukOrani": "59.44"}]})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        ispark = IsparkClient(
            base_url="https://example.test/ispark",
            http_client=http_client,
            rate_limiter=limiter,
        )
        metro = MetroClient(
            base_url="https://example.test/metro",
            http_client=http_client,
            rate_limiter=limiter,
        )
        traffic = TrafficClient(
            base_url="https://example.test/traffic",
            http_client=http_client,
            rate_limiter=limiter,
        )
        iski = IskiClient(
            base_url="https://example.test/iski",
            http_client=http_client,
            rate_limiter=limiter,
        )

        parks = await ispark.parks()
        stations = await metro.stations()
        history = await traffic.index_history()
        faults = await iski.active_faults()
        dams = await iski.dams()

    assert parks == [{"parkName": "Moda Otopark"}]
    assert stations == [{"Description": "Kadikoy"}]
    assert history == [{"TrafficIndex": 63}]
    assert faults["type"] == "FeatureCollection"
    assert dams == [{"kaynakAdi": "Alibey", "dolulukOrani": "59.44"}]
    assert limiter.acquired == ["ispark", "metro", "traffic", "iski", "iski"]


@pytest.mark.asyncio
async def test_retry_helper_raises_final_retryable_status_after_attempt_cap() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(503, text="temporarily unavailable")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await request_with_retries(
                http_client,
                "GET",
                "https://example.test/unavailable",
                attempts=3,
                sleep=no_sleep,
            )

    assert calls == 3
    assert exc_info.value.response.status_code == 503


@pytest.mark.asyncio
async def test_iski_dams_fall_back_to_official_api_when_map_source_times_out() -> None:
    limiter = RecordingLimiter()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/baraj.json"):
            raise httpx.ConnectTimeout("map source unavailable", request=request)
        if request.url.path.endswith("/iski/baraj/listesi/v2"):
            assert request.headers["authorization"] == "Bearer token"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "kaynakAdi": "Omerli",
                            "baslikAdi": "Ömerli",
                            "dolulukOrani": "89.16",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://example.test/map",
            api_base_url="https://example.test/api",
            api_bearer_token="token",
            attempts=1,
            http_client=http_client,
            rate_limiter=limiter,
        )

        dams = await iski.dams()

    assert dams == [{"kaynakAdi": "Omerli", "baslikAdi": "Ömerli", "dolulukOrani": "89.16"}]
    assert limiter.acquired == ["iski", "iski"]


@pytest.mark.asyncio
async def test_iski_active_faults_fall_back_to_configured_snapshot() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("map source unavailable", request=request)

    snapshot = {
        "captured_at": "2026-07-23T10:30:00Z",
        "payload": {"type": "FeatureCollection", "features": []},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://example.test/map",
            active_faults_snapshot_json=json.dumps(snapshot),
            now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        faults = await iski.active_faults()

    assert faults == snapshot["payload"]
    assert iski.last_faults_source == "snapshot"


@pytest.mark.asyncio
async def test_iski_dams_fall_back_to_configured_snapshot_after_api_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("source unavailable", request=request)

    snapshot = {
        "captured_at": "2026-07-23T10:30:00Z",
        "payload": {"data": [{"kaynakAdi": "Omerli", "dolulukOrani": "89.16"}]},
    }
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://example.test/map",
            api_base_url="https://example.test/api",
            api_bearer_token="token",
            dams_snapshot_json=json.dumps(snapshot),
            now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        dams = await iski.dams()

    assert dams == [{"kaynakAdi": "Omerli", "dolulukOrani": "89.16"}]
    assert iski.last_dams_source == "snapshot"


@pytest.mark.asyncio
async def test_iski_active_faults_prefer_authenticated_relay() -> None:
    calls: list[str] = []
    payload = {"type": "FeatureCollection", "features": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        assert request.headers["authorization"] == "Bearer relay-secret"
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == payload
    assert calls == ["https://relay.example/iski/faults"]
    assert iski.last_faults_source == "relay_geojson"


@pytest.mark.asyncio
async def test_iski_active_faults_preserve_edevlet_relay_provenance() -> None:
    payload = {"type": "FeatureCollection", "relay_source": "edevlet", "features": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == payload
    assert iski.last_faults_source == "relay_edevlet"


@pytest.mark.asyncio
async def test_iski_preserves_stale_relay_cache_metadata() -> None:
    payload = {
        "type": "FeatureCollection",
        "relay_source": "edevlet",
        "relay_cache_status": "stale",
        "relay_cached_at": "2026-07-23T10:30:00Z",
        "features": [],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        await iski.active_faults()

    assert iski.last_faults_source_updated_at == "2026-07-23T10:30:00Z"
    assert iski.last_faults_source_stale is True


@pytest.mark.asyncio
async def test_iski_dams_preserve_edevlet_relay_provenance() -> None:
    payload = {
        "relay_source": "edevlet",
        "data": [{"kaynakAdi": "Omerli", "biriktirmeHacmi": 244.54, "dolulukOrani": 80.68}],
    }

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        dams = await iski.dams()

    assert dams == payload["data"]
    assert iski.last_dams_source == "relay_edevlet"


@pytest.mark.asyncio
async def test_iski_active_faults_use_direct_source_after_relay_failure() -> None:
    calls: list[str] = []
    payload = {"type": "FeatureCollection", "features": []}

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.host)
        if request.url.host == "relay.example":
            return httpx.Response(502)
        return httpx.Response(200, json=payload)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == payload
    assert calls == ["relay.example", "direct.example"]
    assert iski.last_faults_source == "live_geojson"


@pytest.mark.asyncio
async def test_iski_active_faults_fall_back_when_relay_payload_is_invalid() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "relay.example":
            return httpx.Response(200, json={"unexpected": True})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == {"type": "FeatureCollection", "features": []}
    assert iski.last_faults_source == "live_geojson"


@pytest.mark.asyncio
async def test_iski_active_faults_fall_back_when_relay_feature_is_invalid() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "relay.example":
            return httpx.Response(200, json={"type": "FeatureCollection", "features": [None]})
        return httpx.Response(200, json={"type": "FeatureCollection", "features": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == {"type": "FeatureCollection", "features": []}
    assert iski.last_faults_source == "live_geojson"


@pytest.mark.asyncio
async def test_iski_dams_fall_back_when_relay_row_is_invalid() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "relay.example":
            return httpx.Response(200, json={"data": ["invalid"]})
        return httpx.Response(200, json={"data": []})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        dams = await iski.dams()

    assert dams == []
    assert iski.last_dams_source == "live_json"


@pytest.mark.asyncio
async def test_iski_active_faults_use_official_api_after_geojson_failure() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "direct.example":
            raise httpx.ConnectTimeout("map unavailable", request=request)
        if request.url.path.endswith("/bolgeselAriza/listesi"):
            return httpx.Response(200, json={"data": [{"ilceKodu": "IL", "ilceAdi": "Bağcılar"}]})
        if request.url.path.endswith("/bolgeselAriza/arizaDetayi"):
            assert request.method == "POST"
            assert request.url.params["ilceKodu"] == "IL"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "arizaNo": "100",
                            "ilceKodu": "IL",
                            "ilceAdi": "BAĞCILAR",
                            "mahalleKodu": "117",
                            "mahalleAdi": "DEMİRKAPI MAH",
                            "arizaNeviAciklamasi": "BAKIM",
                            "baslamaTarihi": "23/07/2026",
                            "tahminiBitisTarihi": "23/07/2026 20:00:00",
                        }
                    ]
                },
            )
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            api_base_url="https://api.example/api",
            api_bearer_token="api-secret",
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults["features"][0]["properties"]["ARIZA_NO"] == "100"
    assert faults["features"][0]["geometry"] is None
    assert iski.last_faults_source == "official_api"


@pytest.mark.asyncio
async def test_iski_rate_limited_official_fault_api_still_uses_snapshot() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "direct.example":
            raise httpx.ConnectTimeout("map unavailable", request=request)
        if request.url.path.endswith("/bolgeselAriza/listesi"):
            return httpx.Response(200, json={"data": [{"ilceKodu": "IL"}]})
        return httpx.Response(500)

    payload = {"type": "FeatureCollection", "features": []}
    snapshot = json.dumps({"captured_at": "2026-07-23T10:30:00Z", "payload": payload})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            api_base_url="https://api.example/api",
            api_bearer_token="api-secret",
            active_faults_snapshot_json=snapshot,
            now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            attempts=1,
            http_client=http_client,
            rate_limiter=ExhaustingLimiter(allowed=2),
        )
        faults = await iski.active_faults()

    assert faults == payload
    assert iski.last_faults_source == "snapshot"


@pytest.mark.asyncio
async def test_iski_accepts_timestamped_snapshot_within_age_limit() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("source unavailable", request=request)

    payload = {"type": "FeatureCollection", "features": []}
    snapshot = json.dumps({"captured_at": "2026-07-23T10:30:00Z", "payload": payload})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            active_faults_snapshot_json=snapshot,
            faults_snapshot_max_age_seconds=3600,
            now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        faults = await iski.active_faults()

    assert faults == payload
    assert iski.last_faults_source == "snapshot"
    assert iski.last_faults_source_updated_at == "2026-07-23T10:30:00+00:00"


@pytest.mark.asyncio
async def test_iski_rejects_expired_or_undated_snapshots() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("source unavailable", request=request)

    payload = {"type": "FeatureCollection", "features": []}
    expired = json.dumps({"captured_at": "2026-07-23T08:00:00Z", "payload": payload})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        for snapshot in (expired, json.dumps(payload)):
            iski = IskiClient(
                base_url="https://direct.example",
                active_faults_snapshot_json=snapshot,
                faults_snapshot_max_age_seconds=3600,
                now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
                attempts=1,
                http_client=http_client,
                rate_limiter=RecordingLimiter(),
            )
            with pytest.raises(IskiPayloadError):
                await iski.active_faults()


@pytest.mark.asyncio
async def test_iski_failure_logs_do_not_expose_tokens(caplog) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("source unavailable", request=request)

    payload = {"type": "FeatureCollection", "features": []}
    snapshot = json.dumps({"captured_at": "2026-07-23T10:30:00Z", "payload": payload})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://direct.example",
            relay_base_url="https://relay.example",
            relay_token="relay-secret",
            active_faults_snapshot_json=snapshot,
            now=lambda: datetime(2026, 7, 23, 11, 0, tzinfo=timezone.utc),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with caplog.at_level("WARNING", logger="istanbul_mcp.connectors.iski"):
            await iski.active_faults()

    records = [json.loads(record.message) for record in caplog.records]
    assert records
    assert all(set(record) == {"event", "source", "duration_ms", "error_type"} for record in records)
    assert "relay-secret" not in caplog.text
