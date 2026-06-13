from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from app.core.abuse_guard import ClientRateLimiter, ConcurrencyLimiter, McpAbuseGuardMiddleware
from app.core.http_logging import JsonRequestLogMiddleware
from app.core.mcp_transport import McpJsonRpcGuard
from app.core.settings import get_settings
from app.core.status import build_status
from app.mcp.server import mcp
from app.storage.db import readiness


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "istanbul-mcp"})


async def readyz(_request):
    settings = get_settings()
    return JSONResponse(readiness(settings.database_path))


async def status(request):
    abuse_guard = {}
    if hasattr(request.app.state, "mcp_rate_limiter"):
        abuse_guard["rate_limit"] = request.app.state.mcp_rate_limiter.snapshot()
    if hasattr(request.app.state, "mcp_concurrency_limiter"):
        abuse_guard["concurrency"] = request.app.state.mcp_concurrency_limiter.snapshot()
    return JSONResponse(build_status(get_settings(), abuse_guard=abuse_guard))


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app() -> Starlette:
    settings = get_settings()
    mcp_rate_limiter = ClientRateLimiter(
        capacity=settings.mcp_rate_limit_capacity,
        refill_per_second=settings.mcp_rate_limit_refill_per_second,
        max_clients=settings.mcp_rate_limit_max_clients,
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
            Mount("/mcp", app=mcp.streamable_http_app()),
        ],
        middleware=[
            Middleware(JsonRequestLogMiddleware),
            Middleware(
                McpAbuseGuardMiddleware,
                max_body_bytes=settings.mcp_max_body_bytes,
                rate_limiter=mcp_rate_limiter,
                concurrency_limiter=mcp_concurrency_limiter,
            ),
            Middleware(McpJsonRpcGuard),
        ],
        lifespan=lifespan,
    )
    app.state.mcp_rate_limiter = mcp_rate_limiter
    app.state.mcp_concurrency_limiter = mcp_concurrency_limiter
    return app


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
