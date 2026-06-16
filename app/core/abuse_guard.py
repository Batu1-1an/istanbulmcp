from __future__ import annotations

import asyncio
import ipaddress
import time
from dataclasses import dataclass
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send


@dataclass
class ClientBucket:
    tokens: float
    updated_at: float
    last_seen_at: float


class ClientRateLimiter:
    def __init__(self, *, capacity: int, refill_per_second: float, max_clients: int):
        self.capacity = max(1, int(capacity))
        self.refill_per_second = max(0.001, float(refill_per_second))
        self.max_clients = max(1, int(max_clients))
        self._clients: dict[str, ClientBucket] = {}
        self._lock = asyncio.Lock()

    async def acquire(self, client_id: str) -> tuple[bool, float]:
        now = time.monotonic()
        async with self._lock:
            self._prune_locked(now)
            bucket = self._clients.get(client_id)
            if bucket is None:
                bucket = ClientBucket(tokens=float(self.capacity), updated_at=now, last_seen_at=now)
                self._clients[client_id] = bucket

            elapsed = max(0.0, now - bucket.updated_at)
            bucket.tokens = min(float(self.capacity), bucket.tokens + elapsed * self.refill_per_second)
            bucket.updated_at = now
            bucket.last_seen_at = now

            if bucket.tokens >= 1.0:
                bucket.tokens -= 1.0
                return True, 0.0
            return False, (1.0 - bucket.tokens) / self.refill_per_second

    def snapshot(self) -> dict[str, Any]:
        return {
            "tracked_clients": len(self._clients),
            "capacity": self.capacity,
            "refill_per_second": self.refill_per_second,
            "max_clients": self.max_clients,
        }

    def _prune_locked(self, now: float) -> None:
        if len(self._clients) < self.max_clients:
            return
        stale_before = now - max(60.0, self.capacity / self.refill_per_second)
        stale = [client_id for client_id, bucket in self._clients.items() if bucket.last_seen_at < stale_before]
        for client_id in stale:
            self._clients.pop(client_id, None)
        while len(self._clients) >= self.max_clients:
            oldest = min(self._clients, key=lambda key: self._clients[key].last_seen_at)
            self._clients.pop(oldest, None)


class ConcurrencyLimiter:
    def __init__(self, *, max_concurrent: int):
        self.max_concurrent = max(1, int(max_concurrent))
        self.current = 0
        self.rejected = 0
        self._lock = asyncio.Lock()

    async def acquire(self) -> bool:
        async with self._lock:
            if self.current >= self.max_concurrent:
                self.rejected += 1
                return False
            self.current += 1
            return True

    async def release(self) -> None:
        async with self._lock:
            self.current = max(0, self.current - 1)

    def snapshot(self) -> dict[str, Any]:
        return {
            "current": self.current,
            "max_concurrent": self.max_concurrent,
            "rejected": self.rejected,
        }


class McpAbuseGuardMiddleware:
    def __init__(
        self,
        app,
        *,
        max_body_bytes: int,
        rate_limiter: ClientRateLimiter,
        concurrency_limiter: ConcurrencyLimiter,
    ):
        self.app = app
        self.max_body_bytes = max(1, int(max_body_bytes))
        self.rate_limiter = rate_limiter
        self.concurrency_limiter = concurrency_limiter

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._should_guard(scope):
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._reject(scope, receive, send, status_code=413, summary="Request body is too large.")
            return

        client_id = self._client_id(scope)
        allowed, retry_after = await self.rate_limiter.acquire(client_id)
        if not allowed:
            await self._reject(
                scope,
                receive,
                send,
                status_code=429,
                summary="Too many MCP requests. Please retry shortly.",
                retry_after_seconds=retry_after,
            )
            return

        if not await self.concurrency_limiter.acquire():
            await self._reject(
                scope,
                receive,
                send,
                status_code=429,
                summary="MCP service is busy. Please retry shortly.",
                retry_after_seconds=1.0,
            )
            return

        body_size = 0

        async def limited_receive() -> Message:
            nonlocal body_size
            message = await receive()
            if message["type"] == "http.request":
                body_size += len(message.get("body", b""))
                if body_size > self.max_body_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await self._reject(scope, receive, send, status_code=413, summary="Request body is too large.")
        finally:
            await self.concurrency_limiter.release()

    def _should_guard(self, scope: Scope) -> bool:
        return scope.get("type") == "http" and scope.get("method") == "POST" and scope.get("path") in {"/mcp", "/mcp/"}

    def _content_length(self, scope: Scope) -> int | None:
        for key, value in scope.get("headers", []):
            if key.lower() == b"content-length":
                try:
                    return int(value.decode("latin-1"))
                except ValueError:
                    return None
        return None

    def _client_id(self, scope: Scope) -> str:
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        for header in ("x-real-ip", "cf-connecting-ip"):
            if client_ip := self._trusted_header_ip(headers.get(header)):
                return client_ip
        client = scope.get("client")
        if isinstance(client, tuple) and client:
            return str(client[0])
        return "unknown"

    def _trusted_header_ip(self, value: str | None) -> str | None:
        if not value:
            return None
        candidate = value.strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            return None

    async def _reject(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
        *,
        status_code: int,
        summary: str,
        retry_after_seconds: float | None = None,
    ) -> None:
        data = []
        headers: dict[str, str] = {}
        if retry_after_seconds is not None:
            retry_after = max(1, round(retry_after_seconds))
            data.append({"retry_after_seconds": retry_after})
            headers["retry-after"] = str(retry_after)
        response = JSONResponse(
            {
                "ok": False,
                "summary": summary,
                "data": data,
                "warnings": [summary],
            },
            status_code=status_code,
            headers=headers,
        )
        await response(scope, receive, send)


class RequestBodyTooLarge(Exception):
    pass
