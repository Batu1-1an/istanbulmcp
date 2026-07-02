import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache_snapshot
from app.services.iski import IskiService


FAULTS_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "ILCE_KODU": "AO",
                "MAHALLE_KODU": 607,
                "MAHALLE_ADI": "ATAŞEHİR ATATÜRK MAH",
                "ILCE_ADI": "ATAŞEHİR",
                "ARIZA_NO": "10000511781",
                "ARIZA_NEVI_ACIKLAMASI": "100 MM ÇAPLI ŞEBEKE HATTI ARIZASI",
                "BASLAMA_TARIHI": "2026-06-23 10:23:52",
                "TAHMINI_BITIS_TARIHI": "23/6/2026 17:00",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [29.1230, 40.9920],
                        [29.1250, 40.9920],
                        [29.1250, 40.9940],
                        [29.1230, 40.9940],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "ILCE_ADI": "BEŞİKTAŞ",
                "MAHALLE_ADI": "LEVENT MAH",
                "ARIZA_NO": "200",
                "ARIZA_NEVI_ACIKLAMASI": "İÇME SUYU HATTI ARIZASI",
                "BASLAMA_TARIHI": "2026-06-23 11:00:00",
                "TAHMINI_BITIS_TARIHI": "23/6/2026 18:00",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [29.0100, 41.0800],
                        [29.0120, 41.0800],
                        [29.0120, 41.0820],
                        [29.0100, 41.0820],
                    ]
                ],
            },
        },
    ],
}

DAMS = [
    {
        "kaynakAdi": "Alibey",
        "baslikAdi": "Alibey Barajı",
        "verim": "36",
        "biriktirmeHacmi": "34.14",
        "mevcutSuHacmi": "20.29",
        "dolulukOrani": "59.44",
        "azamiSuSeviyesi": "28.0",
    },
    {
        "kaynakAdi": "Omerli",
        "baslikAdi": "Ömerli Barajı",
        "verim": "220",
        "biriktirmeHacmi": "235.37",
        "mevcutSuHacmi": "140.0",
        "dolulukOrani": "75,5",
        "azamiSuSeviyesi": "62.0",
    },
]


class FakeIski:
    def __init__(self):
        self.fault_calls = 0
        self.dam_calls = 0

    async def active_faults(self):
        self.fault_calls += 1
        return FAULTS_GEOJSON

    async def dams(self):
        self.dam_calls += 1
        return DAMS


class FailingIski:
    async def active_faults(self):
        raise RuntimeError("down")

    async def dams(self):
        raise RuntimeError("down")


class FlakyIski:
    def __init__(self):
        self.fault_calls = 0
        self.dam_calls = 0

    async def active_faults(self):
        self.fault_calls += 1
        if self.fault_calls > 1:
            raise RuntimeError("temporary fault source outage")
        return FAULTS_GEOJSON

    async def dams(self):
        self.dam_calls += 1
        if self.dam_calls > 1:
            raise RuntimeError("temporary dam source outage")
        return DAMS


def service(client=None):
    clear_source_cache()
    return IskiService(settings=Settings(), client=client or FakeIski())


@pytest.mark.asyncio
async def test_active_faults_filters_district_and_normalizes_rows():
    result = await service().active_faults(district="Ataşehir", limit=5)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    row = result["data"][0]
    assert row["fault_number"] == "10000511781"
    assert row["district"] == "ATAŞEHİR"
    assert row["center"] == {"lat": 40.993, "lon": 29.124}
    assert row["maps_url"] == "https://www.google.com/maps/search/?api=1&query=40.993000,29.124000"
    assert "source=live ISKI GeoJSON" in result["limits"]


@pytest.mark.asyncio
async def test_fault_by_number_returns_active_match():
    result = await service().fault_by_number("200")

    assert result["ok"] is True
    assert result["data"][0]["district"] == "BEŞİKTAŞ"
    assert "found" in result["summary"]


@pytest.mark.asyncio
async def test_fault_by_number_returns_empty_for_unknown_active_fault():
    result = await service().fault_by_number("missing")

    assert result["ok"] is True
    assert result["data"] == []
    assert "No active ISKI fault" in result["summary"]


@pytest.mark.asyncio
async def test_nearby_faults_returns_sorted_distance_matches():
    result = await service().nearby_faults(lat=40.9929, lon=29.1241, radius_m=500, limit=5)

    assert result["ok"] is True
    assert [row["fault_number"] for row in result["data"]] == ["10000511781"]
    assert result["data"][0]["distance_m"] < 50
    assert "distance uses feature center" in result["limits"]


@pytest.mark.asyncio
async def test_nearby_faults_validates_radius():
    result = await service().nearby_faults(lat=40.99, lon=29.12, radius_m=6000, limit=1)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "radius_m"
    assert result["data"][0]["allowed_max"] == 5000


@pytest.mark.asyncio
async def test_dam_occupancy_filters_name_and_minimum():
    result = await service().dam_occupancy(dam_name="Ömerli", min_occupancy=70, limit=10)

    assert result["ok"] is True
    assert [row["name"] for row in result["data"]] == ["Omerli"]
    assert result["data"][0]["occupancy_rate"] == 75.5
    assert result["data"][0]["capacity"] == 235.37


@pytest.mark.asyncio
async def test_dam_occupancy_validates_minimum():
    result = await service().dam_occupancy(min_occupancy=101)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "min_occupancy"


@pytest.mark.asyncio
async def test_iski_source_failure_returns_envelope():
    result = await service(FailingIski()).active_faults()

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["warnings"] == ["ISKI source request failed: RuntimeError"]


@pytest.mark.asyncio
async def test_iski_faults_use_ttl_cache():
    clear_source_cache()
    fake = FakeIski()
    svc = IskiService(settings=Settings(iski_faults_cache_ttl_seconds=30), client=fake)

    first = await svc.active_faults(limit=5)
    second = await svc.active_faults(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert fake.fault_calls == 1
    assert any(row["source"] == "iski.active_faults" and row["is_fresh"] for row in source_cache_snapshot())


@pytest.mark.asyncio
async def test_iski_faults_return_stale_cache_when_source_fails_after_refresh():
    clear_source_cache()
    fake = FlakyIski()
    svc = IskiService(
        settings=Settings(
            iski_faults_cache_ttl_seconds=0,
            iski_faults_stale_if_error_seconds=60,
        ),
        client=fake,
    )

    first = await svc.active_faults(limit=5)
    second = await svc.active_faults(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert "returning cached snapshot" in second["warnings"][0]
    assert fake.fault_calls == 2


@pytest.mark.asyncio
async def test_iski_dams_return_stale_cache_when_source_fails_after_refresh():
    clear_source_cache()
    fake = FlakyIski()
    svc = IskiService(
        settings=Settings(
            iski_dams_cache_ttl_seconds=0,
            iski_dams_stale_if_error_seconds=60,
        ),
        client=fake,
    )

    first = await svc.dam_occupancy(limit=5)
    second = await svc.dam_occupancy(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert "returning cached snapshot" in second["warnings"][0]
    assert fake.dam_calls == 2
