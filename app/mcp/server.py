from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.core.envelope import Freshness, Source, success_envelope
from app.core.settings import get_settings
from app.services.catalog import CatalogService
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


@mcp.tool()
async def istanbul_search_datasets(
    query: str,
    formats: list[str] | None = None,
    limit: int | None = None,
) -> dict:
    """Search the IBB open data catalog."""
    return await CatalogService(settings=get_settings()).search_datasets(
        query=query,
        formats=formats,
        limit=limit,
    )


@mcp.tool()
async def istanbul_get_dataset(dataset_id: str) -> dict:
    """Return metadata and resources for one IBB dataset."""
    return await CatalogService(settings=get_settings()).get_dataset(dataset_id)


@mcp.tool()
async def istanbul_get_resource_schema(resource_id: str) -> dict:
    """Return DataStore field schema for a resource."""
    return await CatalogService(settings=get_settings()).get_resource_schema(resource_id)


@mcp.tool()
async def istanbul_query_resource(
    resource_id: str,
    filters: dict | None = None,
    limit: int | None = None,
) -> dict:
    """Query a CKAN DataStore resource with guarded filters and limits."""
    return await CatalogService(settings=get_settings()).query_resource(
        resource_id=resource_id,
        filters=filters,
        limit=limit,
    )
