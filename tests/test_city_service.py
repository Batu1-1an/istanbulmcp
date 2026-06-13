import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache_snapshot
from app.services.city import CityService
from app.services.city import GTFS_STOPS_RESOURCE_ID, LIBRARY_LOCATIONS_RESOURCE_ID, WIFI_LOCATIONS_RESOURCE_ID
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
            },
            {
                "parkID": 2,
                "parkName": "Basaksehir Otopark",
                "lat": "41.0930",
                "lng": "28.8060",
                "capacity": 250,
                "emptyCapacity": 80,
                "district": "Başakşehir",
                "isOpen": 1,
            },
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


class FakeCkan:
    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        records = {
            GTFS_STOPS_RESOURCE_ID: [
                {
                    "stop_id": "s1",
                    "stop_code": "1001",
                    "stop_name": "Kadikoy Rihtim",
                    "stop_lat": "40.9910",
                    "stop_lon": "29.0305",
                    "wheelchair_boarding": "1",
                },
                {
                    "stop_id": "s2",
                    "stop_code": "1002",
                    "stop_name": "Far Stop",
                    "stop_lat": "41.2000",
                    "stop_lon": "29.2000",
                },
            ],
            WIFI_LOCATIONS_RESOURCE_ID: [
                {
                    "location_group": "Library",
                    "location_type": "Indoor",
                    "location_code": "WIFI-1",
                    "location": "Kadikoy WiFi",
                    "latitude": 40.9911,
                    "longitude": 29.0307,
                },
                {
                    "location_group": "Invalid",
                    "location_type": "Invalid",
                    "location_code": "ZERO",
                    "location": "Bad Coordinates",
                    "latitude": 0.0,
                    "longitude": 0.0,
                },
            ],
            LIBRARY_LOCATIONS_RESOURCE_ID: [
                {
                    "Kutuphane Adi": "Kadikoy Library",
                    "Ilce Adi": "Kadıköy",
                    "Adres": "Kadikoy address",
                    "Telefon": "0212",
                    "Calisma Saatleri": "09:00-18:00",
                    "Calisma Gunleri": "Hafta ici",
                },
                {
                    "Kutuphane Adi": "Besiktas Library",
                    "Ilce Adi": "Beşiktaş",
                    "Adres": "Besiktas address",
                },
            ],
        }
        return {"records": records.get(resource_id, [])[:limit], "total": len(records.get(resource_id, []))}


class FailingAir:
    async def stations(self):
        raise RuntimeError("down")

    async def readings(self, _station_id):
        raise RuntimeError("down")


class FailingAirReadings:
    async def stations(self):
        return [{"Id": "aq1", "Name": "Kadikoy", "Location": "POINT (29.0303 40.9909)"}]

    async def readings(self, _station_id):
        raise RuntimeError("reading down")


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
        ckan_client=FakeCkan(),
    )


@pytest.mark.asyncio
async def test_parking_nearby_returns_capacity(tmp_path):
    result = await service(tmp_path).parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)

    assert result["data"][0]["name"] == "Moda Otopark"
    assert result["data"][0]["properties"]["empty_capacity"] == 25


@pytest.mark.asyncio
async def test_parking_by_district_uses_source_district_without_distance(tmp_path):
    result = await service(tmp_path).parking_by_district(district="Başakşehir", limit=5)

    assert result["ok"] is True
    assert result["data"][0]["name"] == "Basaksehir Otopark"
    assert result["data"][0]["empty_capacity"] == 80
    assert "distance_m" not in result["data"][0]
    assert "no distance shown without an exact location" in result["limits"]
    assert any("exact place or coordinates" in warning for warning in result["warnings"])


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
        ckan_client=FakeCkan(),
    )

    result = await svc.air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=1)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["warnings"] == ["IBB source request failed: RuntimeError"]


@pytest.mark.asyncio
async def test_nearby_returns_partial_results_when_one_source_fails(tmp_path):
    settings = Settings(database_path=tmp_path / "city.sqlite3")
    svc = CityService(
        settings=settings,
        geo_repository=GeoRepository(settings.database_path),
        ispark_client=FakeIspark(),
        metro_client=FakeMetro(),
        air_quality_client=FailingAir(),
        traffic_client=FakeTraffic(),
        ckan_client=FakeCkan(),
    )

    result = await svc.nearby(lat=40.9909, lon=29.0303, radius_m=1500, limit=5)

    assert result["ok"] is True
    assert {row["feature_type"] for row in result["data"]} >= {"parking", "metro_station"}
    assert any("Air quality station source refresh failed" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_air_quality_reading_failure_returns_partial_station(tmp_path):
    settings = Settings(database_path=tmp_path / "city.sqlite3")
    svc = CityService(
        settings=settings,
        geo_repository=GeoRepository(settings.database_path),
        ispark_client=FakeIspark(),
        metro_client=FakeMetro(),
        air_quality_client=FailingAirReadings(),
        traffic_client=FakeTraffic(),
        ckan_client=FakeCkan(),
    )

    result = await svc.air_quality_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=1)

    assert result["ok"] is True
    assert result["data"][0]["name"] == "Kadikoy"
    assert result["data"][0]["latest_reading_quality"]["has_reading"] is False
    assert any("readings are unavailable" in warning for warning in result["warnings"])


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
        ckan_client=FakeCkan(),
    )

    first = await svc.parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)
    second = await svc.parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert ispark.calls == 1
    assert any(row["source"] == "ispark.parks" and row["is_fresh"] for row in source_cache_snapshot())


@pytest.mark.asyncio
async def test_mobility_nearby_aggregates_sections_for_place(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Kadıköy Rıhtım", radius_m=1500, limit=3)

    payload = result["data"][0]
    assert result["ok"] is True
    assert payload["query"]["district"] == "Kadikoy"
    assert payload["parking"][0]["name"] == "Moda Otopark"
    assert payload["metro_stations"][0]["name"] == "Kadikoy"
    assert payload["public_transport_stops"][0]["name"] == "Kadikoy Rihtim"
    assert payload["traffic"]["traffic_index"] == 63


@pytest.mark.asyncio
async def test_mobility_nearby_returns_district_parking_for_district_place(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Kadıköy", radius_m=1500, limit=3)

    assert result["ok"] is True
    assert "ilçe geneli otopark" in result["summary"]
    assert result["data"][0]["query"]["district"] == "Kadıköy"
    assert result["data"][0]["query"]["distance_included"] is False
    assert result["data"][0]["parking"][0]["name"] == "Moda Otopark"
    assert "distance_m" not in result["data"][0]["parking"][0]


@pytest.mark.asyncio
async def test_mobility_nearby_returns_district_parking_for_uncurated_district_text(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Başakşehir merkez", radius_m=1500, limit=3)

    assert result["ok"] is True
    assert result["data"][0]["query"]["district"] == "Başakşehir"
    assert result["data"][0]["parking"][0]["name"] == "Basaksehir Otopark"
    assert "distance_m" not in result["data"][0]["parking"][0]


@pytest.mark.asyncio
async def test_city_services_nearby_filters_wifi_and_returns_district_libraries(tmp_path):
    result = await service(tmp_path).city_services_nearby(place="Kadıköy", radius_m=600, limit=5)

    payload = result["data"][0]
    assert result["ok"] is True
    assert [row["name"] for row in payload["wifi_locations"]] == ["Kadikoy WiFi"]
    assert [row["name"] for row in payload["libraries"]] == ["Kadikoy Library"]
    assert any("district-level" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_mobility_nearby_unknown_place_returns_validation_envelope(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Atlantis", radius_m=600, limit=3)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "place"
