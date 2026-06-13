from __future__ import annotations

import asyncio
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
        now = time.monotonic()
        entry = self._entries.get(key)
        if entry is not None and now < entry.expires_at_monotonic:
            return entry.value

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            now = time.monotonic()
            entry = self._entries.get(key)
            if entry is not None and now < entry.expires_at_monotonic:
                return entry.value

            value = await loader()
            refreshed_at = datetime.now(timezone.utc).isoformat()
            self._evict_before_insert(max_entries=max_entries, now=now)
            self._entries[key] = CacheEntry(
                value=value,
                refreshed_at_monotonic=now,
                expires_at_monotonic=now + ttl_seconds,
                refreshed_at_iso=refreshed_at,
            )
            return value

    def snapshot(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        rows = []
        for key, entry in sorted(self._entries.items()):
            rows.append(
                {
                    "source": key,
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


def source_cache_snapshot() -> list[dict[str, Any]]:
    return source_cache.snapshot()


def clear_source_cache() -> None:
    source_cache.clear()
