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
