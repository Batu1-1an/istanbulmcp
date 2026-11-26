"""Probe the public endpoint the way an MCP client does; used by the uptime workflow.

Healthy means /healthz answers and an MCP initialize + tools/list round trip
succeeds. Optional --check-sources additionally detects upstream/relay outages
(e.g., suspended IBB relay returning 403) without confusing them with total
server downtime. Exit code 0 = healthy, 1 = down. Inside GitHub Actions the
result is also written to $GITHUB_OUTPUT (healthy, reason, url, degraded,
degraded_reason).
"""
from __future__ import annotations

import argparse
import http.client
import json
import os
import sys
import time
import urllib.request

DEFAULT_URL = "https://istanbulmcp-production.up.railway.app"
HEADERS = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "user-agent": "istanbul-mcp-uptime/1.0 (+github-actions)",
}


def _request(url: str, *, timeout: float, payload: dict | None = None) -> tuple[int, dict]:
    data = None if payload is None else json.dumps(payload).encode()
    with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=HEADERS), timeout=timeout) as response:
        return response.status, json.loads(response.read())


def probe(base_url: str, *, timeout: float = 20.0) -> str | None:
    """Return None when healthy, otherwise a short reason."""
    base = base_url.rstrip("/")
    try:
        status, health = _request(base + "/healthz", timeout=timeout)
        if status != 200 or health.get("ok") is not True:
            return f"/healthz returned HTTP {status}"
        _, init = _request(base + "/mcp/", timeout=timeout, payload={
            "jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                "protocolVersion": "2025-03-26", "capabilities": {},
                "clientInfo": {"name": "istanbul-mcp-uptime", "version": "1"},
            },
        })
        if init.get("result", {}).get("serverInfo", {}).get("name") != "istanbul-mcp":
            return "MCP initialize did not return istanbul-mcp server info"
        _, listed = _request(base + "/mcp/", timeout=timeout, payload={
            "jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {},
        })
        if not listed.get("result", {}).get("tools"):
            return "MCP tools/list returned no tools"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def _call_tool_ok(base: str, name: str, arguments: dict, *, timeout: float) -> tuple[bool, str | None]:
    _, body = _request(base + "/mcp/", timeout=timeout, payload={
        "jsonrpc": "2.0", "id": 10, "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    })
    result = body.get("result") or {}
    payload = result.get("structuredContent")
    if not isinstance(payload, dict):
        content = result.get("content") or []
        if content and isinstance(content[0], dict) and isinstance(content[0].get("text"), str):
            payload = json.loads(content[0]["text"])
    if not isinstance(payload, dict):
        return False, "malformed_tool_response"
    if payload.get("ok") is True:
        return True, None
    err = payload.get("error") or {}
    return False, err.get("code") or "request_failed"


def probe_sources(base_url: str, *, timeout: float = 20.0) -> str | None:
    """Return None when upstream city sources/relay look healthy, else a degraded reason."""
    base = base_url.rstrip("/")
    try:
        traffic_ok, traffic_err = _call_tool_ok(base, "istanbul_traffic_status", {}, timeout=timeout)
        catalog_ok, catalog_err = _call_tool_ok(
            base, "istanbul_search_datasets", {"query": "istanbul", "limit": 1}, timeout=timeout,
        )
        status_code, status_body = _request(base + "/status", timeout=timeout)
        relay = status_body.get("ibb_relay") if status_code == 200 and isinstance(status_body, dict) else None
        if isinstance(relay, dict) and relay.get("enabled") and relay.get("status") == "degraded":
            kind = relay.get("last_error_kind") or "relay_error"
            code = relay.get("last_error_status")
            detail = f"{kind} (HTTP {code})" if code is not None else kind
            return f"IBB relay degraded: {detail}"
        if not traffic_ok and not catalog_ok:
            return f"Core IBB sources unavailable (traffic={traffic_err}, catalog={catalog_err})"
    except (OSError, ValueError, http.client.HTTPException) as exc:
        return f"Source probe failed ({type(exc).__name__})"
    return None


def _write_github_output(**values: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as output:
            for key, value in values.items():
                output.write(f"{key}={' '.join(value.split())[:300]}\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("UPTIME_URL") or DEFAULT_URL)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=20.0, help="seconds between attempts")
    parser.add_argument("--timeout", type=float, default=20.0, help="seconds per HTTP request")
    parser.add_argument("--check-sources", action="store_true", help="also probe upstream IBB relay/sources for degradation")
    args = parser.parse_args(argv)

    reason = None
    for attempt in range(1, max(1, args.attempts) + 1):
        reason = probe(args.url, timeout=args.timeout)
        if reason is None:
            degraded_reason = probe_sources(args.url, timeout=args.timeout) if args.check_sources else None
            if degraded_reason:
                print(f"DEGRADED: {args.url}: {degraded_reason}")
                _write_github_output(
                    healthy="true", reason="", url=args.url,
                    degraded="true", degraded_reason=degraded_reason,
                )
            else:
                print(f"OK: {args.url} is healthy (attempt {attempt})")
                outputs = {"healthy": "true", "reason": "", "url": args.url}
                if args.check_sources:
                    outputs.update(degraded="false", degraded_reason="")
                _write_github_output(**outputs)
            return 0
        print(f"attempt {attempt}/{args.attempts} failed: {reason}", file=sys.stderr)
        if attempt < args.attempts:
            time.sleep(args.delay)
    print(f"DOWN: {args.url}: {reason}")
    _write_github_output(healthy="false", reason=reason or "unknown", url=args.url)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
