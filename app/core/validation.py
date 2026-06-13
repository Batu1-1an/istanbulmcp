from __future__ import annotations

import re
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


def validate_text(value: str, *, field: str, max_length: int, min_length: int = 1) -> str:
    text = str(value or "").strip()
    if len(text) < min_length:
        raise InputValidationError(f"{field} is required", field=field, allowed_min=min_length)
    if len(text) > max_length:
        raise InputValidationError(f"{field} must be <= {max_length} characters", field=field, allowed_max=max_length)
    return text


def validate_identifier(value: str, *, field: str, max_length: int = 120) -> str:
    text = validate_text(value, field=field, max_length=max_length)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", text):
        raise InputValidationError(f"{field} contains unsupported characters", field=field)
    return text


def validate_line_code(value: str, *, max_length: int = 20) -> str:
    text = validate_text(value, field="line_code", max_length=max_length).upper()
    if not re.fullmatch(r"[0-9A-Z._-]+", text):
        raise InputValidationError("line_code contains unsupported characters", field="line_code")
    return text


def validate_filters(filters: dict | None, *, max_keys: int = 10, max_key_length: int = 80, max_value_length: int = 200, max_list_items: int = 20) -> dict | None:
    if filters is None:
        return None
    if not isinstance(filters, dict):
        raise InputValidationError("filters must be an object", field="filters")
    if len(filters) > max_keys:
        raise InputValidationError(f"filters must contain <= {max_keys} keys", field="filters", allowed_max=max_keys)

    safe_filters = {}
    for key, value in filters.items():
        safe_key = validate_text(str(key), field="filters", max_length=max_key_length)
        if not re.fullmatch(r"[\w .:-]+", safe_key, flags=re.UNICODE):
            raise InputValidationError("filter key contains unsupported characters", field="filters")
        safe_filters[safe_key] = _validate_filter_value(value, max_value_length=max_value_length, max_list_items=max_list_items, allow_list=True)
    return safe_filters


def _validate_filter_value(value, *, max_value_length: int, max_list_items: int, allow_list: bool):
    if isinstance(value, (str, int, float, bool)) or value is None:
        if isinstance(value, str):
            return validate_text(value, field="filters", max_length=max_value_length, min_length=0)
        return value
    if isinstance(value, list) and allow_list:
        if len(value) > max_list_items:
            raise InputValidationError(f"filter lists must contain <= {max_list_items} items", field="filters", allowed_max=max_list_items)
        return [
            _validate_filter_value(item, max_value_length=max_value_length, max_list_items=max_list_items, allow_list=False)
            for item in value
        ]
    raise InputValidationError("filter values must be scalars or scalar lists", field="filters")


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
