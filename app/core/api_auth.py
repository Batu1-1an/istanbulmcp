"""Static Bearer API keys, deliberately not an OAuth authorization server."""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import re
import sqlite3

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.settings import Settings
from app.storage.quota import DailyQuota

KEY_ID = "istanbul.api_key_id"
KEY_PATTERN = re.compile(r"[A-Za-z0-9._~-]{32,256}", re.ASCII)


def validate_auth_settings(settings: Settings) -> bool:
    keys = settings.mcp_api_keys
    if settings.mcp_auth_required and not keys:
        raise ValueError("MCP_AUTH_REQUIRED=true requires MCP_API_KEYS; omit both for the default public mode")
    if len(keys) > 100 or len(set(keys)) != len(keys) or any(not KEY_PATTERN.fullmatch(key) for key in keys):
        raise ValueError("MCP_API_KEYS must contain 1-100 unique 32-256 character URL-safe keys")
    if settings.mcp_api_key_daily_quota <= 0 and (keys or settings.mcp_auth_required):
        raise ValueError("MCP_API_KEY_DAILY_QUOTA must be positive")
    # Keys alone switch authentication on, so a configured key is never ignored.
    return bool(keys)


class ApiKeyAuthMiddleware:
    def __init__(self, app: ASGIApp, *, keys: tuple[str, ...]):
        self.app = app
        # Keep no plaintext credentials in middleware state or quota storage.
        self.key_hashes = tuple(hashlib.sha256(key.encode("ascii")).hexdigest() for key in keys)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = scope.get("path", "")
        protected = path == "/status" or path == "/mcp" or path.startswith("/mcp/")
        if scope["type"] != "http" or not protected or not self.key_hashes:
            await self.app(scope, receive, send)
            return
        headers = [value.decode("latin-1") for key, value in scope.get("headers", [])
                   if key.lower() == b"authorization"]
        matched = None
        if len(headers) == 1:
            parts = headers[0].split(" ")
            if len(parts) == 2 and parts[0].lower() == "bearer" and KEY_PATTERN.fullmatch(parts[1]):
                candidate = hashlib.sha256(parts[1].encode("ascii")).hexdigest()
                for key_hash in self.key_hashes:
                    if hmac.compare_digest(candidate, key_hash):
                        matched = key_hash
        if matched is None:
            response = JSONResponse(
                {"ok": False, "error_code": "unauthorized", "summary": "A valid Bearer API key is required."},
                status_code=401, headers={"WWW-Authenticate": 'Bearer realm="istanbul-mcp"',
                                          "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        scope[KEY_ID] = matched
        await self.app(scope, receive, send)


class ApiKeyQuotaMiddleware:
    """Count authenticated POST attempts after the body/rate/concurrency guards."""
    def __init__(self, app: ASGIApp, *, quota: DailyQuota | None):
        self.app = app
        self.quota = quota

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (self.quota is None or scope["type"] != "http" or scope.get("method") != "POST"
                or scope.get("path") != "/mcp/" or KEY_ID not in scope):
            await self.app(scope, receive, send)
            return
        try:
            result = await asyncio.to_thread(self.quota.consume, scope[KEY_ID])
        except sqlite3.Error:
            response = JSONResponse(
                {"ok": False, "error_code": "quota_unavailable", "summary": "Quota store is unavailable."},
                status_code=503, headers={"Retry-After": "1", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        headers = {
            "X-RateLimit-Limit": str(self.quota.limit),
            "X-RateLimit-Remaining": str(result.remaining),
            "X-RateLimit-Reset": str(result.reset_at),
            "Cache-Control": "no-store",
        }
        if not result.allowed:
            headers["Retry-After"] = str(result.retry_after)
            response = JSONResponse(
                {"ok": False, "error_code": "daily_quota_exceeded",
                 "summary": "Daily API key quota exhausted; resets at UTC midnight."},
                status_code=429, headers=headers,
            )
            await response(scope, receive, send)
            return

        async def send_with_quota(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message).update(headers)
            await send(message)

        await self.app(scope, receive, send_with_quota)
