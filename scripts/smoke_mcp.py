"""Run the real local server with disposable credentials; never contact data APIs."""
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


def request(base: str, path: str, *, key: str | None = None, payload: dict | None = None):
    headers = {"accept": "application/json, text/event-stream"}
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


def main() -> None:
    checks = []
    process = None
    with tempfile.TemporaryDirectory(prefix="istanbul-mcp-smoke-") as directory:
        directory = Path(directory)
        key = secrets.token_urlsafe(32)  # never printed, persisted or forwarded
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        base = f"http://127.0.0.1:{port}"
        env = {
            "PATH": os.defpath, "PYTHONPATH": str(ROOT), "PYTHONUNBUFFERED": "1",
            "HOST": "127.0.0.1", "PORT": str(port),
            "MCP_AUTH_REQUIRED": "true", "MCP_API_KEYS": key,
            "MCP_API_KEY_DAILY_QUOTA": "5",
            "DATABASE_PATH": str(directory / "runtime.sqlite3"),
        }

        def start():
            log = (directory / "server.log").open("ab")
            try:
                child = subprocess.Popen(
                    [sys.executable, "-m", "app.main"], cwd=ROOT, env=env,
                    stdout=log, stderr=subprocess.STDOUT,
                )
            finally:
                log.close()
            deadline = time.monotonic() + 15
            try:
                while child.poll() is None and time.monotonic() < deadline:
                    try:
                        status, _body = request(base, "/healthz")
                        if status == 200:
                            return child
                    except (urllib.error.URLError, TimeoutError, OSError):
                        pass
                    time.sleep(0.05)
                raise RuntimeError("Local MCP subprocess did not become ready; inspect its startup configuration")
            except BaseException:
                stop(child)
                raise

        try:
            process = start()
            assert request(base, "/healthz")[0] == 200
            assert request(base, "/status")[0] == 401
            assert request(base, "/mcp/", payload=rpc("tools/list"))[0] == 401
            checks.append("public health + unauthenticated status/MCP 401")

            status, initialized = request(base, "/mcp/", key=key, payload=rpc(
                "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                               "clientInfo": {"name": "process-smoke", "version": "1"}},
            ))
            assert status == 200 and initialized["result"]["serverInfo"]["name"] == "istanbul-mcp"
            checks.append("authenticated MCP initialize")

            status, listed = request(base, "/mcp/", key=key, payload=rpc("tools/list"))
            names = {tool["name"] for tool in listed["result"]["tools"]}
            assert status == 200 and len(names) == 15
            assert "istanbul_ferry_schedules" not in names and "istanbul_parking_nearby" not in names
            assert "istanbul_datastore_query" in names
            checks.append("15 compact tools; ferry/legacy absent")

            status, health = request(base, "/mcp/", key=key, payload=rpc(
                "tools/call", {"name": "istanbul_health", "arguments": {}},
            ))
            assert status == 200 and tool_payload(health)["ok"] is True
            checks.append("MCP tool call returns readiness envelope")

            status, invalid_geo = request(base, "/mcp/", key=key, payload=rpc(
                "tools/call", {"name": "istanbul_nearby",
                               "arguments": {"kind": "pharmacy", "lat": 41, "lon": 29, "radius_m": 6000}},
            ))
            assert status == 200 and tool_payload(invalid_geo)["data"][0]["field"] == "radius_m"
            checks.append("invalid geo rejected without upstream access")

            status, invalid_sql = request(base, "/mcp/", key=key, payload=rpc(
                "tools/call", {"name": "istanbul_datastore_query",
                               "arguments": {"resource_id": "not-enabled",
                                             "sql": "SELECT COUNT(*) AS n FROM records"}},
            ))
            assert status == 200 and tool_payload(invalid_sql)["data"][0]["error_code"] == "resource_not_allowlisted"
            checks.append("SQL resource allowlist fails closed")

            assert request(base, "/mcp/", key=key, payload=rpc("ping"))[0] == 429
            checks.append("daily quota 429 after five authenticated attempts")
            stop(process)
            process = start()
            assert request(base, "/mcp/", key=key, payload=rpc("ping"))[0] == 429
            checks.append("daily quota survives process restart")
        finally:
            stop(process)
    print(json.dumps({"ok": True, "surface": "real python -m app.main subprocess",
                      "external_data_api_calls": 0, "checks": checks}, indent=2))


if __name__ == "__main__":
    main()
