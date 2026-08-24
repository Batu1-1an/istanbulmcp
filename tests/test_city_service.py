import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache_snapshot
from app.connectors.ckan import CkanError
from app.services.city import CityService, ISTANBUL_GTFS_BOUNDS
from app.services.city import LIBRARY_LOCATIONS_RESOURCE_ID, WIFI_LOCATIONS_RESOURCE_ID
from app.storage.geo import GeoRepository


GTFS_FIXTURE_RESOURCE_ID = "fixture-active-stops"


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
    async def package_show(self, dataset_id):
        return {
            "name": dataset_id,
            "resources": [
                {
                    "id": GTFS_FIXTURE_RESOURCE_ID,
                    "name": "stops.txt",
                    "format": "CSV",
                    "datastore_active": True,
                    "last_modified": "2026-08-24T08:00:00Z",
                }
            ],
        }

    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        records = {
            GTFS_FIXTURE_RESOURCE_ID: [
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


class PagedGtfsCkan:
    def __init__(self):
        self.datastore_calls = []
        self.records = [
            {
                "stop_id": f"far-{index}",
                "stop_name": f"Far Stop {index}",
                "stop_lat": "41.2000",
                "stop_lon": "29.2000",
            }
            for index in range(100)
        ]
        self.records.extend(
            [
                {"stop_id": "outside-first-page", "stop_name": "Kadikoy Rihtim", "stop_lat": "40.9910", "stop_lon": "29.0305"},
                {"stop_id": "invalid", "stop_name": "Invalid", "stop_lat": "not-a-number", "stop_lon": "29.0305"},
            ]
        )

    async def package_show(self, dataset_id):
        return {
            "name": dataset_id,
            "resources": [
                {"id": "active-stops", "name": "GTFS stops", "datastore_active": True, "last_modified": "2026-08-24T08:00:00Z"},
                {"id": "other", "name": "routes.txt", "datastore_active": True},
            ],
        }

    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        self.datastore_calls.append({"resource_id": resource_id, "limit": limit, "offset": offset})
        page = self.records[offset : offset + limit]
        return {"records": page, "total": len(self.records)}


class IncompleteGtfsCkan(PagedGtfsCkan):
    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        self.datastore_calls.append({"resource_id": resource_id, "limit": limit, "offset": offset})
        return {"records": self.records[offset : offset + limit] if offset == 0 else [], "total": len(self.records)}


class AmbiguousGtfsCkan(PagedGtfsCkan):
    async def package_show(self, dataset_id):
        return {
            "name": dataset_id,
            "resources": [
                {"id": "active-stops", "name": "stops.txt", "datastore_active": True},
                {"id": "active-stops-copy", "name": "GTFS stops backup", "datastore_active": True},
            ],
        }


class MissingGtfsCkan(PagedGtfsCkan):
    async def package_show(self, dataset_id):
        return {
            "name": dataset_id,
            "resources": [{"id": "routes", "name": "routes.txt", "datastore_active": True}],
        }


class OutsideIstanbulGtfsCkan(PagedGtfsCkan):
    def __init__(self):
        super().__init__()
        self.records.append(
            {
                "stop_id": "outside-istanbul",
                "stop_name": "Paris Stop",
                "stop_lat": "48.8566",
                "stop_lon": "2.3522",
            }
        )


class CountingGeoRepository(GeoRepository):
    def __init__(self, database_path):
        super().__init__(database_path)
        self.replace_calls = 0

    def replace_features(self, **kwargs):
        self.replace_calls += 1
        return super().replace_features(**kwargs)


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


def paged_gtfs_service(tmp_path, ckan):
    clear_source_cache()
    settings = Settings(database_path=tmp_path / "paged-city.sqlite3")
    return CityService(
        settings=settings,
        geo_repository=CountingGeoRepository(settings.database_path),
        ispark_client=FakeIspark(),
        metro_client=FakeMetro(),
        air_quality_client=FakeAir(),
        traffic_client=FakeTraffic(),
        ckan_client=ckan,
    )


@pytest.mark.asyncio
async def test_parking_nearby_returns_capacity(tmp_path):
    result = await service(tmp_path).parking_nearby(lat=40.9909, lon=29.0303, radius_m=500, limit=5)

    assert result["data"][0]["name"] == "Moda Otopark"
    assert result["data"][0]["properties"]["empty_capacity"] == 25
    assert result["data"][0]["maps_url"] == "https://www.google.com/maps/search/?api=1&query=40.990900,29.030300"


@pytest.mark.asyncio
async def test_parking_by_district_uses_source_district_without_distance(tmp_path):
    result = await service(tmp_path).parking_by_district(district="Başakşehir", limit=5)

    assert result["ok"] is True
    assert result["data"][0]["name"] == "Basaksehir Otopark"
    assert result["data"][0]["empty_capacity"] == 80
    assert result["data"][0]["maps_url"] == "https://www.google.com/maps/search/?api=1&query=41.093000,28.806000"
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
    assert payload["parking"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert payload["metro_stations"][0]["name"] == "Kadikoy"
    assert payload["metro_stations"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert payload["public_transport_stops"][0]["name"] == "Kadikoy Rihtim"
    assert payload["public_transport_stops"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert payload["traffic"]["traffic_index"] == 63


@pytest.mark.asyncio
async def test_mobility_nearby_uses_active_paged_gtfs_and_reports_context(tmp_path):
    ckan = PagedGtfsCkan()
    svc = paged_gtfs_service(tmp_path, ckan)

    first = await svc.mobility_nearby(lat=40.9910, lon=29.0303, radius_m=500, limit=5)
    second = await svc.mobility_nearby(lat=40.9910, lon=29.0303, radius_m=500, limit=5)

    first_payload = first["data"][0]
    gtfs_source = next(source for source in first["sources"] if source.get("dataset_id") == "iett-gtfs-verisi")

    assert first["ok"] is True
    assert second["ok"] is True
    assert first_payload["public_transport_stops"][0]["source_id"] == "outside-first-page"
    assert len(ckan.datastore_calls) == 2
    assert [call["offset"] for call in ckan.datastore_calls] == [0, 100]
    assert gtfs_source["resource_id"] == "active-stops"
    assert gtfs_source["source_updated_at"] == "2026-08-24T08:00:00Z"
    assert gtfs_source["scope"] == "all_active_datastore_records"
    assert gtfs_source["reported_total"] == 102
    assert gtfs_source["received_total"] == 102
    assert gtfs_source["accepted_total"] == 101
    assert gtfs_source["skipped_total"] == 1
    assert gtfs_source["last_successful_refresh_at"]
    assert svc.geo.replace_calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("ckan_factory", [MissingGtfsCkan, AmbiguousGtfsCkan])
async def test_gtfs_resource_candidates_fail_without_replacing_existing_layer(tmp_path, ckan_factory):
    svc = paged_gtfs_service(tmp_path, ckan_factory())
    svc.geo.upsert_features(
        [
            {
                "id": "gtfs_stop:old",
                "source": "gtfs",
                "feature_type": "public_transport_stop",
                "source_id": "old",
                "name": "Old Stop",
                "lat": 40.991,
                "lon": 29.0305,
            }
        ]
    )

    with pytest.raises(CkanError):
        await svc._gtfs_stops()

    nearby = svc.geo.nearby(lat=40.991, lon=29.0305, radius_m=100, limit=5, types=["public_transport_stop"])
    assert [row["source_id"] for row in nearby] == ["old"]
    assert svc.geo.replace_calls == 0


@pytest.mark.asyncio
async def test_incomplete_gtfs_pagination_fails_without_replacing_existing_layer(tmp_path):
    svc = paged_gtfs_service(tmp_path, IncompleteGtfsCkan())
    svc.geo.upsert_features(
        [
            {
                "id": "gtfs_stop:old",
                "source": "gtfs",
                "feature_type": "public_transport_stop",
                "source_id": "old",
                "name": "Old Stop",
                "lat": 40.991,
                "lon": 29.0305,
            }
        ]
    )

    with pytest.raises(CkanError, match="pagination incomplete"):
        await svc._gtfs_stops()

    nearby = svc.geo.nearby(lat=40.991, lon=29.0305, radius_m=100, limit=5, types=["public_transport_stop"])
    assert [row["source_id"] for row in nearby] == ["old"]
    assert svc.geo.replace_calls == 0


def test_gtfs_resource_name_matches_stops_but_not_stop_times(tmp_path):
    svc = service(tmp_path)

    assert svc._is_gtfs_stops_resource({"name": "stops.txt"}) is True
    assert svc._is_gtfs_stops_resource({"name": "stop_times.txt"}) is False


def test_gtfs_coordinate_bounds_accept_edges_and_reject_outside(tmp_path):
    svc = service(tmp_path)
    min_lat, max_lat, min_lon, max_lon = ISTANBUL_GTFS_BOUNDS

    assert svc._gtfs_stop_feature({"stop_id": "edge", "stop_lat": min_lat, "stop_lon": min_lon})
    assert svc._gtfs_stop_feature({"stop_id": "outside", "stop_lat": min_lat - 0.01, "stop_lon": min_lon}) is None


@pytest.mark.asyncio
async def test_gtfs_outside_istanbul_coordinates_are_counted_as_skipped(tmp_path):
    svc = paged_gtfs_service(tmp_path, OutsideIstanbulGtfsCkan())

    cached = await svc._gtfs_stops()

    assert cached.metadata["reported_total"] == 103
    assert cached.metadata["accepted_total"] == 101
    assert cached.metadata["skipped_total"] == 2


@pytest.mark.asyncio
async def test_mobility_nearby_returns_district_parking_for_district_place(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Kadıköy", radius_m=1500, limit=3)

    assert result["ok"] is True
    assert "ilçe geneli otopark" in result["summary"]
    assert result["data"][0]["query"]["district"] == "Kadıköy"
    assert result["data"][0]["query"]["distance_included"] is False
    assert result["data"][0]["parking"][0]["name"] == "Moda Otopark"
    assert result["data"][0]["parking"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert "distance_m" not in result["data"][0]["parking"][0]


@pytest.mark.asyncio
async def test_mobility_nearby_returns_district_parking_for_uncurated_district_text(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Başakşehir merkez", radius_m=1500, limit=3)

    assert result["ok"] is True
    assert result["data"][0]["query"]["district"] == "Başakşehir"
    assert result["data"][0]["parking"][0]["name"] == "Basaksehir Otopark"
    assert result["data"][0]["parking"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert "distance_m" not in result["data"][0]["parking"][0]


@pytest.mark.asyncio
async def test_city_services_nearby_filters_wifi_and_returns_district_libraries(tmp_path):
    result = await service(tmp_path).city_services_nearby(place="Kadıköy", radius_m=600, limit=5)

    payload = result["data"][0]
    assert result["ok"] is True
    assert [row["name"] for row in payload["wifi_locations"]] == ["Kadikoy WiFi"]
    assert payload["wifi_locations"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert [row["name"] for row in payload["libraries"]] == ["Kadikoy Library"]
    assert "maps_url" not in payload["libraries"][0]
    assert payload["libraries"][0]["maps_search_url"].startswith("https://www.google.com/maps/search/?")
    assert "Kadikoy+Library" in payload["libraries"][0]["maps_search_url"]
    assert payload["libraries"][0]["location_precision"] == "address_search"
    assert any("district-level" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_mobility_nearby_unknown_place_returns_validation_envelope(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="Atlantis", radius_m=600, limit=3)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "place"


@pytest.mark.asyncio
async def test_mobility_nearby_rejects_overlong_place(tmp_path):
    result = await service(tmp_path).mobility_nearby(place="x" * 121, radius_m=600, limit=3)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "place"
