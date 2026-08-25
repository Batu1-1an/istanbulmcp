import httpx
import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.ferry import FerryScheduleService


class FakeFerryScheduleClient:
    schedule_index_url = "https://example.test/seferler"
    last_schedule_index_url = schedule_index_url

    def __init__(self, *, error: Exception | None = None, detail_error: Exception | None = None):
        self.error = error
        self.detail_error = detail_error
        self.catalog_calls = 0
        self.detail_calls = 0

    async def schedule_catalog(self):
        self.catalog_calls += 1
        if self.error:
            raise self.error
        return [
            {
                "route_label": "KADIKÖY - BEŞİKTAŞ",
                "detail_url": "https://example.test/detail/kadikoy-besiktas",
                "source_url": self.schedule_index_url,
            }
        ]

    async def schedule_for_route(self, detail_url, *, route_label):
        self.detail_calls += 1
        if self.detail_error:
            raise self.detail_error
        return [
            {
                "operator": "sehir_hatlari",
                "mode": "ferry",
                "route_label": "Kadıköy - Beşiktaş",
                "stop_name": "Kadıköy",
                "direction": "Beşiktaş",
                "day_type": "all_days",
                "planned_departure_time": "06:45",
                "stop_sequence": 1,
                "source_url": detail_url,
                "source_updated_at": None,
            },
            {
                "operator": "sehir_hatlari",
                "mode": "ferry",
                "route_label": "Kadıköy - Beşiktaş",
                "stop_name": "Kadıköy",
                "direction": "Beşiktaş",
                "day_type": "all_days",
                "planned_departure_time": "07:20",
                "stop_sequence": 1,
                "source_url": detail_url,
                "source_updated_at": None,
            },
        ]


def service(client):
    clear_source_cache()
    return FerryScheduleService(settings=Settings(), client=client)


@pytest.mark.asyncio
async def test_ferry_schedule_returns_static_rows_and_source_metadata():
    client = FakeFerryScheduleClient()
    result = await service(client).schedules(route="kadıköy - beşiktaş", limit=1)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["planned_departure_time"] == "06:45"
    assert result["freshness"]["ttl_seconds"] == 120
    assert {source["coverage_kind"] for source in result["sources"]} == {"published_timetable"}
    assert any("canlı" in warning and "ETA" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_ferry_schedule_route_miss_does_not_fetch_detail():
    client = FakeFerryScheduleClient()
    result = await service(client).schedules(route="Üsküdar - Eminönü")

    assert result["ok"] is True
    assert result["data"] == []
    assert client.detail_calls == 0


@pytest.mark.asyncio
async def test_ferry_schedule_invalid_route_is_rejected_before_network():
    client = FakeFerryScheduleClient()
    result = await service(client).schedules(route=" ")

    assert result["ok"] is False
    assert result["data"][0]["field"] == "route"
    assert client.catalog_calls == 0


@pytest.mark.asyncio
async def test_ferry_schedule_detail_failure_is_structured_and_not_fabricated():
    request = httpx.Request("GET", "https://example.test/detail")
    response = httpx.Response(403, request=request)
    client = FakeFerryScheduleClient(
        detail_error=httpx.HTTPStatusError("blocked", request=request, response=response)
    )
    result = await service(client).schedules(route="Kadıköy - Beşiktaş")

    assert result["ok"] is False
    assert result["data"] == []
    assert "HTTP 403" in result["warnings"][0]
    assert result["freshness"]["status"] == "unknown"
