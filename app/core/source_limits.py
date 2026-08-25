from __future__ import annotations

from functools import lru_cache

from app.core.rate_limit import AsyncTokenBucket
from app.core.settings import get_settings


@lru_cache
def ckan_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.ckan_rate_capacity,
        refill_per_second=settings.ckan_rate_refill_per_second,
        max_wait_seconds=settings.ckan_rate_max_wait_seconds,
    )


@lru_cache
def iett_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.iett_rate_capacity,
        refill_per_second=settings.iett_rate_refill_per_second,
        max_wait_seconds=settings.iett_rate_max_wait_seconds,
    )


@lru_cache
def air_quality_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.air_quality_rate_capacity,
        refill_per_second=settings.air_quality_rate_refill_per_second,
        max_wait_seconds=settings.air_quality_rate_max_wait_seconds,
    )


@lru_cache
def ispark_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.ispark_rate_capacity,
        refill_per_second=settings.ispark_rate_refill_per_second,
        max_wait_seconds=settings.ispark_rate_max_wait_seconds,
    )


@lru_cache
def metro_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.metro_rate_capacity,
        refill_per_second=settings.metro_rate_refill_per_second,
        max_wait_seconds=settings.metro_rate_max_wait_seconds,
    )


@lru_cache
def transport_notice_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.transport_notice_rate_capacity,
        refill_per_second=settings.transport_notice_rate_refill_per_second,
        max_wait_seconds=settings.transport_notice_rate_max_wait_seconds,
    )


@lru_cache
def traffic_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.traffic_rate_capacity,
        refill_per_second=settings.traffic_rate_refill_per_second,
        max_wait_seconds=settings.traffic_rate_max_wait_seconds,
    )


@lru_cache
def ieo_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.ieo_rate_capacity,
        refill_per_second=settings.ieo_rate_refill_per_second,
        max_wait_seconds=settings.ieo_rate_max_wait_seconds,
    )


@lru_cache
def social_facilities_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.social_facilities_rate_capacity,
        refill_per_second=settings.social_facilities_rate_refill_per_second,
        max_wait_seconds=settings.social_facilities_rate_max_wait_seconds,
    )


@lru_cache
def iski_rate_limiter() -> AsyncTokenBucket:
    settings = get_settings()
    return AsyncTokenBucket(
        capacity=settings.iski_rate_capacity,
        refill_per_second=settings.iski_rate_refill_per_second,
        max_wait_seconds=settings.iski_rate_max_wait_seconds,
    )
