from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import sqlite3

import pytest
from starlette.testclient import TestClient

from app.core.settings import Settings, get_settings
from app.core.api_auth import validate_auth_settings
from app.main import create_app
from app.storage.quota import DailyQuota

KEY_A = "fixture-A-" + "a" * 32
KEY_B = "fixture-B-" + "b" * 32
HEADERS = {"accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def configured(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("MCP_AUTH_REQUIRED", "true")
    monkeypatch.setenv("MCP_API_KEYS", KEY_A + "," + KEY_B)
    get_settings.cache_clear()

    def factory(**env):
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        get_settings.cache_clear()
        return create_app()
    return factory


def auth(key=KEY_A):
    return {**HEADERS, "authorization": "Bearer " + key}


def test_public_mode_is_the_default(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_AUTH_REQUIRED", raising=False)
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "public.sqlite3"))
    get_settings.cache_clear()
    with TestClient(create_app(), base_url="http://localhost") as client:
        status = client.get("/status")
        listed = client.post("/mcp/", headers=HEADERS, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        called = client.post("/mcp/", headers=HEADERS, json={
            "jsonrpc": "2.0", "id": 2, "method": "tools/call",
            "params": {"name": "istanbul_health", "arguments": {}},
        })
    assert status.status_code == 200
    assert status.json()["access"]["api_key_required"] is False
    assert listed.status_code == 200 and len(listed.json()["result"]["tools"]) == 15
    assert called.status_code == 200 and not called.json()["result"].get("isError", False)
    # No key configured means no per-key daily quota is enforced.
    assert "x-ratelimit-limit" not in listed.headers


def test_enabling_auth_without_keys_fails_closed(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_REQUIRED", "true")
    monkeypatch.delenv("MCP_API_KEYS", raising=False)
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="requires MCP_API_KEYS"):
        create_app()


def test_configured_keys_alone_enable_auth(monkeypatch, tmp_path):
    monkeypatch.delenv("MCP_AUTH_REQUIRED", raising=False)
    monkeypatch.setenv("MCP_API_KEYS", KEY_A)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "keys.sqlite3"))
    get_settings.cache_clear()
    client = TestClient(create_app(), base_url="http://localhost")
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers=auth()).status_code == 200


@pytest.mark.parametrize("keys", [
    ("short",), (KEY_A, KEY_A), ("x" * 257,), ("with spaces" + "x" * 32,),
    ("ı" * 40,), (KEY_A, ""), tuple(str(i).zfill(40) for i in range(101)),
])
def test_malformed_key_configuration_is_rejected_without_leaking_values(keys):
    with pytest.raises(ValueError) as exc:
        validate_auth_settings(Settings(mcp_api_keys=keys))
    assert not any(key and key in str(exc.value) for key in keys)


def test_invalid_boolean_cannot_silently_turn_off_auth(monkeypatch):
    monkeypatch.setenv("MCP_AUTH_REQUIRED", "disabled-maybe")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="must be a boolean"):
        get_settings()


@pytest.mark.parametrize("path", ["/mcp", "/mcp/", "/mcp/extra", "/status"])
@pytest.mark.parametrize("method", ["GET", "POST"])
def test_protected_paths_reject_missing_key_before_payload_parsing(configured, path, method):
    client = TestClient(configured(), base_url="http://localhost", follow_redirects=False)
    response = client.request(method, path, content=b"not-json", headers=HEADERS)
    assert response.status_code == 401
    assert response.headers["www-authenticate"].startswith("Bearer")
    assert response.json()["error_code"] == "unauthorized"


@pytest.mark.parametrize("authorization", [
    "Bearer " + "c" * 40, "Basic " + KEY_A, "Bearer short", "Bearer " + KEY_A + " extra",
])
def test_invalid_credentials_have_same_401_response(configured, authorization):
    client = TestClient(configured(), base_url="http://localhost")
    response = client.post("/mcp/", headers={**HEADERS, "authorization": authorization}, json=PING)
    assert response.status_code == 401
    assert response.json()["error_code"] == "unauthorized"


def test_query_string_and_duplicate_headers_do_not_authenticate(configured):
    client = TestClient(configured(), base_url="http://localhost")
    assert client.get("/status?api_key=" + KEY_A).status_code == 401
    response = client.get("/status", headers=[("authorization", "Bearer " + KEY_A),
                                              ("authorization", "Bearer " + KEY_B)])
    assert response.status_code == 401


def test_health_checks_stay_public_but_status_is_protected(configured):
    client = TestClient(configured(), base_url="http://localhost")
    assert client.get("/healthz").status_code == 200
    assert client.get("/readyz").status_code == 200
    assert client.get("/status").status_code == 401
    assert client.get("/status", headers=auth()).status_code == 200


def test_authenticated_mcp_initialize_list_and_call_work(configured):
    with TestClient(configured(), base_url="http://localhost") as client:
        for method, params in [
            ("initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                            "clientInfo": {"name": "auth-fixture", "version": "1"}}),
            ("tools/list", {}),
            ("tools/call", {"name": "istanbul_health", "arguments": {}}),
        ]:
            response = client.post("/mcp/", headers=auth(),
                                   json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            assert response.status_code == 200
            assert "error" not in response.json()
            assert not response.json()["result"].get("isError", False)


def test_forwarded_allow_ips_is_configurable(monkeypatch):
    monkeypatch.setenv("FORWARDED_ALLOW_IPS", "10.0.0.0/8")
    get_settings.cache_clear()
    assert get_settings().forwarded_allow_ips == "10.0.0.0/8"
    monkeypatch.delenv("FORWARDED_ALLOW_IPS")
    get_settings.cache_clear()
    assert get_settings().forwarded_allow_ips == "127.0.0.1"


def test_daily_quota_is_per_key_persistent_and_not_bypassed_by_proxy_headers(configured):
    app = configured(MCP_API_KEY_DAILY_QUOTA=2)
    with TestClient(app, base_url="http://localhost") as client:
        first = client.post("/mcp/", headers=auth(), json=PING)
        second = client.post("/mcp/", headers=auth(), json=PING)
        exhausted = client.post("/mcp/", headers={**auth(), "x-real-ip": "198.51.100.2"}, json=PING)
        other = client.post("/mcp/", headers=auth(KEY_B), json=PING)
    assert first.headers["x-ratelimit-remaining"] == "1"
    assert second.headers["x-ratelimit-remaining"] == "0"
    assert exhausted.status_code == 429
    assert exhausted.json()["error_code"] == "daily_quota_exceeded"
    assert int(exhausted.headers["retry-after"]) > 0
    assert other.status_code == 200
    with TestClient(configured(), base_url="http://localhost") as client:
        assert client.post("/mcp/", headers=auth(), json=PING).status_code == 429


def test_burst_rate_limit_uses_verified_key_not_source_ip(configured):
    with TestClient(configured(MCP_RATE_LIMIT_CAPACITY=1, MCP_RATE_LIMIT_REFILL_PER_SECOND=0.001),
                    base_url="http://localhost") as client:
        assert client.post("/mcp/", headers=auth(), json=PING).status_code == 200
        assert client.post("/mcp/", headers=auth(), json=PING).status_code == 429
        assert client.post("/mcp/", headers=auth(KEY_B), json=PING).status_code == 200


def test_secret_keys_never_appear_in_status_repr_or_http_logs(configured, caplog):
    with TestClient(configured(), base_url="http://localhost") as client:
        with caplog.at_level("INFO", logger="istanbul_mcp.http"):
            status = client.get("/status", headers=auth()).json()
            client.get("/status?api_key=" + KEY_B)
    combined = json.dumps(status) + repr(get_settings()) + caplog.text
    assert KEY_A not in combined and KEY_B not in combined


def test_quota_store_failure_is_closed(configured, monkeypatch):
    app = configured()
    def fail(*_args):
        raise sqlite3.OperationalError("fixture failure")
    monkeypatch.setattr(DailyQuota, "consume", fail)
    with TestClient(app, base_url="http://localhost") as client:
        response = client.post("/mcp/", headers=auth(), json=PING)
    assert response.status_code == 503
    assert response.json()["error_code"] == "quota_unavailable"


def test_daily_quota_is_atomic_and_rolls_at_utc_midnight(tmp_path):
    quota = DailyQuota(tmp_path / "quota.sqlite3", 5)
    fingerprint = hashlib.sha256(KEY_A.encode()).hexdigest()
    before = datetime(2026, 10, 19, 23, 59, 59, tzinfo=timezone.utc)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _n: quota.consume(fingerprint, before), range(20)))
    assert sum(item.allowed for item in results) == 5
    assert all(0 <= item.remaining <= 4 and item.retry_after == 1 for item in results)
    after = datetime(2026, 10, 20, tzinfo=timezone.utc)
    assert quota.consume(fingerprint, after).remaining == 4
    # SQLite stores only fingerprints, never API key values.
    with sqlite3.connect(quota.database_path) as conn:
        assert conn.execute("SELECT key_hash FROM api_daily_usage").fetchone()[0] == fingerprint
