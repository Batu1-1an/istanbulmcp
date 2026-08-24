import pytest

from app.storage.geo import GeoRepository


def test_nearby_returns_sorted_features(tmp_path):
    repo = GeoRepository(tmp_path / "geo.sqlite3")
    repo.upsert_features(
        [
            {
                "id": "a",
                "source": "test",
                "feature_type": "parking",
                "source_id": "a",
                "name": "A",
                "lat": 41.0,
                "lon": 29.0,
            },
            {
                "id": "b",
                "source": "test",
                "feature_type": "parking",
                "source_id": "b",
                "name": "B",
                "lat": 41.01,
                "lon": 29.0,
            },
        ]
    )

    results = repo.nearby(lat=41.0, lon=29.0, radius_m=2000, limit=5, types=["parking"])

    assert [item["name"] for item in results] == ["A", "B"]
    assert results[0]["distance_m"] == 0
    assert results[0]["maps_url"] == "https://www.google.com/maps/search/?api=1&query=41.000000,29.000000"


def test_bbox_search_filters_by_type(tmp_path):
    repo = GeoRepository(tmp_path / "geo.sqlite3")
    repo.upsert_features(
        [
            {"id": "a", "source": "test", "feature_type": "parking", "source_id": "a", "name": "A", "lat": 41.0, "lon": 29.0},
            {"id": "b", "source": "test", "feature_type": "metro_station", "source_id": "b", "name": "B", "lat": 41.0, "lon": 29.0},
        ]
    )

    results = repo.bbox_search(min_lon=28.9, min_lat=40.9, max_lon=29.1, max_lat=41.1, limit=10, types=["metro_station"])

    assert len(results) == 1
    assert results[0]["feature_type"] == "metro_station"
    assert results[0]["maps_url"] == "https://www.google.com/maps/search/?api=1&query=41.000000,29.000000"


def test_replace_features_removes_stale_rows_for_one_layer(tmp_path):
    repo = GeoRepository(tmp_path / "geo.sqlite3")
    repo.upsert_features(
        [
            {"id": "old", "source": "gtfs", "feature_type": "public_transport_stop", "source_id": "old", "name": "Old", "lat": 41.0, "lon": 29.0},
            {"id": "other", "source": "test", "feature_type": "parking", "source_id": "other", "name": "Other", "lat": 41.0, "lon": 29.0},
        ]
    )

    repo.replace_features(
        source="gtfs",
        feature_type="public_transport_stop",
        features=[
            {"id": "new", "source": "gtfs", "feature_type": "public_transport_stop", "source_id": "new", "name": "New", "lat": 41.01, "lon": 29.0},
        ],
    )

    stops = repo.bbox_search(min_lon=28.9, min_lat=40.9, max_lon=29.1, max_lat=41.1, limit=10, types=["public_transport_stop"])
    parking = repo.bbox_search(min_lon=28.9, min_lat=40.9, max_lon=29.1, max_lat=41.1, limit=10, types=["parking"])

    assert [row["name"] for row in stops] == ["New"]
    assert [row["name"] for row in parking] == ["Other"]


def test_replace_features_rolls_back_when_insert_fails(tmp_path):
    repo = GeoRepository(tmp_path / "geo.sqlite3")
    repo.upsert_features(
        [{"id": "old", "source": "gtfs", "feature_type": "public_transport_stop", "source_id": "old", "name": "Old", "lat": 41.0, "lon": 29.0}]
    )

    with pytest.raises(KeyError):
        repo.replace_features(
            source="gtfs",
            feature_type="public_transport_stop",
            features=[{"id": "broken", "source": "gtfs", "feature_type": "public_transport_stop", "source_id": "broken", "name": "Broken"}],
        )

    stops = repo.bbox_search(min_lon=28.9, min_lat=40.9, max_lon=29.1, max_lat=41.1, limit=10, types=["public_transport_stop"])

    assert [row["name"] for row in stops] == ["Old"]
