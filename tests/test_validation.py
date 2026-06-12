import pytest

from app.core.validation import (
    validate_bbox,
    validate_lat_lon,
    validate_limit,
    validate_radius,
)


def test_validate_lat_lon_accepts_istanbul_coordinates():
    assert validate_lat_lon(41.0082, 28.9784) == (41.0082, 28.9784)


def test_validate_lat_lon_rejects_invalid_latitude():
    with pytest.raises(ValueError, match="lat"):
        validate_lat_lon(100, 28.9784)


def test_validate_radius_enforces_maximum():
    with pytest.raises(ValueError, match="<= 5000"):
        validate_radius(5001)


def test_validate_limit_enforces_maximum():
    with pytest.raises(ValueError, match="<= 100"):
        validate_limit(101)


def test_validate_bbox_accepts_valid_bbox():
    assert validate_bbox([28.9, 40.9, 29.1, 41.1]) == (28.9, 40.9, 29.1, 41.1)


def test_validate_bbox_rejects_reversed_bounds():
    with pytest.raises(ValueError, match="min_lon"):
        validate_bbox([29.1, 40.9, 28.9, 41.1])
