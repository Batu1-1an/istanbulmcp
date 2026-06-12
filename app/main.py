from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

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


async def status(_request):
    return JSONResponse(build_status(get_settings()))


async def mcp_redirect(_request):
    return RedirectResponse(url="/mcp/", status_code=308)


def create_app() -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Route("/status", status, methods=["GET"]),
            Route("/mcp", mcp_redirect, methods=["GET", "POST", "HEAD", "OPTIONS"]),
            Mount("/mcp", app=mcp.streamable_http_app()),
        ],
        middleware=[
            Middleware(JsonRequestLogMiddleware),
            Middleware(McpJsonRpcGuard),
        ],
        lifespan=lifespan,
    )


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
