"""Regression cases captured before repairing the live İBB GTFS stop path."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.city import CityService

CSV_URL = (
    "https://data.ibb.gov.tr/dataset/8540e256-6df5-4719-85bc-e64e91508ede/"
    "resource/2299bc82-983b-4bdf-8520-5cef8c555e29/download/stops.csv"
)


def make_service(tmp_path, resources):
    clear_source_cache()
    ckan = SimpleNamespace(package_show_bounded=AsyncMock(return_value={"resources": resources}))
    return CityService(settings=Settings(database_path=tmp_path / "gtfs.sqlite3"), ckan_client=ckan)


@pytest.mark.asyncio
async def test_gtfs_selects_real_csv_even_when_only_stop_times_is_datastore_active(tmp_path):
    wrong = {"id": "stop-times", "name": "stop_times", "datastore_active": True,
             "description": "İçerisinde durak bilgileri ve durak sıralamaları bulunur.",
             "url": CSV_URL.replace("stops.csv", "stop_times.csv")}
    actual = {"id": "2299bc82-983b-4bdf-8520-5cef8c555e29", "name": "stops",
              "datastore_active": False, "url": CSV_URL, "format": "CSV"}
    selected = await make_service(tmp_path, [wrong, actual])._resolve_gtfs_stops_resource()
    assert selected["id"] == actual["id"]


def test_gtfs_does_not_use_descriptions_to_identify_the_stops_file(tmp_path):
    service = make_service(tmp_path, [])
    assert not service._is_gtfs_stops_resource({
        "name": "stop_times", "description": "durak bilgileri", "url": CSV_URL.replace("stops.csv", "stop_times.csv"),
    })
    assert not service._is_gtfs_stops_resource({"name": "bus stops backup", "datastore_active": True})


def test_gtfs_normalizes_only_the_known_grouped_coordinate_format(tmp_path):
    service = make_service(tmp_path, [])
    feature = service._gtfs_stop_feature({
        "stop_id": "292235", "stop_name": "RIFAT ILGAZ CADDESİ",
        "stop_lat": "410.191.700.005.564", "stop_lon": "286.843.529.999.755",
    })
    assert feature is not None
    assert feature["lat"] == pytest.approx(41.0191700005564)
    assert feature["lon"] == pytest.approx(28.6843529999755)


@pytest.mark.asyncio
async def test_failed_stop_refresh_does_not_return_old_index_rows_as_fresh(tmp_path):
    service = make_service(tmp_path, [])
    service.geo.upsert_features([{
        "id": "gtfs_stop:old", "source": "gtfs", "feature_type": "public_transport_stop",
        "source_id": "old", "name": "Unverified old stop", "lat": 41.01917, "lon": 28.684353,
    }])
    result = await service.nearby(lat=41.01917, lon=28.684353, types=["public_transport_stop"])
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert not any(row.get("source_id") == "old" for row in result["data"])
    assert any(source["coverage_status"] == "unavailable" for source in result["sources"])
