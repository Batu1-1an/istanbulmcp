from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "istanbul-mcp"
    host: str = "0.0.0.0"
    port: int = 8000
    database_path: Path = Path(".data/istanbul_mcp.sqlite3")
    max_radius_m: int = 5000
    default_limit: int = 20
    max_limit: int = 100
    request_timeout_seconds: float = 15.0
    ckan_rate_capacity: int = 6
    ckan_rate_refill_per_second: float = 2.0
    ckan_rate_max_wait_seconds: float = 0.5
    iett_rate_capacity: int = 2
    iett_rate_refill_per_second: float = 0.5
    iett_rate_max_wait_seconds: float = 0.2
    ispark_cache_ttl_seconds: int = 300
    metro_cache_ttl_seconds: int = 86400
    air_quality_station_cache_ttl_seconds: int = 3600
    air_quality_reading_cache_ttl_seconds: int = 900
    traffic_cache_ttl_seconds: int = 60


def _int_env(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return int(value)


def _float_env(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return float(value)


@lru_cache
def get_settings() -> Settings:
    return Settings(
        app_name=os.getenv("APP_NAME", "istanbul-mcp"),
        host=os.getenv("HOST", "0.0.0.0"),
        port=_int_env("PORT", 8000),
        database_path=Path(os.getenv("DATABASE_PATH", ".data/istanbul_mcp.sqlite3")),
        max_radius_m=_int_env("MAX_RADIUS_M", 5000),
        default_limit=_int_env("DEFAULT_LIMIT", 20),
        max_limit=_int_env("MAX_LIMIT", 100),
        request_timeout_seconds=_float_env("REQUEST_TIMEOUT_SECONDS", 15.0),
        ckan_rate_capacity=_int_env("CKAN_RATE_CAPACITY", 6),
        ckan_rate_refill_per_second=_float_env("CKAN_RATE_REFILL_PER_SECOND", 2.0),
        ckan_rate_max_wait_seconds=_float_env("CKAN_RATE_MAX_WAIT_SECONDS", 0.5),
        iett_rate_capacity=_int_env("IETT_RATE_CAPACITY", 2),
        iett_rate_refill_per_second=_float_env("IETT_RATE_REFILL_PER_SECOND", 0.5),
        iett_rate_max_wait_seconds=_float_env("IETT_RATE_MAX_WAIT_SECONDS", 0.2),
        ispark_cache_ttl_seconds=_int_env("ISPARK_CACHE_TTL_SECONDS", 300),
        metro_cache_ttl_seconds=_int_env("METRO_CACHE_TTL_SECONDS", 86400),
        air_quality_station_cache_ttl_seconds=_int_env("AIR_QUALITY_STATION_CACHE_TTL_SECONDS", 3600),
        air_quality_reading_cache_ttl_seconds=_int_env("AIR_QUALITY_READING_CACHE_TTL_SECONDS", 900),
        traffic_cache_ttl_seconds=_int_env("TRAFFIC_CACHE_TTL_SECONDS", 60),
    )
