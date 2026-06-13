import pytest
import asyncio

from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.transit import TransitService
from app.storage.geo import GeoRepository


class FakeIett:
    def __init__(self):
        self.line_info_calls = 0
        self.stops_for_line_calls = 0

    async def line_info(self, line_code):
        self.line_info_calls += 1
        return [{"SHATKODU": line_code, "SHATADI": "A - B", "TARIFE": "TEST"}]

    async def stops_for_line(self, line_code):
        self.stops_for_line_calls += 1
        return [
            {
                "HATKODU": line_code,
                "YON": "D",
                "YON_ADI": " B ",
                "SIRANO": "1",
                "DURAKKODU": "100",
                "DURAKADI": "Stop",
                "XKOORDINATI": "29.0",
                "YKOORDINATI": "41.0",
                "DURAKTIPI": "DURAK",
                "ILCEADI": "Test",
            }
        ]


class FailingIett:
    async def line_info(self, line_code):
        raise RuntimeError("down")

    async def stops_for_line(self, line_code):
        raise RuntimeError("down")


class RateLimitedIett:
    async def line_info(self, _line_code):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)

    async def stops_for_line(self, _line_code):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)


def service(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    return TransitService(
        settings=settings,
        iett_client=FakeIett(),
        geo_repository=GeoRepository(settings.database_path),
    )


@pytest.mark.asyncio
async def test_line_info_returns_envelope(tmp_path):
    result = await service(tmp_path).line_info("34A")

    assert result["data"][0]["line_code"] == "34A"
    assert result["sources"][0]["name"] == "IETT SOAP Services"


@pytest.mark.asyncio
async def test_stops_for_line_upserts_bus_stop(tmp_path):
    svc = service(tmp_path)
    result = await svc.stops_for_line("34A")

    assert result["data"][0]["stop_code"] == "100"
    nearby = svc.geo.nearby(lat=41.0, lon=29.0, radius_m=100, limit=5, types=["bus_stop"])
    assert nearby[0]["name"] == "Stop"


@pytest.mark.asyncio
async def test_line_info_failure_returns_structured_error(tmp_path):
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(
        settings=settings,
        iett_client=FailingIett(),
        geo_repository=GeoRepository(settings.database_path),
    )

    result = await svc.line_info("34A")

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["warnings"]


@pytest.mark.asyncio
async def test_line_info_rate_limit_returns_retry_after_envelope(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(
        settings=settings,
        iett_client=RateLimitedIett(),
        geo_repository=GeoRepository(settings.database_path),
    )

    result = await svc.line_info("34A")

    assert result["ok"] is False
    assert result["freshness"]["status"] == "stale"
    assert result["data"][0]["source"] == "iett"
    assert result["data"][0]["retry_after_seconds"] == 2.5


@pytest.mark.asyncio
async def test_line_info_cache_collapses_concurrent_requests(tmp_path):
    clear_source_cache()
    fake = FakeIett()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(
        settings=settings,
        iett_client=fake,
        geo_repository=GeoRepository(settings.database_path),
    )

    results = await asyncio.gather(*(svc.line_info("34A") for _ in range(20)))

    assert all(result["ok"] is True for result in results)
    assert fake.line_info_calls == 1


@pytest.mark.asyncio
async def test_stops_for_line_cache_collapses_concurrent_requests(tmp_path):
    clear_source_cache()
    fake = FakeIett()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(
        settings=settings,
        iett_client=fake,
        geo_repository=GeoRepository(settings.database_path),
    )

    results = await asyncio.gather(*(svc.stops_for_line("34A") for _ in range(20)))

    assert all(result["ok"] is True for result in results)
    assert fake.stops_for_line_calls == 1
