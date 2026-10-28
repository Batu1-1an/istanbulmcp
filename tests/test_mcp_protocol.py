"""Both protocol eras share the guarded, stateless HTTP endpoint."""
import asyncio
import json
import threading
import tomllib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.mcp.registry import DEFAULT_TOOL_NAMES

MODERN_VERSION = "2026-07-28"


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "protocol.sqlite3"))


def modern_request(client, method, params=None):
    params = dict(params or {})
    params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": MODERN_VERSION,
        "mcp-method": method,
    }
    if "name" in params:
        headers["mcp-name"] = params["name"]
    return client.post(
        "/mcp/", headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
    )


@pytest.mark.parametrize("version", ["2025-03-26", "2025-11-25"])
def test_legacy_initialize_keeps_identity_capabilities_and_stateless_mode(version):
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp/", headers={"accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": version, "capabilities": {},
                "clientInfo": {"name": "legacy-pytest", "version": "1"},
            }},
        )
        assert client.app.state.mcp_server.session_manager.stateless is True

    assert response.status_code == 200
    assert "mcp-session-id" not in response.headers
    result = response.json()["result"]
    assert result["protocolVersion"] == version
    project_version = tomllib.loads((Path(__file__).parents[1] / "pyproject.toml").read_text())["project"]["version"]
    assert result["serverInfo"] == {"name": "istanbul-mcp", "title": "Istanbul MCP", "version": project_version}
    assert {"tools", "resources", "prompts"} <= result["capabilities"].keys()


def test_modern_discovery_and_tools_work_without_initialize_or_session():
    with TestClient(create_app(), base_url="http://localhost") as client:
        discovered = modern_request(client, "server/discover")
        listed = modern_request(client, "tools/list")
        called = modern_request(client, "tools/call", {
            "name": "istanbul_nearby", "arguments": {},
        })

    for response in (discovered, listed, called):
        assert response.status_code == 200, response.text
        assert "mcp-session-id" not in response.headers
    result = discovered.json()["result"]
    assert MODERN_VERSION in result["supportedVersions"]
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["name"] == "istanbul-mcp"
    tools = listed.json()["result"]["tools"]
    assert {tool["name"] for tool in tools} == set(DEFAULT_TOOL_NAMES)
    for tool in tools:
        assert tool["annotations"] == {
            "readOnlyHint": True, "destructiveHint": False,
            "idempotentHint": True, "openWorldHint": True,
        }
    result = called.json()["result"]
    assert not result.get("isError", False)
    payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    assert payload["ok"] is False
    assert payload["data"][0]["field"] == "lat"
    assert payload["warnings"] and payload["limits"]


def test_modern_discovery_uses_the_same_optional_bearer_auth(monkeypatch):
    monkeypatch.setenv("MCP_API_KEYS", "fixture-only-not-a-real-key-1234567890")
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert modern_request(client, "server/discover").status_code == 401
        client.headers["authorization"] = "Bearer fixture-only-not-a-real-key-1234567890"
        assert modern_request(client, "server/discover").status_code == 200


def test_modern_listen_stream_ends_on_client_disconnect_without_freezing_the_server():
    # Production outage: a modern client opens subscriptions/listen; the SDK
    # waits for http.disconnect. Our body-replaying guard answered every later
    # receive() at once with an empty request, so the watcher spun at 100% CPU
    # and froze the event loop. Run in a thread so a spin fails, not hangs.
    app = create_app()
    params = {"notifications": {"toolsListChanged": True}, "_meta": {
        "io.modelcontextprotocol/protocolVersion": MODERN_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
    }}
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "subscriptions/listen", "params": params}).encode()
    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "POST",
        "scheme": "http", "path": "/mcp/", "raw_path": b"/mcp/", "query_string": b"", "root_path": "",
        "client": ("127.0.0.1", 50000), "server": ("localhost", 80),
        "headers": [
            (b"host", b"localhost"), (b"content-type", b"application/json"),
            (b"accept", b"application/json, text/event-stream"),
            (b"mcp-protocol-version", MODERN_VERSION.encode()), (b"mcp-method", b"subscriptions/listen"),
        ],
    }
    sent = []

    async def serve_until_client_disconnects():
        disconnected = asyncio.Event()
        pending = [{"type": "http.request", "body": body, "more_body": False}]

        async def receive():
            if pending:
                return pending.pop()
            await disconnected.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            sent.append(message)

        async with app.router.lifespan_context(app):
            asyncio.get_running_loop().call_later(0.5, disconnected.set)
            await app(scope, receive, send)

    worker = threading.Thread(target=asyncio.run, args=(serve_until_client_disconnects(),), daemon=True)
    worker.start()
    worker.join(timeout=10)

    assert not worker.is_alive(), "event loop stuck after the listen client disconnected"
    start = next(message for message in sent if message["type"] == "http.response.start")
    assert start["status"] == 200
    assert (b"content-type", b"text/event-stream") in [(k.lower(), v.split(b";")[0]) for k, v in start["headers"]]


def test_modern_requests_still_obey_the_body_limit(monkeypatch):
    monkeypatch.setenv("MCP_MAX_BODY_BYTES", "1024")
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = modern_request(client, "tools/call", {
            "name": "istanbul_nearby", "arguments": {"district": "x" * 2048},
        })
    assert response.status_code == 413
