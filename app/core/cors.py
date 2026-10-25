"""Explicit browser origins for MCP, outside auth and error responses."""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.settings import Settings

ALLOW_METHODS = ("GET", "POST", "DELETE")
ALLOW_HEADERS = (
    "Accept", "Content-Type", "Authorization", "Mcp-Session-Id",
    "Mcp-Protocol-Version", "Mcp-Method", "Mcp-Name", "Last-Event-ID",
)
EXPOSE_HEADERS = (
    "Mcp-Session-Id", "Mcp-Protocol-Version", "WWW-Authenticate", "Retry-After",
    "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset",
)
MAX_AGE_SECONDS = 600
HOST_PATTERN = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*")


def validate_cors_settings(settings: Settings) -> None:
    origins = settings.mcp_cors_allowed_origins
    error = "MCP_CORS_ALLOWED_ORIGINS requires at most 32 unique HTTPS origins; HTTP is allowed only for localhost, 127.0.0.1 or [::1]. No wildcard, credentials, path, query or fragment."
    if len(origins) > 32 or len(set(origins)) != len(origins):
        raise ValueError(error)
    for origin in origins:
        try:
            parsed = urlsplit(origin)
            host, port = parsed.hostname, parsed.port
            valid = (
                0 < len(origin) <= 2048 and origin.isascii()
                and host is not None and len(host) <= 253 and (host == "::1" or HOST_PATTERN.fullmatch(host))
                and (port is None or 1 <= port <= 65535)
                and (parsed.scheme == "https" or (parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}))
                and parsed.username is None and parsed.password is None
                and origin == f"{parsed.scheme}://{parsed.netloc}"
                and parsed.netloc == parsed.netloc.lower()
                and not any(char.isspace() for char in origin)
                and not any(char in origin for char in "*\\%")
            )
        except (ValueError, TypeError):
            valid = False
        if not valid:
            # A misconfigured URL can include a password; do not echo its value.
            raise ValueError(error)


def cors_transport_security(settings: Settings) -> TransportSecuritySettings | None:
    if settings.host not in {"127.0.0.1", "localhost", "::1"}:
        # Preserve the SDK's existing deployment Host policy. Origin validation
        # is still enforced by our outer middleware, including in public mode.
        return None
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["localhost", "localhost:*", "127.0.0.1", "127.0.0.1:*", "[::1]", "[::1]:*"],
        allowed_origins=list(settings.mcp_cors_allowed_origins),
    )


class McpCorsMiddleware:
    def __init__(self, app: ASGIApp, *, allowed_origins: tuple[str, ...]):
        self.app = app
        self.allowed_origins = frozenset(allowed_origins)
        self.cors = CORSMiddleware(
            self._dispatch, allow_origins=allowed_origins, allow_methods=ALLOW_METHODS,
            allow_headers=ALLOW_HEADERS, expose_headers=EXPOSE_HEADERS,
            allow_credentials=False, max_age=MAX_AGE_SECONDS,
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope.get("path") not in {"/mcp", "/mcp/"}:
            await self.app(scope, receive, send)
            return
        origins = [value.decode("latin-1") for key, value in scope.get("headers", []) if key.lower() == b"origin"]
        # CORS alone controls browser reads. Explicit Origin validation also
        # rejects untrusted origins before any MCP call reaches the application.
        if origins and (len(origins) != 1 or origins[0] not in self.allowed_origins):
            response = JSONResponse(
                {"ok": False, "error_code": "origin_not_allowed", "summary": "This browser origin is not allowed."},
                status_code=403, headers={"Vary": "Origin", "Cache-Control": "no-store"},
            )
            await response(scope, receive, send)
            return
        await self.cors(scope, receive, send)

    async def _dispatch(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["method"] == "OPTIONS":
            # No data, auth/quota consumption or SDK session is needed to
            # describe transport methods. Real requests still cross all guards.
            response = Response(status_code=204, headers={
                "Allow": "GET, POST, DELETE, OPTIONS", "Vary": "Origin",
            })
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


class McpCorsApplication(Starlette):
    def build_middleware_stack(self) -> ASGIApp:
        # Keep Starlette's app/state/lifespan API, while following its CORS
        # guidance: wrap ServerErrorMiddleware too, so 500s carry CORS headers.
        return McpCorsMiddleware(super().build_middleware_stack(),
                                 allowed_origins=self.state.settings.mcp_cors_allowed_origins)
