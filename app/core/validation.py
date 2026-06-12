from __future__ import annotations

from typing import Iterable


class InputValidationError(ValueError):
    def __init__(
        self,
        message: str,
        *,
        field: str,
        code: str = "validation_error",
        allowed_min: float | int | None = None,
        allowed_max: float | int | None = None,
    ):
        super().__init__(message)
        self.field = field
        self.code = code
        self.allowed_min = allowed_min
        self.allowed_max = allowed_max


def validate_lat_lon(lat: float, lon: float) -> tuple[float, float]:
    if not -90 <= lat <= 90:
        raise InputValidationError("lat must be between -90 and 90", field="lat", allowed_min=-90, allowed_max=90)
    if not -180 <= lon <= 180:
        raise InputValidationError("lon must be between -180 and 180", field="lon", allowed_min=-180, allowed_max=180)
    return lat, lon


def validate_radius(radius_m: int, max_radius_m: int = 5000) -> int:
    if radius_m <= 0:
        raise InputValidationError("radius_m must be positive", field="radius_m", allowed_min=1)
    if radius_m > max_radius_m:
        raise InputValidationError(f"radius_m must be <= {max_radius_m}", field="radius_m", allowed_max=max_radius_m)
    return radius_m


def validate_limit(limit: int, max_limit: int = 100) -> int:
    if limit <= 0:
        raise InputValidationError("limit must be positive", field="limit", allowed_min=1)
    if limit > max_limit:
        raise InputValidationError(f"limit must be <= {max_limit}", field="limit", allowed_max=max_limit)
    return limit


def validate_bbox(bbox: Iterable[float]) -> tuple[float, float, float, float]:
    values = tuple(float(v) for v in bbox)
    if len(values) != 4:
        raise InputValidationError("bbox must contain min_lon, min_lat, max_lon, max_lat", field="bbox")
    min_lon, min_lat, max_lon, max_lat = values
    validate_lat_lon(min_lat, min_lon)
    validate_lat_lon(max_lat, max_lon)
    if min_lon >= max_lon:
        raise InputValidationError("bbox min_lon must be less than max_lon", field="bbox")
    if min_lat >= max_lat:
        raise InputValidationError("bbox min_lat must be less than max_lat", field="bbox")
    return min_lon, min_lat, max_lon, max_lat
