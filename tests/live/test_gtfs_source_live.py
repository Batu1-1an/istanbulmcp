"""Opt-in: the real ASGI MCP endpoint, SQLite and public İBB GTFS source."""
import json
import os
import time

import httpx
import pytest

from app.core.settings import get_settings
from app.core.source_cache import clear_source_cache

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(os.getenv("RUN_LIVE_GTFS_TESTS") != "1", reason="Set RUN_LIVE_GTFS_TESTS=1 to check the public GTFS source"),
]


@pytest.mark.asyncio
async def test_live_gtfs_stops_is_bounded_usable_and_cached(tmp_path, monkeypatch):
    from app.main import create_app

    # Only the public GTFS source is contacted, never the deployed MCP server.
    for name, value in {
        "DATABASE_PATH": str(tmp_path / "live-gtfs.sqlite3"), "MCP_API_KEYS": "", "MCP_AUTH_REQUIRED": "false",
        "GTFS_STOPS_MAX_BYTES": "5242880", "GTFS_STOPS_MAX_ROWS": "50000",
        "GTFS_STOPS_LOAD_TIMEOUT_SECONDS": "20", "GTFS_STOPS_CACHE_TTL_SECONDS": "86400",
        "GTFS_STOPS_STALE_IF_ERROR_SECONDS": "0",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()
    clear_source_cache()
    app = create_app()
    settings = app.state.settings
    args = {"lat": 41.01917, "lon": 28.684353, "types": ["public_transport_stop"], "radius_m": 2000, "limit": 5}
    headers = {
        "accept": "application/json, text/event-stream", "mcp-protocol-version": "2026-07-28",
        "mcp-method": "tools/call", "mcp-name": "istanbul_nearby",
    }
    body = {
        "jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {
            "name": "istanbul_nearby", "arguments": args,
            "_meta": {"io.modelcontextprotocol/protocolVersion": "2026-07-28",
                      "io.modelcontextprotocol/clientCapabilities": {}},
        },
    }
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                status = await client.get("/status")
                limits = status.json()["limits"]["gtfs_stops"]
                assert limits["max_bytes"] == 5242880 and limits["max_rows"] == 50000
                assert limits["stale_if_error_seconds"] == 0
                started = time.monotonic()
                response = await client.post("/mcp/", headers=headers, json=body)
                cold_seconds = time.monotonic() - started
                assert response.status_code == 200, response.text
                wire = response.json()["result"]
                assert not wire.get("isError", False), wire
                result = wire["structuredContent"]
                assert json.loads(wire["content"][0]["text"]) == result
                assert result["ok"], result
                assert result["freshness"]["status"] == "fresh"
                source = next(source for source in result["sources"] if source.get("dataset_id") == "iett-gtfs-verisi")
                assert source["coverage_status"] == "checked" and source["scope"] == "complete_stops_csv"
                assert source["accepted_total"] > 0
                assert source["accepted_total"] + source["skipped_total"] == source["received_total"]
                assert source["received_total"] <= settings.gtfs_stops_max_rows
                assert result["data"] and all(row["maps_url"] for row in result["data"])
                assert cold_seconds < settings.gtfs_stops_load_timeout_seconds + 2
                warm_started = time.monotonic()
                warm_response = await client.post("/mcp/", headers=headers, json={**body, "id": 2})
                warm_seconds = time.monotonic() - warm_started
                assert warm_response.status_code == 200
                warm = warm_response.json()["result"]["structuredContent"]
                assert warm["data"] == result["data"] and warm["sources"] == result["sources"]
                print(json.dumps({
                    "surface": "ASGI POST /mcp/ -> istanbul_nearby -> public GTFS -> SQLite",
                    "cold_seconds": round(cold_seconds, 3), "warm_seconds": round(warm_seconds, 4),
                    "resource_id": source["resource_id"], "received_total": source["received_total"],
                    "accepted_total": source["accepted_total"], "skipped_total": source["skipped_total"],
                    "source_updated_at": source["source_updated_at"],
                    "sample": [{key: row[key] for key in ("source_id", "name", "lat", "lon", "distance_m")} for row in result["data"]],
                }, ensure_ascii=False))
    finally:
        clear_source_cache()
        get_settings.cache_clear()
