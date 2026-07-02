import httpx
import pytest
import json

from app.connectors.http_retry import request_with_retries, retry_after_seconds
from app.connectors.iski import IskiClient
from app.connectors.ispark import IsparkClient
from app.connectors.metro import MetroClient
from app.connectors.traffic import TrafficClient


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


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

    snapshot = {"type": "FeatureCollection", "features": []}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://example.test/map",
            active_faults_snapshot_json=json.dumps(snapshot),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        faults = await iski.active_faults()

    assert faults == snapshot
    assert iski.last_faults_source == "snapshot"


@pytest.mark.asyncio
async def test_iski_dams_fall_back_to_configured_snapshot_after_api_timeout() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("source unavailable", request=request)

    snapshot = {"data": [{"kaynakAdi": "Omerli", "dolulukOrani": "89.16"}]}
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        iski = IskiClient(
            base_url="https://example.test/map",
            api_base_url="https://example.test/api",
            api_bearer_token="token",
            dams_snapshot_json=json.dumps(snapshot),
            attempts=1,
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        dams = await iski.dams()

    assert dams == [{"kaynakAdi": "Omerli", "dolulukOrani": "89.16"}]
    assert iski.last_dams_source == "snapshot"
