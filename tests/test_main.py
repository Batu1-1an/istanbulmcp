import json

from starlette.testclient import TestClient

from app.main import create_app


def test_healthz_returns_ok():
    client = TestClient(create_app())

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["ok"] is True


def test_readyz_initializes_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    from app.core.settings import get_settings

    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json()["ready"] is True


def test_status_returns_tool_inventory(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "test.sqlite3"))
    from app.core.settings import get_settings

    get_settings.cache_clear()
    client = TestClient(create_app())

    response = client.get("/status")
    body = response.json()

    assert response.status_code == 200
    assert body["ok"] is True
    assert body["transport"]["streamable_http"] == "/mcp/"
    assert body["tool_count"] >= 13
    assert "istanbul_search_datasets" in {tool["name"] for tool in body["tools"]}


def test_http_requests_are_logged_as_json(caplog):
    client = TestClient(create_app())

    with caplog.at_level("INFO", logger="istanbul_mcp.http"):
        response = client.get("/healthz")

    assert response.status_code == 200
    records = [json.loads(record.message) for record in caplog.records]
    assert records[-1]["event"] == "http_request"
    assert records[-1]["method"] == "GET"
    assert records[-1]["path"] == "/healthz"
    assert records[-1]["status"] == 200
    assert records[-1]["duration_ms"] >= 0


def test_mcp_initialize_endpoint():
    with TestClient(create_app(), base_url="http://localhost") as client:
        response = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "content-type": "application/json",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "1.0"},
                },
            },
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "istanbul-mcp"


def test_mcp_rejects_null_jsonrpc_id():
    client = TestClient(create_app(), base_url="http://localhost")

    response = client.post(
        "/mcp/",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        json={
            "jsonrpc": "2.0",
            "id": None,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "pytest", "version": "1.0"},
            },
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == -32600


def test_mcp_without_trailing_slash_redirects_to_canonical_path():
    client = TestClient(create_app(), base_url="http://localhost", follow_redirects=False)

    response = client.post(
        "/mcp",
        headers={"content-type": "application/json"},
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )

    assert response.status_code == 308
    assert response.headers["location"] == "/mcp/"
