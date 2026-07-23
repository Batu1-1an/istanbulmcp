from __future__ import annotations

import asyncio
import hashlib
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class CacheEntry:
    value: Any
    refreshed_at_monotonic: float
    expires_at_monotonic: float
    refreshed_at_iso: str
    metadata: dict[str, Any] | None = None
    max_age_at_monotonic: float | None = None


@dataclass(frozen=True)
class CachedSourceData:
    value: Any
    refreshed_at_iso: str | None
    is_fresh: bool
    is_stale: bool
    error: Exception | None = None
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class SourceLoadResult:
    value: Any
    metadata: dict[str, Any] | None = None
    max_cache_age_seconds: float | None = None


class SourceTTLCache:
    def __init__(self):
        self._entries: dict[str, CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def get(
        self,
        key: str,
        *,
        ttl_seconds: int,
        max_entries: int,
        loader: Callable[[], Awaitable[Any]],
    ) -> Any:
        result = await self.get_with_status(
            key,
            ttl_seconds=ttl_seconds,
            max_entries=max_entries,
            loader=loader,
        )
        return result.value

    async def get_with_status(
        self,
        key: str,
        *,
        ttl_seconds: int,
        max_entries: int,
        loader: Callable[[], Awaitable[Any]],
        stale_if_error_seconds: int = 0,
    ) -> CachedSourceData:
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None and now < entry.expires_at_monotonic:
            return CachedSourceData(
                value=entry.value,
                refreshed_at_iso=entry.refreshed_at_iso,
                is_fresh=True,
                is_stale=False,
                metadata=entry.metadata,
            )

        lock = self._locks.setdefault(key, asyncio.Lock())
        try:
            async with lock:
                now = time.monotonic()
                entry = self._entries.get(key)
                if entry is not None and now < entry.expires_at_monotonic:
                    return CachedSourceData(
                        value=entry.value,
                        refreshed_at_iso=entry.refreshed_at_iso,
                        is_fresh=True,
                        is_stale=False,
                        metadata=entry.metadata,
                    )

                value = await loader()
                metadata = None
                max_cache_age_seconds = None
                if isinstance(value, SourceLoadResult):
                    metadata = value.metadata
                    max_cache_age_seconds = value.max_cache_age_seconds
                    value = value.value
                refreshed_at = datetime.now(timezone.utc).isoformat()
                self._evict_before_insert(max_entries=max_entries, now=now)
                max_age_at = (
                    now + max(0.0, max_cache_age_seconds)
                    if max_cache_age_seconds is not None
                    else None
                )
                expires_at = now + ttl_seconds
                if max_age_at is not None:
                    expires_at = min(expires_at, max_age_at)
                self._entries[key] = CacheEntry(
                    value=value,
                    refreshed_at_monotonic=now,
                    expires_at_monotonic=expires_at,
                    refreshed_at_iso=refreshed_at,
                    metadata=metadata,
                    max_age_at_monotonic=max_age_at,
                )
                return CachedSourceData(
                    value=value,
                    refreshed_at_iso=refreshed_at,
                    is_fresh=True,
                    is_stale=False,
                    metadata=metadata,
                )
        except Exception as exc:
            stale_entry = self._entries.get(key)
            stale_deadline = (
                stale_entry.expires_at_monotonic + stale_if_error_seconds
                if stale_entry is not None
                else 0
            )
            if stale_entry is not None and stale_entry.max_age_at_monotonic is not None:
                stale_deadline = min(stale_deadline, stale_entry.max_age_at_monotonic)
            if (
                stale_entry is not None
                and stale_if_error_seconds > 0
                and time.monotonic() <= stale_deadline
            ):
                return CachedSourceData(
                    value=stale_entry.value,
                    refreshed_at_iso=stale_entry.refreshed_at_iso,
                    is_fresh=False,
                    is_stale=True,
                    error=exc,
                    metadata=stale_entry.metadata,
                )
            if self._entries.get(key) is None:
                self._locks.pop(key, None)
            raise

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        rows = []
        for key, entry in sorted(self._entries.items()):
            rows.append(
                {
                    "source": _source_label(key),
                    "cache_key_hash": _cache_key_hash(key),
                    "refreshed_at": entry.refreshed_at_iso,
                    "expires_in_seconds": max(0, round(entry.expires_at_monotonic - now, 3)),
                    "is_fresh": now < entry.expires_at_monotonic,
                }
            )
        return rows

    def _evict_before_insert(self, *, max_entries: int, now: float) -> None:
        max_entries = max(1, int(max_entries))
        expired = [key for key, entry in self._entries.items() if now >= entry.expires_at_monotonic]
        for key in expired:
            self._entries.pop(key, None)
            self._locks.pop(key, None)
        while len(self._entries) >= max_entries:
            oldest = min(
                self._entries,
                key=lambda key: (self._entries[key].expires_at_monotonic, self._entries[key].refreshed_at_monotonic),
            )
            self._entries.pop(oldest, None)
            self._locks.pop(oldest, None)

    def clear(self) -> None:
        self._entries.clear()
        self._locks.clear()


source_cache = SourceTTLCache()


async def cached_source_data(
    key: str,
    *,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[Any]],
) -> Any:
    from app.core.settings import get_settings

    return await source_cache.get(
        key,
        ttl_seconds=ttl_seconds,
        max_entries=get_settings().source_cache_max_entries,
        loader=loader,
    )


async def cached_source_data_with_status(
    key: str,
    *,
    ttl_seconds: int,
    loader: Callable[[], Awaitable[Any]],
    stale_if_error_seconds: int = 0,
) -> CachedSourceData:
    from app.core.settings import get_settings

    return await source_cache.get_with_status(
        key,
        ttl_seconds=ttl_seconds,
        max_entries=get_settings().source_cache_max_entries,
        loader=loader,
        stale_if_error_seconds=stale_if_error_seconds,
    )


def source_cache_snapshot() -> list[dict[str, Any]]:
    return source_cache.snapshot()


def clear_source_cache() -> None:
    source_cache.clear()


def _cache_key_hash(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


def _source_label(key: str) -> str:
    parts = key.split(".")
    if len(parts) >= 2:
        return ".".join(parts[:2])
    return key
