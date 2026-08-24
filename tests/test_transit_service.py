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
        self.disruptions_calls = 0
        self.planned_departures_calls = 0

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

    async def disruptions(self):
        self.disruptions_calls += 1
        return [
            {"HAT": "34A", "TIP": "HAT DUYURUSU", "MESAJ": "Sefer değişikliği", "GUNCELLEME_SAATI": "2026-08-24T10:30:00+03:00"},
            {"HAT": "500T", "TIP": "BİLGİ", "MESAJ": "Güzergah güncellendi", "GUNCELLEME_SAATI": "2026-08-24T09:15:00+03:00"},
            {"HAT": "34A", "TIP": "HAT DUYURUSU", "MESAJ": "", "GUNCELLEME_SAATI": "2026-08-24T08:00:00+03:00"},
        ]

    async def planned_departures(self, line_code):
        self.planned_departures_calls += 1
        if line_code == "99":
            return []
        return [
            {"SHATKODU": line_code, "HATADI": "A - B", "SGUZERGAH": "A - B", "SYON": "G", "SGUNTIPI": "I", "DT": "06:30"},
            {"SHATKODU": line_code, "HATADI": "A - B", "SGUZERGAH": "A - B", "SYON": "D", "SGUNTIPI": "C", "DT": "08:30"},
            {"SHATKODU": line_code, "HATADI": "A - B", "SGUZERGAH": "A - B", "SYON": "G", "SGUNTIPI": "P", "DT": "09:00"},
            {"SHATKODU": line_code, "HATADI": "A - B", "SGUZERGAH": "A - B", "SYON": "G", "SGUNTIPI": "X", "DT": "10:00"},
            {"SHATKODU": "OTHER", "HATADI": "Other", "SGUZERGAH": "Other", "SYON": "G", "SGUNTIPI": "I", "DT": "05:00"},
        ]


class FailingIett:
    async def line_info(self, line_code):
        raise RuntimeError("down")

    async def stops_for_line(self, line_code):
        raise RuntimeError("down")

    async def disruptions(self):
        raise RuntimeError("down")

    async def planned_departures(self, line_code):
        raise RuntimeError("down")


class RateLimitedIett:
    async def line_info(self, _line_code):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)

    async def stops_for_line(self, _line_code):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)

    async def disruptions(self):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)

    async def planned_departures(self, _line_code):
        raise SourceRateLimitExceeded(source="iett", retry_after_seconds=2.5)


class MalformedIett(FakeIett):
    async def disruptions(self):
        return [{"HAT": "34A", "MESAJ": "ok"}, "not-an-object"]

    async def planned_departures(self, line_code):
        return [
            {"SHATKODU": line_code, "SGUNTIPI": "I", "SYON": "G", "DT": None},
            {"SHATKODU": line_code, "SGUNTIPI": "I", "SYON": "G", "DT": "06:30"},
        ]


class DuplicateIett(FakeIett):
    async def disruptions(self):
        rows = await super().disruptions()
        return rows + [dict(rows[1])]

    async def planned_departures(self, line_code):
        rows = await super().planned_departures(line_code)
        return rows + [dict(rows[0])]


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
    assert result["data"][0]["maps_url"] == "https://www.google.com/maps/search/?api=1&query=41.000000,29.000000"
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
async def test_line_info_rejects_invalid_line_code(tmp_path):
    result = await service(tmp_path).line_info("../34A")

    assert result["ok"] is False
    assert result["data"][0]["field"] == "line_code"


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


@pytest.mark.asyncio
async def test_disruptions_filters_line_and_excludes_empty_messages(tmp_path):
    svc = service(tmp_path)

    result = await svc.disruptions(line_code="34a", limit=10)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["line_code"] == "34A"
    assert result["data"][0]["message"] == "Sefer değişikliği"
    assert result["data"][0]["updated_at"] == "2026-08-24T10:30:00+03:00"
    assert any("line_code=34A" in item for item in result["limits"])


@pytest.mark.asyncio
async def test_disruptions_empty_filter_returns_successful_empty_result(tmp_path):
    result = await service(tmp_path).disruptions(line_code="99")

    assert result["ok"] is True
    assert result["data"] == []
    assert "No IETT disruptions found" in result["summary"]


@pytest.mark.asyncio
async def test_disruptions_failure_and_validation_are_structured(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    failing = TransitService(settings=settings, iett_client=FailingIett(), geo_repository=GeoRepository(settings.database_path))
    failed = await failing.disruptions()
    invalid = await service(tmp_path).disruptions(line_code="../34A")

    assert failed["ok"] is False
    assert failed["freshness"]["status"] == "broken"
    assert invalid["ok"] is False
    assert invalid["data"][0]["field"] == "line_code"


@pytest.mark.asyncio
async def test_disruptions_cache_collapses_concurrent_requests(tmp_path):
    clear_source_cache()
    fake = FakeIett()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(settings=settings, iett_client=fake, geo_repository=GeoRepository(settings.database_path))

    results = await asyncio.gather(*(svc.disruptions() for _ in range(20)))

    assert all(result["ok"] is True for result in results)
    assert fake.disruptions_calls == 1


@pytest.mark.asyncio
async def test_malformed_disruption_rows_return_structured_error(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(settings=settings, iett_client=MalformedIett(), geo_repository=GeoRepository(settings.database_path))

    result = await svc.disruptions()

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert "ValueError" in result["warnings"][0]


@pytest.mark.asyncio
async def test_planned_departures_normalizes_sorts_and_warns_main_terminal(tmp_path):
    result = await service(tmp_path).planned_departures(line_code="34a", limit=10)

    assert result["ok"] is True
    assert [row["day_type_label"] for row in result["data"]] == ["saturday", "sunday", "unknown", "weekday"]
    assert all(row["line_code"] == "34A" for row in result["data"])
    assert result["data"][-1]["planned_departure_time"] == "06:30"
    assert any("main-terminal planned departures" in item for item in result["limits"])
    assert any("not intermediate-stop ETA" in item for item in result["limits"])


@pytest.mark.asyncio
async def test_planned_departures_empty_result_and_validation_are_structured(tmp_path):
    svc = service(tmp_path)
    empty = await svc.planned_departures(line_code="99")
    invalid = await svc.planned_departures(line_code="x" * 21)

    assert empty["ok"] is True
    assert empty["data"] == []
    assert invalid["ok"] is False
    assert invalid["data"][0]["field"] == "line_code"


@pytest.mark.asyncio
async def test_planned_departures_failure_and_cache_are_structured(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    failing = TransitService(settings=settings, iett_client=FailingIett(), geo_repository=GeoRepository(settings.database_path))
    failed = await failing.planned_departures(line_code="34A")

    assert failed["ok"] is False
    assert failed["freshness"]["status"] == "broken"

    clear_source_cache()
    fake = FakeIett()
    svc = TransitService(settings=settings, iett_client=fake, geo_repository=GeoRepository(settings.database_path))
    results = await asyncio.gather(*(svc.planned_departures(line_code="34A") for _ in range(20)))

    assert all(result["ok"] is True for result in results)
    assert fake.planned_departures_calls == 1


@pytest.mark.asyncio
async def test_planned_departures_rejects_missing_required_time_in_structured_error(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(settings=settings, iett_client=MalformedIett(), geo_repository=GeoRepository(settings.database_path))

    result = await svc.planned_departures(line_code="34A")

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert "ValueError" in result["warnings"][0]


@pytest.mark.asyncio
async def test_disruptions_and_planned_departures_deduplicate_stably(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "transit.sqlite3")
    svc = TransitService(settings=settings, iett_client=DuplicateIett(), geo_repository=GeoRepository(settings.database_path))

    disruptions = await svc.disruptions()
    departures = await svc.planned_departures(line_code="34A")

    assert [(row["line_code"], row["message"]) for row in disruptions["data"]] == [
        ("34A", "Sefer değişikliği"),
        ("500T", "Güzergah güncellendi"),
    ]
    assert len(departures["data"]) == 4
    assert [row["planned_departure_time"] for row in departures["data"]] == ["08:30", "09:00", "10:00", "06:30"]
