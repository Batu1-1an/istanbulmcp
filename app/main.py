from __future__ import annotations

import contextlib

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from app.core.settings import get_settings
from app.mcp.server import mcp
from app.storage.db import readiness


async def healthz(_request):
    return JSONResponse({"ok": True, "service": "istanbul-mcp"})


async def readyz(_request):
    settings = get_settings()
    return JSONResponse(readiness(settings.database_path))


def create_app() -> Starlette:
    @contextlib.asynccontextmanager
    async def lifespan(_app: Starlette):
        async with mcp.session_manager.run():
            yield

    return Starlette(
        routes=[
            Route("/healthz", healthz, methods=["GET"]),
            Route("/readyz", readyz, methods=["GET"]),
            Mount("/mcp", app=mcp.streamable_http_app()),
        ],
        lifespan=lifespan,
    )


app = create_app()


if __name__ == "__main__":
    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)
