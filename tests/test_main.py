import json

from starlette.testclient import TestClient

from app.main import create_app
from app.mcp.server import istanbul_health


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
    assert "database_path" not in response.json()


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
    assert body["limits"]["mcp_request_guard"]["max_body_bytes"] > 0
    assert "air_quality" in body["limits"]["source_rate_limits"]
    assert "iski" in body["limits"]["source_rate_limits"]
    assert body["abuse_guard"]["rate_limit"]["capacity"] > 0
    assert body["abuse_guard"]["concurrency"]["max_concurrent"] > 0
    assert "database_path" not in body["database"]
    tool_names = {tool["name"] for tool in body["tools"]}
    assert body["tool_count"] >= 21
    assert "istanbul_search_datasets" in tool_names
    assert "istanbul_neighborhood_profile" in tool_names
    assert "istanbul_parking_by_district" in tool_names
    assert "istanbul_iski_active_faults" in tool_names
    assert "istanbul_iski_dam_occupancy" in tool_names


def test_settings_join_iski_snapshot_parts(monkeypatch):
    from app.core.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.delenv("ISKI_FAULTS_SNAPSHOT_JSON", raising=False)
    monkeypatch.setenv("ISKI_FAULTS_SNAPSHOT_JSON_PART_1", '{"type":')
    monkeypatch.setenv("ISKI_FAULTS_SNAPSHOT_JSON_PART_2", '"FeatureCollection"}')

    settings = get_settings()

    assert settings.iski_faults_snapshot_json == '{"type":"FeatureCollection"}'
    get_settings.cache_clear()


def test_settings_load_iski_relay_and_snapshot_age_limits(monkeypatch):
    from app.core.settings import get_settings

    get_settings.cache_clear()
    monkeypatch.setenv("ISKI_RELAY_BASE_URL", "https://relay.example")
    monkeypatch.setenv("ISKI_RELAY_TOKEN", "secret-value")
    monkeypatch.setenv("ISKI_FAULTS_SNAPSHOT_CAPTURED_AT", "2026-07-23T10:00:00Z")
    monkeypatch.setenv("ISKI_DAMS_SNAPSHOT_CAPTURED_AT", "2026-07-23T09:00:00Z")

    settings = get_settings()

    assert settings.iski_relay_base_url == "https://relay.example"
    assert settings.iski_relay_token == "secret-value"
    assert settings.iski_relay_timeout_seconds == 15.0
    assert settings.iski_faults_snapshot_captured_at == "2026-07-23T10:00:00Z"
    assert settings.iski_dams_snapshot_captured_at == "2026-07-23T09:00:00Z"
    assert settings.iski_faults_snapshot_max_age_seconds == 21_600
    assert settings.iski_dams_snapshot_max_age_seconds == 86_400
    get_settings.cache_clear()


def test_status_reports_iski_relay_without_exposing_token():
    from app.core.settings import Settings
    from app.core.status import build_status

    body = build_status(
        Settings(
            iski_relay_base_url="https://relay.example",
            iski_relay_token="must-not-appear",
        )
    )

    assert body["limits"]["iski_relay_enabled"] is True
    assert body["limits"]["iski_snapshot_max_age_seconds"] == {
        "faults": 21_600,
        "dams": 86_400,
    }
    assert "must-not-appear" not in json.dumps(body)


def test_mcp_health_does_not_expose_database_path():
    body = istanbul_health()

    assert body["ok"] is True
    assert "database_path" not in body["data"][0]


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
