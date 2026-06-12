from __future__ import annotations

import asyncio
import time
from typing import Protocol


class SourceRateLimitExceeded(RuntimeError):
    def __init__(self, *, source: str, retry_after_seconds: float):
        super().__init__(f"{source} rate limit exceeded")
        self.source = source
        self.retry_after_seconds = max(0.0, retry_after_seconds)


class RateLimiter(Protocol):
    async def acquire(self, source: str) -> None:
        ...

    def penalize(self, retry_after_seconds: float) -> None:
        ...


class AsyncTokenBucket:
    def __init__(
        self,
        *,
        capacity: int,
        refill_per_second: float,
        max_wait_seconds: float,
    ):
        if capacity < 1:
            raise ValueError("capacity must be at least 1")
        if refill_per_second <= 0:
            raise ValueError("refill_per_second must be positive")
        self.capacity = float(capacity)
        self.refill_per_second = float(refill_per_second)
        self.max_wait_seconds = float(max_wait_seconds)
        self._tokens = float(capacity)
        self._updated_at = time.monotonic()
        self._blocked_until = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self, source: str) -> None:
        async with self._lock:
            retry_after = self._retry_after_locked()
            if retry_after <= 0:
                self._tokens -= 1.0
                return
            if retry_after > self.max_wait_seconds:
                raise SourceRateLimitExceeded(
                    source=source,
                    retry_after_seconds=retry_after,
                )

        await asyncio.sleep(retry_after)
        await self.acquire(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self._blocked_until = max(
            self._blocked_until,
            time.monotonic() + max(0.0, retry_after_seconds),
        )

    def _retry_after_locked(self) -> float:
        now = time.monotonic()
        elapsed = max(0.0, now - self._updated_at)
        self._tokens = min(self.capacity, self._tokens + elapsed * self.refill_per_second)
        self._updated_at = now

        if now < self._blocked_until:
            return self._blocked_until - now
        if self._tokens >= 1.0:
            return 0.0
        return (1.0 - self._tokens) / self.refill_per_second
