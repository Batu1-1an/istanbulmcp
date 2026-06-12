from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import get_settings
from app.storage.db import readiness

settings = get_settings()

mcp = FastMCP(
    "istanbul-mcp",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
)


@mcp.tool()
def istanbul_health() -> dict:
    """Return Istanbul MCP service readiness."""
    db_status = readiness(settings.database_path)
    return success_envelope(
        summary="Istanbul MCP is ready.",
        data=[db_status],
        sources=[
            Source(
                name="Istanbul MCP local runtime",
                publisher="Istanbul MCP",
                license=None,
                url=None,
            )
        ],
        freshness=Freshness(status="fresh", ttl_seconds=30),
        limits=[
            f"default_limit={settings.default_limit}",
            f"max_limit={settings.max_limit}",
            f"max_radius_m={settings.max_radius_m}",
        ],
    )
