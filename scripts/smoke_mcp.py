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
        params = payload.get("params", {})
        version = params.get("_meta", {}).get("io.modelcontextprotocol/protocolVersion")
        if version:
            headers["mcp-protocol-version"] = version
            headers["mcp-method"] = payload["method"]
            if "name" in params or "uri" in params:
                headers["mcp-name"] = params.get("name", params.get("uri"))
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


def rpc(method: str, params: dict | None = None, *, modern: bool = False):
    params = dict(params or {})
    if modern:
        params["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": "2026-07-28",
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}


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
        # Import/schema construction can be slower on a shared CI host. This is
        # a startup budget, not a relaxed request or source-query timeout.
        deadline = time.monotonic() + 45
        try:
            while self.process.poll() is None and time.monotonic() < deadline:
                try:
                    if request(self.base, "/healthz")[0] == 200:
                        return self
                except (urllib.error.URLError, TimeoutError, OSError):
                    pass
                time.sleep(0.05)
            raise RuntimeError(
                "Local MCP subprocess did not become ready; startup log follows:\n"
                + (self.directory / "server.log").read_text()
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
        assert status == 200 and len(names) == 16
        assert "istanbul_ferry_schedules" not in names
        assert "istanbul_parking_nearby" not in names
        assert "istanbul_datastore_query" in names
        checks.append("public tools/list: 16 compact tools, no ferry/legacy")
        assert all(tool.get("title") and tool.get("annotations", {}).get("readOnlyHint") is True
                   for tool in listed["result"]["tools"])
        checks.append("public tools/list: every tool has title and readOnlyHint")
        structured = {tool["name"] for tool in listed["result"]["tools"] if "outputSchema" in tool}
        assert structured == {
            "istanbul_nearby", "istanbul_traffic_status", "istanbul_water_status",
            "istanbul_transit_line", "istanbul_transport_disruptions",
            "istanbul_market_schedule",
        }
        checks.append("six public tools publish ResponseEnvelope output schemas")

        status, discovered = request(server.base, "/mcp/", payload=rpc("server/discover", modern=True))
        assert status == 200 and "2026-07-28" in discovered["result"]["supportedVersions"]
        assert "istanbul://coverage" in discovered["result"]["instructions"]
        status, modern_invalid = request(server.base, "/mcp/", payload=rpc(
            "tools/call", {"name": "istanbul_nearby", "arguments": {}}, modern=True,
        ))
        assert status == 200 and tool_payload(modern_invalid)["data"][0]["field"] == "lat"
        result = modern_invalid["result"]
        assert result["structuredContent"] == json.loads(result["content"][0]["text"])
        checks.append("modern server/discover and structured tools/call without initialize")

        for modern in (False, True):
            status, resources = request(server.base, "/mcp/", payload=rpc("resources/list", modern=modern))
            expected_uris = {"istanbul://coverage", "istanbul://sources", "istanbul://schema/catalog"}
            assert status == 200 and {row["uri"] for row in resources["result"]["resources"]} == expected_uris
            for uri in sorted(expected_uris):
                status, document = request(server.base, "/mcp/", payload=rpc(
                    "resources/read", {"uri": uri}, modern=modern,
                ))
                assert status == 200
                content = document["result"]["contents"][0]
                assert content["mimeType"] == "application/json"
                assert json.loads(content["text"])["ok"] is True
            status, prompts = request(server.base, "/mcp/", payload=rpc("prompts/list", modern=modern))
            assert status == 200 and {row["name"] for row in prompts["result"]["prompts"]} == {
                "gunun_ozeti", "mahalle_ozeti", "veri_kesfi", "yolculuk_plani",
            }
            status, rendered = request(server.base, "/mcp/", payload=rpc(
                "prompts/get", {"name": "veri_kesfi", "arguments": {"query": "kütüphane"}}, modern=modern,
            ))
            assert status == 200
            assert "istanbul_get_resource_schema" in rendered["result"]["messages"][0]["content"]["text"]
        checks.append("both protocol eras list/read 3 local resources and list/render 4 workflow prompts")

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
                                         "radius_m": 6000}}, modern=True,
        ))
        assert status == 200
        assert tool_payload(invalid_geo)["data"][0]["field"] == "radius_m"
        assert invalid_geo["result"]["structuredContent"] == tool_payload(invalid_geo)
        checks.append("keyed modern call: invalid geo rejected without upstream access")

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
