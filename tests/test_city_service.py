import pytest

from app.core.settings import Settings
from app.services.city import CityService
from app.storage.geo import GeoRepository


class FakeIspark:
    async def parks(self):
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
    async def stations(self):
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
    async def stations(self):
        return [{"Id": "aq1", "Name": "Kadikoy", "Location": "POINT (29.0303 40.9909)"}]

    async def readings(self, station_id):
        return [{"ReadTime": "2026-05-13T15:08:09+03:00", "AQI": None, "Concentration": None}]


class FakeTraffic:
    async def index_history(self):
        return [{"TrafficIndex": 63, "TrafficIndexDate": "2026-06-12T15:05:00"}]


def service(tmp_path):
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


@pytest.mark.asyncio
async def test_air_quality_warns_on_missing_aqi(tmp_path):
    result = await service(tmp_path).air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=1)

    assert result["data"][0]["latest_reading"]["AQI"] is None
    assert result["warnings"]
