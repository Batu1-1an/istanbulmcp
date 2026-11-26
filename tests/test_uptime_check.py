import socket
import threading
import time

import pytest
import uvicorn

from app.main import create_app
from scripts import uptime_check


@pytest.fixture
def live_server(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "uptime.sqlite3"))
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(), log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{sock.getsockname()[1]}"
    server.should_exit = True
    thread.join(5)


def test_probe_accepts_the_real_app(live_server):
    assert uptime_check.probe(live_server, timeout=5) is None


def test_probe_reports_a_server_that_accepts_but_never_answers():
    # The production outage: TCP connects, but the frozen loop never replies.
    with socket.socket() as frozen:
        frozen.bind(("127.0.0.1", 0))
        frozen.listen()
        reason = uptime_check.probe(f"http://127.0.0.1:{frozen.getsockname()[1]}", timeout=0.5)
    assert reason and "timed out" in reason


def test_probe_reports_a_closed_port():
    with socket.socket() as closed:
        closed.bind(("127.0.0.1", 0))
        port = closed.getsockname()[1]
    assert uptime_check.probe(f"http://127.0.0.1:{port}", timeout=1)


def test_probe_flags_an_mcp_endpoint_without_tools(monkeypatch):
    replies = iter([(200, {"ok": True}), (200, {"result": {"serverInfo": {"name": "istanbul-mcp"}}}),
                    (200, {"result": {"tools": []}})])
    monkeypatch.setattr(uptime_check, "_request", lambda *args, **kwargs: next(replies))
    assert uptime_check.probe("https://example.invalid") == "MCP tools/list returned no tools"


def test_main_retries_before_reporting_down(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(uptime_check, "probe", lambda url, timeout: calls.append(url) or "TimeoutError: timed out")
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert uptime_check.main(["--url", "https://example.invalid", "--attempts", "3", "--delay", "0"]) == 1
    assert len(calls) == 3
    assert output.read_text().splitlines() == [
        "healthy=false", "reason=TimeoutError: timed out", "url=https://example.invalid"]


def test_main_recovers_on_a_later_attempt(monkeypatch, tmp_path):
    results = iter(["URLError: blip", None])
    monkeypatch.setattr(uptime_check, "probe", lambda url, timeout: next(results))
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert uptime_check.main(["--url", "https://example.invalid", "--delay", "0"]) == 0
    assert output.read_text().splitlines()[0] == "healthy=true"


def test_empty_workflow_input_falls_back_to_production(monkeypatch):
    seen = []
    monkeypatch.setenv("UPTIME_URL", "")
    monkeypatch.setattr(uptime_check, "probe", lambda url, timeout: seen.append(url))
    assert uptime_check.main(["--attempts", "1"]) == 0
    assert seen == [uptime_check.DEFAULT_URL]


def test_probe_sources_detects_degraded_relay(monkeypatch):
    replies = iter([
        (200, {"result": {"structuredContent": {"ok": False, "error": {"code": "source_unavailable"}}}}),
        (200, {"result": {"structuredContent": {"ok": False, "error": {"code": "source_unavailable"}}}}),
        (200, {"ibb_relay": {"enabled": True, "status": "degraded", "last_error_kind": "relay_suspended_or_misconfigured", "last_error_status": 403}}),
    ])
    monkeypatch.setattr(uptime_check, "_request", lambda *args, **kwargs: next(replies))
    reason = uptime_check.probe_sources("https://example.invalid")
    assert reason == "IBB relay degraded: relay_suspended_or_misconfigured (HTTP 403)"


def test_probe_sources_reports_healthy_when_sources_succeed(monkeypatch):
    replies = iter([
        (200, {"result": {"structuredContent": {"ok": True}}}),
        (200, {"result": {"structuredContent": {"ok": True}}}),
        (200, {"ibb_relay": {"enabled": True, "status": "healthy"}}),
    ])
    monkeypatch.setattr(uptime_check, "_request", lambda *args, **kwargs: next(replies))
    assert uptime_check.probe_sources("https://example.invalid") is None


def test_main_with_check_sources_writes_degraded_output(monkeypatch, tmp_path):
    monkeypatch.setattr(uptime_check, "probe", lambda url, timeout: None)
    monkeypatch.setattr(uptime_check, "probe_sources", lambda url, timeout: "IBB relay degraded: relay_suspended_or_misconfigured (HTTP 403)")
    output = tmp_path / "github_output"
    monkeypatch.setenv("GITHUB_OUTPUT", str(output))

    assert uptime_check.main(["--url", "https://example.invalid", "--attempts", "1", "--check-sources"]) == 0
    lines = output.read_text().splitlines()
    assert "healthy=true" in lines
    assert "degraded=true" in lines
    assert "degraded_reason=IBB relay degraded: relay_suspended_or_misconfigured (HTTP 403)" in lines
