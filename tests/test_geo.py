from app.core.geo import google_maps_url, haversine_m, parse_wkt_point, radius_bbox


def test_parse_wkt_point_returns_lat_lon():
    assert parse_wkt_point("POINT (29.0245 41.1000)") == (41.1, 29.0245)


def test_haversine_returns_reasonable_distance():
    distance = haversine_m(40.9906, 29.0220, 41.0002, 29.0301)

    assert 1000 < distance < 1500


def test_radius_bbox_contains_origin_point():
    min_lon, min_lat, max_lon, max_lat = radius_bbox(41.0, 29.0, 1000)

    assert min_lat < 41.0 < max_lat
    assert min_lon < 29.0 < max_lon


def test_google_maps_url_returns_clickable_coordinate_link():
    assert google_maps_url(40.9909, 29.0303) == "https://www.google.com/maps/search/?api=1&query=40.990900,29.030300"


def test_google_maps_url_ignores_missing_or_invalid_coordinates():
    assert google_maps_url(None, 29.0303) is None
    assert google_maps_url(40.9909, "not-a-lon") is None
    assert google_maps_url(100, 29.0303) is None
