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
    air_quality_rate_capacity: int = 4
    air_quality_rate_refill_per_second: float = 1.0
    air_quality_rate_max_wait_seconds: float = 0.5
    ispark_rate_capacity: int = 4
    ispark_rate_refill_per_second: float = 1.0
    ispark_rate_max_wait_seconds: float = 0.5
    metro_rate_capacity: int = 4
    metro_rate_refill_per_second: float = 1.0
    metro_rate_max_wait_seconds: float = 0.5
    traffic_rate_capacity: int = 2
    traffic_rate_refill_per_second: float = 0.5
    traffic_rate_max_wait_seconds: float = 0.5
    iski_request_timeout_seconds: float = 5.0
    iski_request_attempts: int = 1
    iski_api_base_url: str = "https://iskiapi.iski.istanbul/api"
    iski_api_bearer_token: str | None = None
    iski_relay_base_url: str | None = None
    iski_relay_token: str | None = None
    iski_relay_timeout_seconds: float = 15.0
    iski_faults_snapshot_json: str | None = None
    iski_dams_snapshot_json: str | None = None
    iski_faults_snapshot_captured_at: str | None = None
    iski_dams_snapshot_captured_at: str | None = None
    iski_faults_snapshot_max_age_seconds: int = 21600
    iski_dams_snapshot_max_age_seconds: int = 86400
    iski_rate_capacity: int = 4
    iski_rate_refill_per_second: float = 1.0
    iski_rate_max_wait_seconds: float = 0.5
    ispark_cache_ttl_seconds: int = 300
    metro_cache_ttl_seconds: int = 86400
    air_quality_station_cache_ttl_seconds: int = 3600
    air_quality_reading_cache_ttl_seconds: int = 900
    traffic_cache_ttl_seconds: int = 60
    istanbulkart_dataset_id: str = "istanbulkart-dolum-merkezi-bilgileri"
    istanbulkart_resource_id: str | None = None
    istanbulkart_datastore_page_size: int = 100
    istanbulkart_cache_ttl_seconds: int = 86400
    istanbulkart_stale_if_error_seconds: int = 604800
    social_facilities_base_url: str = "https://tesislerimiz.ibb.istanbul"
    social_facilities_catalog_url: str = "https://tesislerimiz.ibb.istanbul/tesisler"
    social_facilities_reservation_url: str = "https://tesislerrezervasyon.ibb.istanbul/"
    social_facilities_ckan_download_url: str = "https://data.ibb.gov.tr/dataset/6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d/resource/87517b4e-28b5-478f-a0ba-27291cf17b69/download/ibb-sosyal-tesis-konumlar.xlsx"
    social_facilities_request_timeout_seconds: float = 15.0
    social_facilities_request_attempts: int = 2
    social_facilities_cache_ttl_seconds: int = 86400
    social_facilities_stale_if_error_seconds: int = 604800
    social_facilities_rate_capacity: int = 4
    social_facilities_rate_refill_per_second: float = 0.5
    social_facilities_rate_max_wait_seconds: float = 0.5
    social_facilities_max_catalog_pages: int = 10
    social_facilities_max_detail_pages: int = 100
    ieo_base_url: str = "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php"
    ieo_request_timeout_seconds: float = 15.0
    ieo_request_attempts: int = 2
    ieo_cache_ttl_seconds: int = 300
    ieo_stale_if_error_seconds: int = 1800
    ieo_rate_capacity: int = 2
    ieo_rate_refill_per_second: float = 0.5
    ieo_rate_max_wait_seconds: float = 0.5
    iski_faults_cache_ttl_seconds: int = 30
    iski_dams_cache_ttl_seconds: int = 60
    iski_faults_stale_if_error_seconds: int = 900
    iski_dams_stale_if_error_seconds: int = 86400
    ckan_catalog_cache_ttl_seconds: int = 900
    ckan_resource_cache_ttl_seconds: int = 900
    iett_line_cache_ttl_seconds: int = 900
    iett_stops_cache_ttl_seconds: int = 900
    transport_disruptions_cache_ttl_seconds: int = 120
    metro_accessibility_cache_ttl_seconds: int = 120
    metro_accessibility_stale_if_error_seconds: int = 900
    ferry_schedule_cache_ttl_seconds: int = 120
    ferry_schedule_default_limit: int = 50
    ferry_schedule_max_limit: int = 100
    transport_notice_rate_capacity: int = 2
    transport_notice_rate_refill_per_second: float = 0.5
    transport_notice_rate_max_wait_seconds: float = 0.2
    marmaray_api_basic_token: str | None = None
    sehir_hatlari_relay_url: str | None = None
    sehir_hatlari_relay_token: str | None = None
    source_cache_max_entries: int = 1024
    mcp_max_body_bytes: int = 256 * 1024
    mcp_rate_limit_capacity: int = 60
    mcp_rate_limit_refill_per_second: float = 1.0
    mcp_rate_limit_max_clients: int = 2048
    mcp_max_concurrent_requests: int = 25


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


def _str_env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    return value


def _joined_env_parts(prefix: str) -> str | None:
    direct = _str_env(prefix)
    if direct is not None:
        return direct

    parts: list[str] = []
    index = 1
    while True:
        value = _str_env(f"{prefix}_PART_{index}")
        if value is None:
            break
        parts.append(value)
        index += 1

    if not parts:
        return None
    return "".join(parts)


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
        air_quality_rate_capacity=_int_env("AIR_QUALITY_RATE_CAPACITY", 4),
        air_quality_rate_refill_per_second=_float_env("AIR_QUALITY_RATE_REFILL_PER_SECOND", 1.0),
        air_quality_rate_max_wait_seconds=_float_env("AIR_QUALITY_RATE_MAX_WAIT_SECONDS", 0.5),
        ispark_rate_capacity=_int_env("ISPARK_RATE_CAPACITY", 4),
        ispark_rate_refill_per_second=_float_env("ISPARK_RATE_REFILL_PER_SECOND", 1.0),
        ispark_rate_max_wait_seconds=_float_env("ISPARK_RATE_MAX_WAIT_SECONDS", 0.5),
        metro_rate_capacity=_int_env("METRO_RATE_CAPACITY", 4),
        metro_rate_refill_per_second=_float_env("METRO_RATE_REFILL_PER_SECOND", 1.0),
        metro_rate_max_wait_seconds=_float_env("METRO_RATE_MAX_WAIT_SECONDS", 0.5),
        traffic_rate_capacity=_int_env("TRAFFIC_RATE_CAPACITY", 2),
        traffic_rate_refill_per_second=_float_env("TRAFFIC_RATE_REFILL_PER_SECOND", 0.5),
        traffic_rate_max_wait_seconds=_float_env("TRAFFIC_RATE_MAX_WAIT_SECONDS", 0.5),
        iski_request_timeout_seconds=_float_env("ISKI_REQUEST_TIMEOUT_SECONDS", 5.0),
        iski_request_attempts=_int_env("ISKI_REQUEST_ATTEMPTS", 1),
        iski_api_base_url=os.getenv("ISKI_API_BASE_URL", "https://iskiapi.iski.istanbul/api"),
        iski_api_bearer_token=_str_env("ISKI_API_BEARER_TOKEN"),
        iski_relay_base_url=_str_env("ISKI_RELAY_BASE_URL"),
        iski_relay_token=_str_env("ISKI_RELAY_TOKEN"),
        iski_relay_timeout_seconds=_float_env("ISKI_RELAY_TIMEOUT_SECONDS", 15.0),
        iski_faults_snapshot_json=_joined_env_parts("ISKI_FAULTS_SNAPSHOT_JSON"),
        iski_dams_snapshot_json=_joined_env_parts("ISKI_DAMS_SNAPSHOT_JSON"),
        iski_faults_snapshot_captured_at=_str_env("ISKI_FAULTS_SNAPSHOT_CAPTURED_AT"),
        iski_dams_snapshot_captured_at=_str_env("ISKI_DAMS_SNAPSHOT_CAPTURED_AT"),
        iski_faults_snapshot_max_age_seconds=_int_env("ISKI_FAULTS_SNAPSHOT_MAX_AGE_SECONDS", 21600),
        iski_dams_snapshot_max_age_seconds=_int_env("ISKI_DAMS_SNAPSHOT_MAX_AGE_SECONDS", 86400),
        iski_rate_capacity=_int_env("ISKI_RATE_CAPACITY", 4),
        iski_rate_refill_per_second=_float_env("ISKI_RATE_REFILL_PER_SECOND", 1.0),
        iski_rate_max_wait_seconds=_float_env("ISKI_RATE_MAX_WAIT_SECONDS", 0.5),
        ispark_cache_ttl_seconds=_int_env("ISPARK_CACHE_TTL_SECONDS", 300),
        metro_cache_ttl_seconds=_int_env("METRO_CACHE_TTL_SECONDS", 86400),
        air_quality_station_cache_ttl_seconds=_int_env("AIR_QUALITY_STATION_CACHE_TTL_SECONDS", 3600),
        air_quality_reading_cache_ttl_seconds=_int_env("AIR_QUALITY_READING_CACHE_TTL_SECONDS", 900),
        traffic_cache_ttl_seconds=_int_env("TRAFFIC_CACHE_TTL_SECONDS", 60),
        istanbulkart_dataset_id=os.getenv(
            "ISTANBULKART_DATASET_ID", "istanbulkart-dolum-merkezi-bilgileri"
        ),
        istanbulkart_resource_id=_str_env("ISTANBULKART_RESOURCE_ID"),
        istanbulkart_datastore_page_size=_int_env("ISTANBULKART_DATASTORE_PAGE_SIZE", 100),
        istanbulkart_cache_ttl_seconds=_int_env("ISTANBULKART_CACHE_TTL_SECONDS", 86400),
        istanbulkart_stale_if_error_seconds=_int_env(
            "ISTANBULKART_STALE_IF_ERROR_SECONDS", 604800
        ),
        social_facilities_base_url=os.getenv(
            "SOCIAL_FACILITIES_BASE_URL", "https://tesislerimiz.ibb.istanbul"
        ),
        social_facilities_catalog_url=os.getenv(
            "SOCIAL_FACILITIES_CATALOG_URL", "https://tesislerimiz.ibb.istanbul/tesisler"
        ),
        social_facilities_reservation_url=os.getenv(
            "SOCIAL_FACILITIES_RESERVATION_URL", "https://tesislerrezervasyon.ibb.istanbul/"
        ),
        social_facilities_ckan_download_url=os.getenv(
            "SOCIAL_FACILITIES_CKAN_DOWNLOAD_URL",
            "https://data.ibb.gov.tr/dataset/6e9b0cf3-d756-4301-8c5e-a6e3a223ed6d/resource/87517b4e-28b5-478f-a0ba-27291cf17b69/download/ibb-sosyal-tesis-konumlar.xlsx",
        ),
        social_facilities_request_timeout_seconds=_float_env(
            "SOCIAL_FACILITIES_REQUEST_TIMEOUT_SECONDS", 15.0
        ),
        social_facilities_request_attempts=_int_env("SOCIAL_FACILITIES_REQUEST_ATTEMPTS", 2),
        social_facilities_cache_ttl_seconds=_int_env("SOCIAL_FACILITIES_CACHE_TTL_SECONDS", 86400),
        social_facilities_stale_if_error_seconds=_int_env(
            "SOCIAL_FACILITIES_STALE_IF_ERROR_SECONDS", 604800
        ),
        social_facilities_rate_capacity=_int_env("SOCIAL_FACILITIES_RATE_CAPACITY", 4),
        social_facilities_rate_refill_per_second=_float_env(
            "SOCIAL_FACILITIES_RATE_REFILL_PER_SECOND", 0.5
        ),
        social_facilities_rate_max_wait_seconds=_float_env(
            "SOCIAL_FACILITIES_RATE_MAX_WAIT_SECONDS", 0.5
        ),
        social_facilities_max_catalog_pages=_int_env("SOCIAL_FACILITIES_MAX_CATALOG_PAGES", 10),
        social_facilities_max_detail_pages=_int_env("SOCIAL_FACILITIES_MAX_DETAIL_PAGES", 100),
        ieo_base_url=os.getenv(
            "IEO_BASE_URL",
            "https://www.istanbuleczaciodasi.org.tr/nobetci-eczane/index.php",
        ),
        ieo_request_timeout_seconds=_float_env("IEO_REQUEST_TIMEOUT_SECONDS", 15.0),
        ieo_request_attempts=_int_env("IEO_REQUEST_ATTEMPTS", 2),
        ieo_cache_ttl_seconds=_int_env("IEO_CACHE_TTL_SECONDS", 300),
        ieo_stale_if_error_seconds=_int_env("IEO_STALE_IF_ERROR_SECONDS", 1800),
        ieo_rate_capacity=_int_env("IEO_RATE_CAPACITY", 2),
        ieo_rate_refill_per_second=_float_env("IEO_RATE_REFILL_PER_SECOND", 0.5),
        ieo_rate_max_wait_seconds=_float_env("IEO_RATE_MAX_WAIT_SECONDS", 0.5),
        iski_faults_cache_ttl_seconds=_int_env("ISKI_FAULTS_CACHE_TTL_SECONDS", 30),
        iski_dams_cache_ttl_seconds=_int_env("ISKI_DAMS_CACHE_TTL_SECONDS", 60),
        iski_faults_stale_if_error_seconds=_int_env("ISKI_FAULTS_STALE_IF_ERROR_SECONDS", 900),
        iski_dams_stale_if_error_seconds=_int_env("ISKI_DAMS_STALE_IF_ERROR_SECONDS", 86400),
        ckan_catalog_cache_ttl_seconds=_int_env("CKAN_CATALOG_CACHE_TTL_SECONDS", 900),
        ckan_resource_cache_ttl_seconds=_int_env("CKAN_RESOURCE_CACHE_TTL_SECONDS", 900),
        iett_line_cache_ttl_seconds=_int_env("IETT_LINE_CACHE_TTL_SECONDS", 900),
        iett_stops_cache_ttl_seconds=_int_env("IETT_STOPS_CACHE_TTL_SECONDS", 900),
        transport_disruptions_cache_ttl_seconds=_int_env("TRANSPORT_DISRUPTIONS_CACHE_TTL_SECONDS", 120),
        metro_accessibility_cache_ttl_seconds=_int_env("METRO_ACCESSIBILITY_CACHE_TTL_SECONDS", 120),
        metro_accessibility_stale_if_error_seconds=_int_env("METRO_ACCESSIBILITY_STALE_IF_ERROR_SECONDS", 900),
        ferry_schedule_cache_ttl_seconds=_int_env("FERRY_SCHEDULE_CACHE_TTL_SECONDS", 120),
        ferry_schedule_default_limit=_int_env("FERRY_SCHEDULE_DEFAULT_LIMIT", 50),
        ferry_schedule_max_limit=_int_env("FERRY_SCHEDULE_MAX_LIMIT", 100),
        transport_notice_rate_capacity=_int_env("TRANSPORT_NOTICE_RATE_CAPACITY", 2),
        transport_notice_rate_refill_per_second=_float_env("TRANSPORT_NOTICE_RATE_REFILL_PER_SECOND", 0.5),
        transport_notice_rate_max_wait_seconds=_float_env("TRANSPORT_NOTICE_RATE_MAX_WAIT_SECONDS", 0.2),
        marmaray_api_basic_token=_str_env("MARMARAY_API_BASIC_TOKEN"),
        sehir_hatlari_relay_url=_str_env("SEHIR_HATLARI_RELAY_URL"),
        sehir_hatlari_relay_token=_str_env("SEHIR_HATLARI_RELAY_TOKEN"),
        source_cache_max_entries=_int_env("SOURCE_CACHE_MAX_ENTRIES", 1024),
        mcp_max_body_bytes=_int_env("MCP_MAX_BODY_BYTES", 256 * 1024),
        mcp_rate_limit_capacity=_int_env("MCP_RATE_LIMIT_CAPACITY", 60),
        mcp_rate_limit_refill_per_second=_float_env("MCP_RATE_LIMIT_REFILL_PER_SECOND", 1.0),
        mcp_rate_limit_max_clients=_int_env("MCP_RATE_LIMIT_MAX_CLIENTS", 2048),
        mcp_max_concurrent_requests=_int_env("MCP_MAX_CONCURRENT_REQUESTS", 25),
    )
