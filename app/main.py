from __future__ import annotations

import asyncio
import contextlib
import logging
from pathlib import Path

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route

from app.connectors.city_open_data import validate_open_data_settings
from app.connectors.gtfs import validate_gtfs_settings
from app.connectors.gtfs_schedule import validate_schedule_settings
from app.connectors.ibb_relay import shared_http_pool, validate_ibb_relay_settings
from app.core.abuse_guard import ClientRateLimiter, ConcurrencyLimiter, McpAbuseGuardMiddleware
from app.core.api_auth import ApiKeyAuthMiddleware, ApiKeyQuotaMiddleware, validate_auth_settings
from app.core.cors import McpCorsApplication, cors_transport_security, validate_cors_settings
from app.core.http_logging import JsonRequestLogMiddleware
from app.core.loop_watchdog import EventLoopWatchdog, validate_watchdog_settings
from app.core.mcp_transport import McpJsonRpcGuard
from app.core.otel import configure_otel
from app.core.server_card import (
    AI_CATALOG_MEDIA_TYPE,
    SERVER_CARD_MEDIA_TYPE,
    build_ai_catalog,
    build_server_card,
)
from app.core.settings import get_settings
from app.core.status import build_status
from app.mcp.registry import create_mcp_server
from app.services.datastore_sql import validate_sql_settings
from app.services.events import keep_events_fresh, validate_events_settings
from app.services.gtfs_schedule import begin_warmup, keep_snapshot_fresh
from app.storage.db import public_readiness, readiness
from app.storage.quota import DailyQuota

logger = logging.getLogger("istanbul_mcp.runtime")
STATIC_DIR = Path(__file__).resolve().parent / "static"
_ICON_PNG = (STATIC_DIR / "icon.png").read_bytes()
_FAVICON_ICO = (STATIC_DIR / "favicon.ico").read_bytes()


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "istanbul-mcp"})


async def readyz(request):
    settings = request.app.state.settings
    db_status = await asyncio.to_thread(readiness, settings.database_path)
    return JSONResponse(public_readiness(db_status))


async def status(request):
    abuse_guard = {}
    if hasattr(request.app.state, "mcp_rate_limiter"):
        abuse_guard["rate_limit"] = request.app.state.mcp_rate_limiter.snapshot()
    if hasattr(request.app.state, "mcp_concurrency_limiter"):
        abuse_guard["concurrency"] = request.app.state.mcp_concurrency_limiter.snapshot()
    if hasattr(request.app.state, "mcp_listen_limiter"):
        abuse_guard["listen_streams"] = request.app.state.mcp_listen_limiter.snapshot()
    tools = await request.app.state.mcp_server.list_tools()
    telemetry = request.app.state.mcp_server.telemetry
    payload = await asyncio.to_thread(
        build_status,
        request.app.state.settings,
        abuse_guard=abuse_guard,
        tools=tools,
        tool_metrics=telemetry.snapshot() if telemetry is not None else None,
    )
    return JSONResponse(payload)


PUBLIC_DISCOVERY_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "Accept",
}


async def icon_png(request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=PUBLIC_DISCOVERY_CORS)
    return Response(_ICON_PNG, media_type="image/png", headers={"Cache-Control": "public, max-age=86400", **PUBLIC_DISCOVERY_CORS})


async def favicon_ico(request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=PUBLIC_DISCOVERY_CORS)
    return Response(_FAVICON_ICO, media_type="image/x-icon", headers={"Cache-Control": "public, max-age=86400", **PUBLIC_DISCOVERY_CORS})


async def server_card(request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=PUBLIC_DISCOVERY_CORS)
    return JSONResponse(
        build_server_card(request.app.state.settings),
        media_type=SERVER_CARD_MEDIA_TYPE,
        headers={"Cache-Control": "public, max-age=300", **PUBLIC_DISCOVERY_CORS},
    )


async def ai_catalog(request):
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=PUBLIC_DISCOVERY_CORS)
    return JSONResponse(
        build_ai_catalog(request.app.state.settings),
        media_type=AI_CATALOG_MEDIA_TYPE,
        headers={"Cache-Control": "public, max-age=300", **PUBLIC_DISCOVERY_CORS},
    )


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app() -> Starlette:
    settings = get_settings()
    validate_cors_settings(settings)
    validate_sql_settings(settings)
    validate_gtfs_settings(settings)
    validate_schedule_settings(settings)
    validate_open_data_settings(settings)
    validate_ibb_relay_settings(settings)
    validate_watchdog_settings(settings)
    validate_events_settings(settings)
    auth_enabled = validate_auth_settings(settings)
    if not auth_enabled and settings.ckan_sql_allowed_resource_ids:
        logger.warning(
            "SQL allowlist is active without API keys: anonymous clients can trigger bounded "
            "DataStore downloads. Add MCP_API_KEYS or keep the allowlist empty."
        )
    quota = DailyQuota(settings.database_path, settings.mcp_api_key_daily_quota) if auth_enabled else None
    mcp = create_mcp_server(settings)
    mcp_rate_limiter = ClientRateLimiter(
        capacity=settings.mcp_rate_limit_capacity,
        refill_per_second=settings.mcp_rate_limit_refill_per_second,
        max_clients=max(settings.mcp_rate_limit_max_clients, len(settings.mcp_api_keys)),
    )
    mcp_concurrency_limiter = ConcurrencyLimiter(max_concurrent=settings.mcp_max_concurrent_requests)
    mcp_listen_limiter = ConcurrencyLimiter(max_concurrent=settings.mcp_max_listen_streams)

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        configure_otel(settings)
        watchdog = None
        if settings.event_loop_watchdog_seconds:
            watchdog = EventLoopWatchdog(asyncio.get_running_loop(), timeout_seconds=settings.event_loop_watchdog_seconds)
            watchdog.start()
        warmup_task = None
        events_task = None
        try:
            async with shared_http_pool(settings):
                if settings.events_enabled:
                    events_task = asyncio.create_task(keep_events_fresh(settings))
                if settings.gtfs_schedule_enabled and begin_warmup():
                    warmup_task = asyncio.create_task(keep_snapshot_fresh(settings))
                async with mcp.session_manager.run():
                    yield
        finally:
            if events_task is not None:
                events_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await events_task
            if watchdog is not None:
                watchdog.stop()
            if warmup_task is not None and not warmup_task.done():
                warmup_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await warmup_task

    app = McpCorsApplication(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/icon.png", icon_png, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/favicon.ico", favicon_ico, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/.well-known/ai-catalog.json", ai_catalog, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/mcp/server-card", server_card, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/server-card", server_card, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/.well-known/mcp/server-card.json", server_card, methods=["GET", "HEAD", "OPTIONS"]),
            Route("/mcp", mcp_redirect, methods=["GET", "POST", "HEAD", "OPTIONS"]),
            Mount("/mcp", app=mcp.streamable_http_app(
                host=settings.host, streamable_http_path="/",
                stateless_http=True, json_response=True,
                max_request_body_size=settings.mcp_max_body_bytes,
                transport_security=cors_transport_security(settings),
            )),
        ],
        middleware=[
            Middleware(JsonRequestLogMiddleware),
            Middleware(ApiKeyAuthMiddleware, keys=settings.mcp_api_keys),
            Middleware(
                McpAbuseGuardMiddleware,
                max_body_bytes=settings.mcp_max_body_bytes,
                rate_limiter=mcp_rate_limiter,
                concurrency_limiter=mcp_concurrency_limiter,
                listen_limiter=mcp_listen_limiter,
            ),
            Middleware(ApiKeyQuotaMiddleware, quota=quota),
            Middleware(McpJsonRpcGuard),
        ],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.mcp_server = mcp
    app.state.mcp_rate_limiter = mcp_rate_limiter
    app.state.mcp_concurrency_limiter = mcp_concurrency_limiter
    app.state.mcp_listen_limiter = mcp_listen_limiter
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        proxy_headers=True,
        forwarded_allow_ips=settings.forwarded_allow_ips,
    )
