"""Run the real local server in public and keyed modes; never contact data APIs."""
from __future__ import annotations

import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"accept": "application/json, text/event-stream"}


def request(base: str, path: str, *, key: str | None = None, payload: dict | None = None):
    headers = dict(HEADERS)
    if key:
        headers["authorization"] = "Bearer " + key
    if payload is not None:
        headers["content-type"] = "application/json"
    message = urllib.request.Request(
        base + path, headers=headers,
        data=json.dumps(payload).encode() if payload is not None else None,
    )
    # Ignore environment proxies; this helper talks exclusively to loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        response = opener.open(message, timeout=2)
    except urllib.error.HTTPError as exc:
        response = exc
    with response:
        return response.status, json.loads(response.read())


def rpc(method: str, params: dict | None = None):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}


def tool_payload(response: dict):
    result = response["result"]
    assert not result.get("isError"), result
    return result.get("structuredContent") or json.loads(result["content"][0]["text"])


def stop(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


class Server:
    """One real ``python -m app.main`` process with disposable configuration."""

    def __init__(self, directory: Path, extra_env: dict[str, str]):
        self.directory = directory
        self.extra_env = extra_env
        self.process = None
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.base = f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        env = {
            "PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1",
            "HOST": "127.0.0.1", "PORT": str(self.port),
            "DATABASE_PATH": str(self.directory / "runtime.sqlite3"),
            **self.extra_env,
        }
        log = (self.directory / "server.log").open("ab")
        try:
            self.process = subprocess.Popen(
                [sys.executable, "-m", "app.main"], cwd=ROOT, env=env,
                stdout=log, stderr=subprocess.STDOUT,
            )
        finally:
            log.close()
        deadline = time.monotonic() + 15
        try:
            while self.process.poll() is None and time.monotonic() < deadline:
                try:
                    if request(self.base, "/healthz")[0] == 200:
                        return self
                except (urllib.error.URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.05)
            raise RuntimeError(
                "Local MCP subprocess did not become ready; inspect its startup configuration"
            )
        except BaseException:
            stop(self.process)
            raise

    def __exit__(self, *_exc):
        stop(self.process)


def check_public_mode(directory: Path) -> list[str]:
    checks = []
    with Server(directory, {}) as server:
        assert request(server.base, "/healthz")[0] == 200
        status, body = request(server.base, "/status")
        assert status == 200 and body["access"]["api_key_required"] is False
        checks.append("public /status without a key")

        status, listed = request(server.base, "/mcp/", payload=rpc("tools/list"))
        names = {tool["name"] for tool in listed["result"]["tools"]}
        assert status == 200 and len(names) == 15
        assert "istanbul_ferry_schedules" not in names
        assert "istanbul_parking_nearby" not in names
        assert "istanbul_datastore_query" in names
        checks.append("public tools/list: 15 compact tools, no ferry/legacy")

        status, health = request(server.base, "/mcp/", payload=rpc(
            "tools/call", {"name": "istanbul_health", "arguments": {}},
        ))
        assert status == 200 and tool_payload(health)["ok"] is True
        checks.append("public MCP tool call returns readiness envelope")

        status, invalid_sql = request(server.base, "/mcp/", payload=rpc(
            "tools/call", {"name": "istanbul_datastore_query",
                           "arguments": {"resource_id": "not-enabled",
                                         "sql": "SELECT COUNT(*) AS n FROM records"}},
        ))
        assert status == 200
        assert tool_payload(invalid_sql)["data"][0]["error_code"] == "resource_not_allowlisted"
        checks.append("SQL resource allowlist fails closed")
    return checks


def check_keyed_mode(directory: Path) -> list[str]:
    checks = []
    key = secrets.token_urlsafe(32)  # never printed, persisted or forwarded
    env = {"MCP_AUTH_REQUIRED": "true", "MCP_API_KEYS": key, "MCP_API_KEY_DAILY_QUOTA": "5"}
    with Server(directory, env) as server:
        assert request(server.base, "/healthz")[0] == 200
        assert request(server.base, "/status")[0] == 401
        assert request(server.base, "/mcp/", payload=rpc("tools/list"))[0] == 401
        checks.append("keyed mode: health public, status/MCP 401 without key")

        status, initialized = request(server.base, "/mcp/", key=key, payload=rpc(
            "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                           "clientInfo": {"name": "process-smoke", "version": "1"}},
        ))
        assert status == 200
        assert initialized["result"]["serverInfo"]["name"] == "istanbul-mcp"
        checks.append("keyed mode: authenticated initialize")

        status, invalid_geo = request(server.base, "/mcp/", key=key, payload=rpc(
            "tools/call", {"name": "istanbul_nearby",
                           "arguments": {"kind": "pharmacy", "lat": 41, "lon": 29,
                                         "radius_m": 6000}},
        ))
        assert status == 200
        assert tool_payload(invalid_geo)["data"][0]["field"] == "radius_m"
        checks.append("invalid geo rejected without upstream access")

        # Two authenticated attempts are already spent; the daily quota is five.
        statuses = [
            request(server.base, "/mcp/", key=key, payload=rpc("ping"))[0]
            for _ in range(5)
        ]
        assert statuses[:3] == [200, 200, 200] and statuses[3:] == [429, 429]
        checks.append("keyed mode: daily quota 429 once five attempts are spent")

    with Server(directory, env) as server:
        assert request(server.base, "/mcp/", key=key, payload=rpc("ping"))[0] == 429
        checks.append("daily quota survives process restart")
    return checks


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="istanbul-mcp-smoke-") as raw:
        directory = Path(raw)
        checks = check_public_mode(directory) + check_keyed_mode(directory)
    print(json.dumps({"ok": True, "surface": "real python -m app.main subprocess",
                      "external_data_api_calls": 0, "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
