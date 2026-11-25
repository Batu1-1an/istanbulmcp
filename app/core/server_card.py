"""Read-only MCP Server Card (SEP-2127 draft / well-known discovery metadata)."""
from __future__ import annotations

from importlib import metadata
from typing import Any

from app.core.settings import Settings

SERVER_NAME = "io.github.Batu1-1an/istanbul-mcp"
SERVER_TITLE = "Istanbul MCP"
SERVER_DESCRIPTION = (
    "Read-only Istanbul open city data: transport, nearby services, water, "
    "air quality, open-data catalog, and event discovery/planning."
)
REPOSITORY_URL = "https://github.com/Batu1-1an/istanbulmcp"
WEBSITE_URL = "https://github.com/Batu1-1an/istanbulmcp#readme"


def _package_version() -> str:
    try:
        return metadata.version("istanbul-mcp")
    except metadata.PackageNotFoundError:
        return "0.0.0-local"


def build_server_card(settings: Settings) -> dict[str, Any]:
    base = settings.mcp_public_base_url.rstrip("/")
    auth_required = settings.mcp_auth_required or bool(settings.mcp_api_keys)
    return {
        "name": SERVER_NAME,
        "title": SERVER_TITLE,
        "description": SERVER_DESCRIPTION,
        "version": _package_version(),
        "protocolVersions": ["2026-07-28", "2025-11-25", "2025-03-26"],
        "websiteUrl": WEBSITE_URL,
        "repository": {"url": REPOSITORY_URL, "source": "github"},
        "icons": [
            {
                "src": f"{base}/icon.png",
                "mimeType": "image/png",
                "sizes": ["512x512"],
            }
        ],
        "remotes": [
            {
                "type": "streamable-http",
                "url": f"{base}/mcp/",
            }
        ],
        "authentication": {
            "required": auth_required,
            "schemes": ["bearer"] if auth_required else [],
        },
        "capabilities": {
            "tools": True,
            "resources": True,
            "resourceTemplates": True,
            "prompts": True,
            "completions": True,
            "extensions": ["io.modelcontextprotocol/ui"],
        },
    }
