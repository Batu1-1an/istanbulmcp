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
    assert body["tool_count"] == 23
    assert "istanbul_search_datasets" in tool_names
    assert "istanbul_neighborhood_profile" in tool_names
    assert "istanbul_parking_by_district" in tool_names
    assert "istanbul_iski_active_faults" in tool_names
    assert "istanbul_iski_dam_occupancy" in tool_names
    assert "istanbul_transit_disruptions" in tool_names
    assert "istanbul_planned_departures" in tool_names


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
    expected_required = {
        "istanbul_health": [],
        "istanbul_search_datasets": ["query"],
        "istanbul_get_dataset": ["dataset_id"],
        "istanbul_get_resource_schema": ["resource_id"],
        "istanbul_query_resource": ["resource_id"],
        "istanbul_nearby": ["lat", "lon"],
        "istanbul_bbox_search": ["bbox"],
        "istanbul_parking_nearby": ["lat", "lon"],
        "istanbul_parking_by_district": ["district"],
        "istanbul_metro_stations_nearby": ["lat", "lon"],
        "istanbul_air_quality_nearby": ["lat", "lon"],
        "istanbul_traffic_status": [],
        "istanbul_iski_active_faults": [],
        "istanbul_iski_fault_by_number": ["fault_number"],
        "istanbul_iski_nearby_faults": ["lat", "lon"],
        "istanbul_iski_dam_occupancy": [],
        "istanbul_mobility_nearby": [],
        "istanbul_city_services_nearby": [],
        "istanbul_neighborhood_profile": ["district"],
        "istanbul_transit_line_info": ["line_code"],
        "istanbul_stops_for_line": ["line_code"],
        "istanbul_transit_disruptions": [],
        "istanbul_planned_departures": ["line_code"],
    }
    with TestClient(create_app(), base_url="http://localhost") as client:
        headers = {
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        }
        response = client.post(
            "/mcp/",
            headers=headers,
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
        listed = client.post(
            "/mcp/",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )

    assert response.status_code == 200
    assert response.json()["result"]["serverInfo"]["name"] == "istanbul-mcp"
    assert listed.status_code == 200
    listed_tools = listed.json()["result"]["tools"]
    schemas = {tool["name"]: tool["inputSchema"] for tool in listed_tools}
    assert len(listed_tools) == 23
    assert set(schemas) == set(expected_required)
    for name, required in expected_required.items():
        assert schemas[name].get("required", []) == required
        assert set(required) <= set(schemas[name].get("properties", {}))


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
