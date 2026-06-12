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
    )
