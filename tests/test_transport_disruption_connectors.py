from pathlib import Path

import httpx
import pytest

from app.connectors.marmaray import MarmarayPayloadError, MarmarayClient
from app.connectors.metro import MetroClient, MetroPayloadError
from app.connectors.sehir_hatlari import SehirHatlariClient, SehirHatlariPayloadError


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


def fixture_text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def client_for(body: str, *, url: str = "https://example.test/source", status_code: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == url
        return httpx.Response(status_code, text=body, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def marmaray_api_client_for(
    page_body: str,
    api_body: str,
    *,
    page_url: str,
    api_url: str,
    status_code: int = 200,
):
    async def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == page_url:
            return httpx.Response(200, text=page_body, request=request)
        assert str(request.url) == api_url
        assert request.headers["authorization"] == "Basic test-token"
        return httpx.Response(status_code, text=api_body, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_metro_service_statuses_maps_modes_and_preserves_source_fields():
    body = fixture_text("metro/service_statuses.json")
    limiter = RecordingLimiter()

    async with client_for(body, url="https://example.test/metro/GetServiceStatuses") as http_client:
        client = MetroClient(
            base_url="https://example.test/metro",
            http_client=http_client,
            rate_limiter=limiter,
        )
        rows = await client.service_statuses()

    assert [row["mode"] for row in rows] == ["metro", "tram", "funicular", "cable_car"]
    assert rows[0]["event_type"] == "operational"
    assert rows[1]["event_type"] == "service_change"
    assert rows[1]["line_code"] == "T1"
    assert rows[1]["updated_at"] == "2026-08-25T10:15:00+03:00"
    assert limiter.acquired == ["metro"]


@pytest.mark.asyncio
async def test_metro_service_statuses_accepts_empty_data():
    async with client_for(
        fixture_text("metro/service_statuses_empty.json"),
        url="https://example.test/metro/GetServiceStatuses",
    ) as http_client:
        rows = await MetroClient(base_url="https://example.test/metro", http_client=http_client).service_statuses()

    assert rows == []


@pytest.mark.asyncio
async def test_metro_service_statuses_rejects_malformed_data():
    async with client_for(
        fixture_text("metro/service_statuses_malformed.json"),
        url="https://example.test/metro/GetServiceStatuses",
    ) as http_client:
        client = MetroClient(base_url="https://example.test/metro", http_client=http_client)

        with pytest.raises(MetroPayloadError, match="list"):
            await client.service_statuses()


@pytest.mark.asyncio
async def test_metro_service_statuses_keeps_duplicate_source_rows_for_service_deduplication():
    async with client_for(
        fixture_text("metro/service_statuses_duplicates.json"),
        url="https://example.test/metro/GetServiceStatuses",
    ) as http_client:
        rows = await MetroClient(base_url="https://example.test/metro", http_client=http_client).service_statuses()

    assert len(rows) == 2
    assert rows[0]["message"] == rows[1]["message"] == "Teknik arıza."


@pytest.mark.asyncio
async def test_sehir_hatlari_client_parses_active_notice_without_fabricating_fields():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        client = SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        rows = await client.cancellations()

    assert rows == [
        {
            "operator": "sehir_hatlari",
            "mode": "ferry",
            "line_code": "HAT1",
            "route_label": "Kadıköy - Beşiktaş",
            "event_type": "cancellation",
            "message": "Olumsuz hava koşulları nedeniyle sefer iptali.",
            "updated_at": "2026-08-25T09:00:00+03:00",
        }
    ]
@pytest.mark.asyncio
async def test_sehir_hatlari_client_accepts_explicit_empty_page():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations_empty.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        rows = await SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).cancellations()

    assert rows == []


@pytest.mark.asyncio
async def test_sehir_hatlari_client_rejects_changed_markup_and_keeps_unknown_source_visible():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations_changed.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        client = SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        with pytest.raises(SehirHatlariPayloadError, match="markup"):
            await client.cancellations()


@pytest.mark.asyncio
async def test_sehir_hatlari_client_does_not_invent_time_or_line_code():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations_duplicates.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        rows = await SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).cancellations()

    assert rows[0]["updated_at"] is None
    assert rows[0]["line_code"] == "HAT1"
    assert len(rows) == 2


@pytest.mark.asyncio
async def test_sehir_hatlari_client_parses_current_official_empty_notice_as_checked_empty():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations_official_empty.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        rows = await SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).cancellations()

    assert rows == []


@pytest.mark.asyncio
async def test_sehir_hatlari_client_preserves_current_official_global_notice_fields():
    async with client_for(
        fixture_text("sehir_hatlari/cancellations_official_active.html"),
        url="https://example.test/sehir/iptal-seferler",
    ) as http_client:
        rows = await SehirHatlariClient(
            url="https://example.test/sehir/iptal-seferler",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).cancellations()

    assert rows == [
        {
            "operator": "sehir_hatlari",
            "mode": "ferry",
            "line_code": None,
            "route_label": None,
            "event_type": "cancellation",
            "message": "Olumsuz hava koşulları nedeniyle bazı seferler iptal edilmiştir.",
            "updated_at": "25.08.2026",
        }
    ]


@pytest.mark.asyncio
async def test_sehir_hatlari_client_falls_back_to_official_page_after_relay_failure():
    relay_url = "https://relay.example/transport/sehir-hatlari"
    official_url = "https://example.test/sehir/iptal-seferler"
    calls: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((str(request.url), request.headers.get("authorization")))
        if str(request.url) == relay_url:
            return httpx.Response(502, request=request)
        assert str(request.url) == official_url
        return httpx.Response(
            200,
            text=fixture_text("sehir_hatlari/cancellations_official_empty.html"),
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        rows = await SehirHatlariClient(
            url=official_url,
            relay_url=relay_url,
            relay_token="relay-token",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).cancellations()

    assert rows == []
    assert calls[:3] == [(relay_url, "Bearer relay-token")] * 3
    assert calls[3:] == [(official_url, None)]


@pytest.mark.asyncio
async def test_marmaray_client_parses_active_notice():
    async with client_for(
        fixture_text("marmaray/urgent_notices.html"),
        url="https://example.test/marmaray/son-dakika",
    ) as http_client:
        rows = await MarmarayClient(
            url="https://example.test/marmaray/son-dakika",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).urgent_notices()

    assert rows[0]["operator"] == "marmaray"
    assert rows[0]["mode"] == "suburban_rail"
    assert rows[0]["line_code"] == "MARMARAY"
    assert rows[0]["route_label"] == "Gebze - Halkalı"
    assert rows[0]["event_type"] == "announcement"
    assert rows[0]["updated_at"] == "2026-08-25T11:00:00+03:00"


@pytest.mark.asyncio
async def test_marmaray_client_accepts_empty_page_and_rejects_changed_markup():
    async with client_for(
        fixture_text("marmaray/urgent_notices_empty.html"),
        url="https://example.test/marmaray/son-dakika",
    ) as http_client:
        rows = await MarmarayClient(
            url="https://example.test/marmaray/son-dakika",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).urgent_notices()
    assert rows == []

    async with client_for(
        fixture_text("marmaray/urgent_notices_changed.html"),
        url="https://example.test/marmaray/son-dakika",
    ) as http_client:
        client = MarmarayClient(
            url="https://example.test/marmaray/son-dakika",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MarmarayPayloadError, match="markup"):
            await client.urgent_notices()


@pytest.mark.asyncio
async def test_marmaray_client_reports_angular_shell_without_rendered_notices_as_unavailable():
    async with client_for(
        fixture_text("marmaray/angular_shell.html"),
        url="https://example.test/marmaray/son-dakika",
    ) as http_client:
        client = MarmarayClient(
            url="https://example.test/marmaray/son-dakika",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        with pytest.raises(MarmarayPayloadError, match="Angular shell"):
            await client.urgent_notices()


@pytest.mark.asyncio
async def test_marmaray_client_uses_official_api_when_page_is_angular_shell():
    page_url = "https://example.test/marmaray/son-dakika"
    api_url = "https://example.test/api/MainPages/GetAnnouncementsByDateAndCategoryIdMarmarayAsync/1?year=2026&categoryid=1&pageSize=100&offset=0"
    limiter = RecordingLimiter()
    async with marmaray_api_client_for(
        fixture_text("marmaray/angular_shell.html"),
        fixture_text("marmaray/urgent_notices_api_active.json"),
        page_url=page_url,
        api_url=api_url,
    ) as http_client:
        rows = await MarmarayClient(
            url=page_url,
            api_url="https://example.test/api",
            language_id=1,
            api_basic_token="test-token",
            http_client=http_client,
            rate_limiter=limiter,
        ).urgent_notices()

    assert rows == [
        {
            "operator": "marmaray",
            "mode": "suburban_rail",
            "line_code": None,
            "route_label": None,
            "event_type": "announcement",
            "message": "Marmaray seferlerinde gecikme duyurusu",
            "updated_at": "2026-08-25T10:30:00",
        }
    ]
    assert limiter.acquired == ["marmaray"]


@pytest.mark.asyncio
async def test_marmaray_client_accepts_official_api_empty_list():
    page_url = "https://example.test/marmaray/son-dakika"
    api_url = "https://example.test/api/MainPages/GetAnnouncementsByDateAndCategoryIdMarmarayAsync/1?year=2026&categoryid=1&pageSize=100&offset=0"
    async with marmaray_api_client_for(
        fixture_text("marmaray/angular_shell.html"),
        fixture_text("marmaray/urgent_notices_api_empty.json"),
        page_url=page_url,
        api_url=api_url,
    ) as http_client:
        rows = await MarmarayClient(
            url=page_url,
            api_url="https://example.test/api",
            api_basic_token="test-token",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).urgent_notices()

    assert rows == []


@pytest.mark.asyncio
async def test_marmaray_client_rejects_malformed_official_api_row():
    page_url = "https://example.test/marmaray/son-dakika"
    api_url = "https://example.test/api/MainPages/GetAnnouncementsByDateAndCategoryIdMarmarayAsync/1?year=2026&categoryid=1&pageSize=100&offset=0"
    async with marmaray_api_client_for(
        fixture_text("marmaray/angular_shell.html"),
        fixture_text("marmaray/urgent_notices_api_malformed.json"),
        page_url=page_url,
        api_url=api_url,
    ) as http_client:
        client = MarmarayClient(
            url=page_url,
            api_url="https://example.test/api",
            api_basic_token="test-token",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )

        with pytest.raises(MarmarayPayloadError, match="message"):
            await client.urgent_notices()


@pytest.mark.asyncio
async def test_marmaray_client_preserves_duplicate_rows_without_fabricating_fields():
    async with client_for(
        fixture_text("marmaray/urgent_notices_duplicates.html"),
        url="https://example.test/marmaray/son-dakika",
    ) as http_client:
        rows = await MarmarayClient(
            url="https://example.test/marmaray/son-dakika",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).urgent_notices()

    assert len(rows) == 2
    assert rows[0]["line_code"] == "MARMARAY"
    assert rows[0]["updated_at"] is None
