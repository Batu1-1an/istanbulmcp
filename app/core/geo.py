from __future__ import annotations

import math
import re

EARTH_RADIUS_M = 6_371_000
WKT_POINT_RE = re.compile(r"POINT\s*\(\s*([0-9.\-]+)\s+([0-9.\-]+)\s*\)", re.I)


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    d_phi = math.radians(lat2 - lat1)
    d_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def radius_bbox(lat: float, lon: float, radius_m: int) -> tuple[float, float, float, float]:
    delta_lat = math.degrees(radius_m / EARTH_RADIUS_M)
    cos_lat = max(math.cos(math.radians(lat)), 0.000001)
    delta_lon = math.degrees(radius_m / (EARTH_RADIUS_M * cos_lat))
    return lon - delta_lon, lat - delta_lat, lon + delta_lon, lat + delta_lat


def parse_wkt_point(value: str | None) -> tuple[float, float] | None:
    if not value:
        return None
    match = WKT_POINT_RE.search(value)
    if not match:
        return None
    lon = float(match.group(1))
    lat = float(match.group(2))
    return lat, lon
