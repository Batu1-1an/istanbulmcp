import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache_snapshot
from app.services.city import CityService
from app.storage.geo import GeoRepository


class FakeIspark:
    def __init__(self):
        self.calls = 0

    async def parks(self):
        self.calls += 1
        return [
            {
                "parkID": 1,
                "parkName": "Moda Otopark",
                "lat": "40.9909",
                "lng": "29.0303",
                "capacity": 100,
                "emptyCapacity": 25,
                "district": "KADIKOY",
                "isOpen": 1,
            }
        ]


class FakeMetro:
    def __init__(self):
        self.calls = 0

    async def stations(self):
        self.calls += 1
        return [
            {
                "Id": 1,
                "Description": "Kadikoy",
                "LineId": 3,
                "LineName": "M4",
                "Order": 1,
                "DetailInfo": {"Latitude": "40.9906", "Longitude": "29.0220"},
            }
        ]


class FakeAir:
    def __init__(self):
        self.station_calls = 0
        self.reading_calls = 0

    async def stations(self):
        self.station_calls += 1
        return [{"Id": "aq1", "Name": "Kadikoy", "Location": "POINT (29.0303 40.9909)"}]

    async def readings(self, station_id):
        self.reading_calls += 1
        return [{"ReadTime": "2026-05-13T15:08:09+03:00", "AQI": None, "Concentration": None}]


class FakeTraffic:
    def __init__(self):
        self.calls = 0

    async def index_history(self):
        self.calls += 1
        return [{"TrafficIndex": 63, "TrafficIndexDate": "2026-06-12T15:05:00"}]


class FailingAir:
    async def stations(self):
        raise RuntimeError("down")

    async def readings(self, _station_id):
        raise RuntimeError("down")


def service(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "city.sqlite3")
    return CityService(
        settings=settings,
        geo_repository=GeoRepository(settings.database_path),
        ispark_client=FakeIspark(),
        metro_client=FakeMetro(),
        air_quality_client=FakeAir(),
        traffic_client=FakeTraffic(),
    )


@pytest.mark.asyncio
async def test_parking_nearby_returns_capacity(tmp_path):
    result = await service(tmp_path).parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)

    assert result["data"][0]["name"] == "Moda Otopark"
    assert result["data"][0]["properties"]["empty_capacity"] == 25


@pytest.mark.asyncio
async def test_traffic_status_returns_label(tmp_path):
    result = await service(tmp_path).traffic_status()

    assert result["data"][0]["traffic_index"] == 63
    assert result["data"][0]["label"] == "high"
    assert "road-level congestion" in result["data"][0]["capabilities"]["does_not_support"]


@pytest.mark.asyncio
async def test_air_quality_warns_on_missing_aqi(tmp_path):
    result = await service(tmp_path).air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=1)

    assert result["data"][0]["latest_reading"]["AQI"] is None
    assert result["data"][0]["latest_reading_quality"]["has_aqi"] is False
    assert result["data"][0]["latest_reading_quality"]["has_reading"] is True
    assert result["warnings"]


@pytest.mark.asyncio
async def test_air_quality_radius_validation_returns_envelope(tmp_path):
    result = await service(tmp_path).air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=7000, limit=1)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "validation_error"
    assert result["data"][0]["field"] == "radius_m"
    assert result["data"][0]["allowed_max"] == 5000


@pytest.mark.asyncio
async def test_bbox_validation_returns_envelope(tmp_path):
    result = await service(tmp_path).bbox_search(bbox=[29.1, 40.9, 28.9, 41.1], limit=5)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "validation_error"
    assert result["data"][0]["field"] == "bbox"


@pytest.mark.asyncio
async def test_air_quality_source_failure_returns_envelope(tmp_path):
    settings = Settings(database_path=tmp_path / "city.sqlite3")
    svc = CityService(
        settings=settings,
        geo_repository=GeoRepository(settings.database_path),
        ispark_client=FakeIspark(),
        metro_client=FakeMetro(),
        air_quality_client=FailingAir(),
        traffic_client=FakeTraffic(),
    )

    result = await svc.air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=1)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["warnings"] == ["IBB source request failed: RuntimeError"]


@pytest.mark.asyncio
async def test_parking_source_uses_ttl_cache(tmp_path):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "city.sqlite3", ispark_cache_ttl_seconds=300)
    ispark = FakeIspark()
    svc = CityService(
        settings=settings,
        geo_repository=GeoRepository(settings.database_path),
        ispark_client=ispark,
        metro_client=FakeMetro(),
        air_quality_client=FakeAir(),
        traffic_client=FakeTraffic(),
    )

    first = await svc.parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)
    second = await svc.parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert ispark.calls == 1
    assert any(row["source"] == "ispark.parks" and row["is_fresh"] for row in source_cache_snapshot())
