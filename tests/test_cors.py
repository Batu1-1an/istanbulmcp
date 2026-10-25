"""Browser CORS and Origin checks do not bypass MCP auth or resource guards."""
from dataclasses import replace

import pytest
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from app.core.cors import ALLOW_HEADERS, ALLOW_METHODS, EXPOSE_HEADERS, validate_cors_settings
from app.core.settings import Settings, get_settings
from app.main import create_app

ORIGIN = "https://ui.example.test"
KEY = "fixture-cors-" + "a" * 32
HEADERS = {"origin": ORIGIN, "accept": "application/json, text/event-stream"}
PING = {"jsonrpc": "2.0", "id": 1, "method": "ping"}


@pytest.fixture
def app_factory(monkeypatch, tmp_path):
    def factory(origins=ORIGIN, **env):
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "cors.sqlite3"))
        monkeypatch.setenv("MCP_CORS_ALLOWED_ORIGINS", origins)
        monkeypatch.setenv("HOST", "0.0.0.0")
        for key, value in env.items():
            monkeypatch.setenv(key, str(value))
        get_settings.cache_clear()
        return create_app()
    return factory


def preflight(client, path="/mcp/", **headers):
    return client.options(path, headers={
        "origin": ORIGIN, "access-control-request-method": "POST",
        "access-control-request-headers": ", ".join(ALLOW_HEADERS), **headers,
    })


def assert_readable(response):
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert "origin" in response.headers["vary"].lower()
    assert "access-control-allow-credentials" not in response.headers
    exposed = {value.strip().lower() for value in response.headers["access-control-expose-headers"].split(",")}
    assert exposed == {value.lower() for value in EXPOSE_HEADERS}


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_allowlisted_preflight_is_local_and_does_not_redirect_or_require_key(app_factory, path):
    with TestClient(app_factory(MCP_API_KEYS=KEY), base_url="http://localhost", follow_redirects=False) as client:
        response = preflight(client, path)
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == ORIGIN
    assert response.headers["access-control-max-age"] == "600"
    assert set(response.headers["access-control-allow-methods"].replace(" ", "").split(",")) == set(ALLOW_METHODS)
    assert "access-control-allow-credentials" not in response.headers


@pytest.mark.parametrize("method", ["GET", "POST", "DELETE"])
def test_all_streamable_http_methods_can_be_preflighted(app_factory, method):
    with TestClient(app_factory(), base_url="http://localhost") as client:
        response = preflight(client, **{"access-control-request-method": method})
    assert response.status_code == 200


@pytest.mark.parametrize("extra", [
    {"access-control-request-method": "PUT"},
    {"access-control-request-headers": "x-unadvertised-header"},
])
def test_unadvertised_method_or_header_is_rejected(app_factory, extra):
    with TestClient(app_factory(), base_url="http://localhost") as client:
        response = preflight(client, **extra)
    assert response.status_code == 400


@pytest.mark.parametrize("origin", ["https://evil.test", "null", "", ORIGIN + ".evil.test", ORIGIN + ":8443", "http://ui.example.test"])
@pytest.mark.parametrize("method", ["POST", "OPTIONS"])
def test_untrusted_origins_are_rejected_before_application_dispatch(app_factory, origin, method):
    app = app_factory()
    dispatched = []

    async def endpoint(_request):
        dispatched.append(True)
        return JSONResponse({"unexpected": True})

    app.router.routes.insert(0, Route("/mcp/", endpoint, methods=["POST", "OPTIONS"]))
    with TestClient(app, base_url="http://localhost") as client:
        response = client.request(method, "/mcp/", headers={**HEADERS, "origin": origin}, json=PING)
    assert response.status_code == 403
    assert response.json()["error_code"] == "origin_not_allowed"
    assert "access-control-allow-origin" not in response.headers
    assert not dispatched


def test_duplicate_origin_headers_are_rejected(app_factory):
    with TestClient(app_factory(), base_url="http://localhost") as client:
        response = client.post("/mcp/", headers=[("origin", ORIGIN), ("origin", ORIGIN)], json=PING)
    assert response.status_code == 403


def test_empty_allowlist_blocks_browser_origins_but_not_existing_clients(app_factory):
    with TestClient(app_factory(origins=""), base_url="http://localhost") as client:
        blocked = client.post("/mcp/", headers=HEADERS, json=PING)
        normal = client.post("/mcp/", headers={"accept": HEADERS["accept"]}, json=PING)
    assert blocked.status_code == 403
    assert normal.status_code == 200
    assert "access-control-allow-origin" not in normal.headers


@pytest.mark.parametrize("path", ["/mcp", "/mcp/"])
def test_plain_options_reports_methods_without_opening_cors(app_factory, path):
    with TestClient(app_factory(origins="", MCP_API_KEYS=KEY), base_url="http://localhost", follow_redirects=False) as client:
        response = client.options(path)
    assert response.status_code == 204 and not response.content
    assert response.headers["allow"] == "GET, POST, DELETE, OPTIONS"
    assert "access-control-allow-origin" not in response.headers


def test_preflights_do_not_consume_key_quota_and_actual_auth_stays_required(app_factory):
    with TestClient(app_factory(MCP_API_KEYS=KEY, MCP_API_KEY_DAILY_QUOTA=1), base_url="http://localhost") as client:
        for _ in range(3):
            assert preflight(client).status_code == 200
        unauthorized = client.post("/mcp/", headers=HEADERS, json=PING)
        first = client.post("/mcp/", headers={**HEADERS, "authorization": "Bearer " + KEY}, json=PING)
        exhausted = client.post("/mcp/", headers={**HEADERS, "authorization": "Bearer " + KEY}, json=PING)
    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"].startswith("Bearer")
    assert first.status_code == 200 and first.headers["x-ratelimit-remaining"] == "0"
    assert exhausted.status_code == 429 and exhausted.json()["error_code"] == "daily_quota_exceeded"
    for response in (unauthorized, first, exhausted):
        assert_readable(response)


def test_body_limit_and_rate_limit_errors_remain_readable_to_allowed_origin(app_factory):
    with TestClient(app_factory(MCP_MAX_BODY_BYTES=32), base_url="http://localhost") as client:
        oversized = client.post("/mcp/", headers=HEADERS, content=b"x" * 100)
    assert oversized.status_code == 413
    assert_readable(oversized)
    with TestClient(app_factory(MCP_MAX_BODY_BYTES=262144, MCP_RATE_LIMIT_CAPACITY=1,
                                MCP_RATE_LIMIT_REFILL_PER_SECOND=.001), base_url="http://localhost") as client:
        for _ in range(3):
            assert preflight(client).status_code == 200
        assert client.post("/mcp/", headers=HEADERS, json=PING).status_code == 200
        limited = client.post("/mcp/", headers=HEADERS, json=PING)
    assert limited.status_code == 429 and int(limited.headers["retry-after"]) > 0
    assert_readable(limited)


def test_unhandled_errors_receive_cors_headers_too(app_factory):
    async def broken(_request):
        raise RuntimeError("fixture exception")
    app = app_factory()
    app.router.routes.insert(0, Route("/mcp/", broken, methods=["POST"]))
    with TestClient(app, base_url="http://localhost", raise_server_exceptions=False) as client:
        response = client.post("/mcp/", headers=HEADERS, json=PING)
    assert response.status_code == 500
    assert_readable(response)


def test_cors_is_not_enabled_on_status_or_unrelated_routes(app_factory):
    with TestClient(app_factory(MCP_API_KEYS=KEY), base_url="http://localhost") as client:
        status = client.get("/status", headers=HEADERS)
        health = client.get("/healthz", headers=HEADERS)
        unknown = preflight(client, "/unknown")
    assert status.status_code == 401 and health.status_code == 200 and unknown.status_code == 404
    assert all("access-control-allow-origin" not in result.headers for result in (status, health, unknown))


def test_local_sdk_origin_policy_agrees_with_cors_and_keeps_host_checks(app_factory):
    with TestClient(app_factory(HOST="localhost"), base_url="http://localhost") as client:
        allowed = client.post("/mcp/", headers=HEADERS, json=PING)
        bad_host = client.post("/mcp/", headers={**HEADERS, "host": "untrusted.test"}, json=PING)
    assert allowed.status_code == 200
    assert bad_host.status_code == 421
    assert_readable(bad_host)


def test_multiple_origins_and_private_status_configuration(app_factory):
    with TestClient(app_factory(origins=ORIGIN + ", https://other.example.test"), base_url="http://localhost") as client:
        other = preflight(client, origin="https://other.example.test")
        status = client.get("/status").json()
    assert other.status_code == 200
    assert status["transport"]["browser_cors"]["allowed_origin_count"] == 2
    assert ORIGIN not in str(status)


@pytest.mark.parametrize("origin", [
    "https://ui.example.test", "https://xn--istanbul-test.example:8443",
    "http://localhost:5173", "http://127.0.0.1:5173", "http://[::1]:5173",
])
def test_valid_origin_configuration(origin):
    validate_cors_settings(replace(Settings(), mcp_cors_allowed_origins=(origin,)))


@pytest.mark.parametrize("origins", [
    ("*",), ("null",), ("https://*.example.test",), ("http://example.test",),
    ("https://user:secret@example.test",), ("https://example.test/path",),
    ("https://example.test/",), ("https://example.test?x=1",), ("https://example.test#fragment",),
    ("https://example.test:99999",), ("https://example.test:0",), ("https://example.test:%",),
    ("https://bad host",), ("https://example.test\\evil",), ("https://example.test\n",),
    ("https://EXAMPLE.test",), (ORIGIN, ORIGIN), tuple(f"https://site{i}.test" for i in range(33)),
])
def test_invalid_origin_configuration_fails_closed_without_echoing_values(origins):
    with pytest.raises(ValueError, match="MCP_CORS_ALLOWED_ORIGINS") as error:
        validate_cors_settings(replace(Settings(), mcp_cors_allowed_origins=origins))
    assert "secret" not in str(error.value)
