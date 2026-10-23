from __future__ import annotations

import contextlib
import logging

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from app.core.abuse_guard import ClientRateLimiter, ConcurrencyLimiter, McpAbuseGuardMiddleware
from app.core.http_logging import JsonRequestLogMiddleware
from app.core.api_auth import ApiKeyAuthMiddleware, ApiKeyQuotaMiddleware, validate_auth_settings
from app.storage.quota import DailyQuota
from app.services.datastore_sql import validate_sql_settings
from app.connectors.gtfs import validate_gtfs_settings
from app.connectors.gtfs_schedule import validate_schedule_settings
from app.connectors.city_open_data import validate_open_data_settings
from app.core.mcp_transport import McpJsonRpcGuard
from app.core.settings import get_settings
from app.core.status import build_status
from app.mcp.registry import create_mcp_server
from app.storage.db import public_readiness, readiness


logger = logging.getLogger("istanbul_mcp.runtime")


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "istanbul-mcp"})


async def readyz(request):
    settings = request.app.state.settings
    return JSONResponse(public_readiness(readiness(settings.database_path)))


async def status(request):
    abuse_guard = {}
    if hasattr(request.app.state, "mcp_rate_limiter"):
        abuse_guard["rate_limit"] = request.app.state.mcp_rate_limiter.snapshot()
    if hasattr(request.app.state, "mcp_concurrency_limiter"):
        abuse_guard["concurrency"] = request.app.state.mcp_concurrency_limiter.snapshot()
    tools = await request.app.state.mcp_server.list_tools()
    return JSONResponse(build_status(request.app.state.settings, abuse_guard=abuse_guard, tools=tools))


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app() -> Starlette:
    settings = get_settings()
    validate_sql_settings(settings)
    validate_gtfs_settings(settings)
    validate_schedule_settings(settings)
    validate_open_data_settings(settings)
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

    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    app = Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/mcp", mcp_redirect, methods=["GET", "POST", "HEAD", "OPTIONS"]),
            Mount("/mcp", app=mcp.streamable_http_app(
                host=settings.host, streamable_http_path="/",
                stateless_http=True, json_response=True,
                max_request_body_size=settings.mcp_max_body_bytes,
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
