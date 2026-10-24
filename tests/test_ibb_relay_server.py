import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from relays.ibb_relay import server as relay

TOKEN = "t" * 40


class Upstream(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def do_GET(self):
        self.record(b"")
        if self.path.startswith("/unsized"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"no length here")
            return
        body = json.dumps({"path": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "max-age=600")
        self.send_header("X-Upstream", "yes")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.record(body)
        self.send_response(201)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def record(self, body: bytes) -> None:
        Upstream.calls.append({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body})

    def log_message(self, *_args) -> None:
        return None


def serve(server: ThreadingHTTPServer):
    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.02}, daemon=True)
    thread.start()
    return server


@pytest.fixture
def upstream():
    Upstream.calls = []
    server = serve(ThreadingHTTPServer(("127.0.0.1", 0), Upstream))
    yield server
    server.shutdown()
    server.server_close()


def start_relay(connect) -> tuple[relay.RelayServer, str]:
    server = serve(relay.RelayServer(("127.0.0.1", 0), TOKEN, connect=connect))
    return server, f"http://127.0.0.1:{server.server_address[1]}"


@pytest.fixture
def relay_url(upstream):
    port = upstream.server_address[1]
    server, url = start_relay(lambda _host: http.client.HTTPConnection("127.0.0.1", port, timeout=5))
    yield url
    server.shutdown()
    server.server_close()


def test_relay_health_is_public(relay_url):
    response = httpx.get(f"{relay_url}/healthz")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.parametrize("headers", [{}, {"X-Relay-Token": "wrong"}, {"X-Relay-Token": TOKEN + "x"}])
def test_relay_rejects_missing_or_wrong_token(relay_url, headers):
    response = httpx.get(f"{relay_url}/api.ibb.gov.tr/ispark/Park", headers=headers)
    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert Upstream.calls == []


@pytest.mark.parametrize("path", ["/example.com/", "/api.ibb.gov.tr.evil.test/", "/http://api.ibb.gov.tr/x", "/"])
def test_relay_rejects_hosts_outside_allowlist(relay_url, path):
    response = httpx.get(f"{relay_url}{path}", headers={"X-Relay-Token": TOKEN})
    assert response.status_code == 404
    assert Upstream.calls == []


def test_relay_forwards_get_with_query_and_strips_relay_headers(relay_url):
    response = httpx.get(
        f"{relay_url}/api.ibb.gov.tr/ispark/Park?a=1&b=%C3%BC",
        headers={
            "X-Relay-Token": TOKEN,
            "X-Forwarded-For": "203.0.113.9",
            "CDN-RequestId": "abc",
            "Accept": "application/json",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"path": "/ispark/Park?a=1&b=%C3%BC"}
    assert response.headers["x-upstream"] == "yes"
    assert response.headers["cache-control"] == "no-store"
    sent = {key.lower(): value for key, value in Upstream.calls[0]["headers"].items()}
    assert sent["accept"] == "application/json"
    assert not {"x-relay-token", "x-forwarded-for", "cdn-requestid"} & sent.keys()


def test_relay_forwards_post_body(relay_url):
    payload = {"resource_id": "abc", "limit": 1}
    response = httpx.post(
        f"{relay_url}/data.ibb.gov.tr/api/3/action/datastore_search",
        json=payload,
        headers={"X-Relay-Token": TOKEN},
    )

    assert response.status_code == 201
    assert response.json() == payload
    assert Upstream.calls[0]["method"] == "POST"
    assert json.loads(Upstream.calls[0]["body"]) == payload


def test_relay_buffers_responses_without_content_length(relay_url):
    response = httpx.get(f"{relay_url}/cbsproxy.ibb.gov.tr/unsized", headers={"X-Relay-Token": TOKEN})
    assert response.status_code == 200
    assert response.content == b"no length here"
    assert response.headers["content-length"] == str(len(b"no length here"))


def test_relay_rejects_oversized_request_body(relay_url, monkeypatch):
    monkeypatch.setattr(relay, "MAX_REQUEST_BYTES", 8)
    response = httpx.post(f"{relay_url}/data.ibb.gov.tr/x", content=b"0123456789", headers={"X-Relay-Token": TOKEN})
    assert response.status_code == 413
    assert Upstream.calls == []


class TimingOutConnection(http.client.HTTPConnection):
    def connect(self):
        raise TimeoutError("connect timed out")


@pytest.mark.parametrize(
    ("connect", "status", "error"),
    [
        (lambda _host: TimingOutConnection("127.0.0.1", 9), 504, "connect_timeout"),
        (lambda _host: http.client.HTTPConnection("127.0.0.1", 9, timeout=1), 502, "connect_error"),
    ],
)
def test_relay_marks_upstream_connect_failures(connect, status, error):
    server, url = start_relay(connect)
    try:
        response = httpx.get(f"{url}/api.ibb.gov.tr/ispark/Park", headers={"X-Relay-Token": TOKEN})
    finally:
        server.shutdown()
        server.server_close()

    assert response.status_code == status
    assert response.headers["x-relay-error"] == error


def test_relay_requires_a_long_token():
    with pytest.raises(ValueError, match="RELAY_TOKEN"):
        relay.RelayServer(("127.0.0.1", 0), "short")


def test_bunny_container_template_runs_relay_source_on_stock_python():
    from relays.ibb_relay.bunny_container import container_template

    template = container_template(TOKEN)

    assert (template["imageNamespace"], template["imageName"], template["imageTag"]) == ("library", "python", "3.12-alpine")
    assert template["entryPoint"]["argumentsArray"] == ["-c", relay.__loader__.get_source(relay.__name__)]
    assert {"name": "RELAY_TOKEN", "value": TOKEN} in template["environmentVariables"]
    assert template["probes"]["readiness"]["httpGet"]["request"] == {"path": "/healthz", "portNumber": 8080}
