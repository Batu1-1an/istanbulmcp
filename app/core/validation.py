from __future__ import annotations

from typing import Iterable


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    if not -90 <= lat <= 90:
        raise ValueError("lat must be between -90 and 90")
    if not -180 <= lon <= 180:
        raise ValueError("lon must be between -180 and 180")
    return lat, lon


def validate_radius(radius_m: int, max_radius_m: int = 5000) -> int:
    if radius_m <= 0:
        raise ValueError("radius_m must be positive")
    if radius_m > max_radius_m:
        raise ValueError(f"radius_m must be <= {max_radius_m}")
    return radius_m


def validate_limit(limit: int, max_limit: int = 100) -> int:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if limit > max_limit:
        raise ValueError(f"limit must be <= {max_limit}")
    return limit


def validate_bbox(bbox: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(v) for v in bbox)
    if len(values) != 4:
        raise ValueError("bbox must contain min_lon, min_lat, max_lon, max_lat")
    min_lon, min_lat, max_lon, max_lat = values
    validate_lat_lon(min_lat, min_lon)
    validate_lat_lon(max_lat, max_lon)
    if min_lon >= max_lon:
        raise ValueError("bbox min_lon must be less than max_lon")
    if min_lat >= max_lat:
        raise ValueError("bbox min_lat must be less than max_lat")
    return min_lon, min_lat, max_lon, max_lat
