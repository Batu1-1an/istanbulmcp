import asyncio

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.disruptions import TransportDisruptionService


class FakeIett:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows if rows is not None else [
            {
                "HATKODU": "34A",
                "HAT": "Cevizlibağ - Söğütlüçeşme",
                "TIP": "HAT DUYURUSU",
                "MESAJ": "Sefer değişikliği",
                "GUNCELLEME_SAATI": "2026-08-25T10:30:00+03:00",
            }
        ]
        self.error = error
        self.calls = 0

    async def disruptions(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.rows)


class FakeMetro:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows if rows is not None else [
            {
                "operator": "metro_istanbul",
                "mode": "metro",
                "line_code": "M7",
                "route_label": "Yıldız-Mahmutbey",
                "event_type": "disruption",
                "message": "Teknik arıza.",
                "updated_at": None,
            },
            {
                "operator": "metro_istanbul",
                "mode": "tram",
                "line_code": "T1",
                "route_label": "Kabataş-Bağcılar",
                "event_type": "service_change",
                "message": "Kabataş yönünde gecikme yaşanıyor.",
                "updated_at": "2026-08-25T10:15:00+03:00",
            },
        ]
        self.error = error
        self.calls = 0

    async def service_statuses(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.rows)


class FakeSehirHatlari:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows if rows is not None else [
            {
                "operator": "sehir_hatlari",
                "mode": "ferry",
                "line_code": "HAT1",
                "route_label": "Kadıköy - Beşiktaş",
                "event_type": "cancellation",
                "message": "Sefer iptali.",
                "updated_at": None,
            }
        ]
        self.error = error
        self.calls = 0

    async def cancellations(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.rows)


class FakeMarmaray:
    def __init__(self, rows=None, error: Exception | None = None):
        self.rows = rows if rows is not None else [
            {
                "operator": "marmaray",
                "mode": "suburban_rail",
                "line_code": "MARMARAY",
                "route_label": "Gebze - Halkalı",
                "event_type": "announcement",
                "message": "Seferlerde gecikme vardır.",
                "updated_at": None,
            }
        ]
        self.error = error
        self.calls = 0

    async def urgent_notices(self):
        self.calls += 1
        if self.error:
            raise self.error
        return list(self.rows)


def service(tmp_path, *, iett=None, metro=None, sehir=None, marmaray=None):
    clear_source_cache()
    return TransportDisruptionService(
        settings=Settings(database_path=tmp_path / "transport.sqlite3"),
        iett_client=iett or FakeIett(),
        metro_client=metro or FakeMetro(),
        sehir_hatlari_client=sehir or FakeSehirHatlari(),
        marmaray_client=marmaray or FakeMarmaray(),
    )


@pytest.mark.asyncio
async def test_all_sources_aggregate_and_exclude_healthy_metro_rows(tmp_path):
    result = await service(tmp_path).disruptions(limit=20)

    assert result["ok"] is True
    assert {row["operator"] for row in result["data"]} == {"iett", "metro_istanbul", "sehir_hatlari", "marmaray"}
    assert all("source" not in row and "freshness" not in row for row in result["data"])
    assert all(row["event_type"] != "operational" for row in result["data"])
    assert result["freshness"]["status"] == "fresh"
    assert result["freshness"]["ttl_seconds"] == 120
    assert {source["coverage_status"] for source in result["sources"]} == {"checked"}


@pytest.mark.asyncio
async def test_mode_operator_and_line_filters_are_exact_and_preserve_fields(tmp_path):
    svc = service(tmp_path)

    metro = await svc.disruptions(mode="metro")
    assert [row["line_code"] for row in metro["data"]] == ["M7"]
    assert {source["operator"] for source in metro["sources"]} == {"metro_istanbul"}

    tram = await svc.disruptions(mode="tram")
    assert [row["line_code"] for row in tram["data"]] == ["T1"]

    route = await svc.disruptions(line="yıldız-mahmutbey")
    assert route["data"][0]["line_code"] == "M7"

    ferry = await svc.disruptions(line="kadıköy - beşiktaş")
    assert ferry["data"][0]["line_code"] == "HAT1"
    assert ferry["data"][0]["route_label"] == "Kadıköy - Beşiktaş"

    operator = await svc.disruptions(operator="marmaray")
    assert {row["operator"] for row in operator["data"]} == {"marmaray"}


@pytest.mark.asyncio
async def test_invalid_and_incompatible_filters_return_structured_validation(tmp_path):
    svc = service(tmp_path)

    invalid_mode = await svc.disruptions(mode="busssss")
    incompatible = await svc.disruptions(mode="ferry", operator="metro_istanbul")

    assert invalid_mode["ok"] is False
    assert invalid_mode["data"][0]["field"] == "mode"
    assert incompatible["ok"] is False
    assert incompatible["data"][0]["field"] == "operator"


@pytest.mark.asyncio
async def test_deduplicates_stably_and_lists_unsupported_operators_in_limits(tmp_path):
    duplicate = FakeSehirHatlari(
        rows=[
            {
                "operator": "sehir_hatlari",
                "mode": "ferry",
                "line_code": "HAT1",
                "route_label": "Kadıköy - Beşiktaş",
                "event_type": "cancellation",
                "message": "Sefer iptali.",
                "updated_at": None,
            }
        ] * 2
    )
    result = await service(tmp_path, sehir=duplicate).disruptions()

    assert len([row for row in result["data"] if row["operator"] == "sehir_hatlari"]) == 1
    assert any("İDO" in limit and "Turyol" in limit for limit in result["limits"])


@pytest.mark.asyncio
async def test_partial_source_failure_preserves_data_and_marks_unavailable(tmp_path):
    svc = service(tmp_path, metro=FakeMetro(error=TimeoutError("metro down")))

    result = await svc.disruptions()

    assert result["ok"] is True
    assert result["freshness"]["status"] == "unknown"
    assert any("metro_istanbul" in warning for warning in result["warnings"])
    metro_source = next(source for source in result["sources"] if source["operator"] == "metro_istanbul")
    assert metro_source["coverage_status"] == "unavailable"
    assert {row["operator"] for row in result["data"]} == {"iett", "sehir_hatlari", "marmaray"}


@pytest.mark.asyncio
async def test_all_source_failure_is_broken(tmp_path):
    down = RuntimeError("upstream down")
    svc = service(
        tmp_path,
        iett=FakeIett(error=down),
        metro=FakeMetro(error=down),
        sehir=FakeSehirHatlari(error=down),
        marmaray=FakeMarmaray(error=down),
    )

    result = await svc.disruptions()

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["data"] == []
    assert len(result["warnings"]) == 4


@pytest.mark.asyncio
async def test_all_checked_empty_sources_are_successful_empty_result(tmp_path):
    empty = []
    result = await service(
        tmp_path,
        iett=FakeIett(rows=empty),
        metro=FakeMetro(rows=empty),
        sehir=FakeSehirHatlari(rows=empty),
        marmaray=FakeMarmaray(rows=empty),
    ).disruptions()

    assert result["ok"] is True
    assert result["data"] == []
    assert result["freshness"]["status"] == "fresh"
    assert "kontrol edilen" in result["summary"]


@pytest.mark.asyncio
async def test_source_cache_reuses_normalized_results_for_concurrent_requests(tmp_path):
    iett = FakeIett()
    metro = FakeMetro()
    sehir = FakeSehirHatlari()
    marmaray = FakeMarmaray()
    svc = service(tmp_path, iett=iett, metro=metro, sehir=sehir, marmaray=marmaray)

    results = await asyncio.gather(*(svc.disruptions(limit=5) for _ in range(20)))

    assert all(result["ok"] for result in results)
    assert iett.calls == metro.calls == sehir.calls == marmaray.calls == 1
