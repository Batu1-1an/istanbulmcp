"""Probe the public endpoint the way an MCP client does; used by the uptime workflow.

Healthy means /healthz answers and an MCP initialize + tools/list round trip
succeeds. Each failed probe is retried, so one network blip on the runner does
not open an incident. Exit code 0 = healthy, 1 = down. Inside GitHub Actions the
result is also written to $GITHUB_OUTPUT (healthy, reason, url).
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
    args = parser.parse_args(argv)

    reason = None
    for attempt in range(1, max(1, args.attempts) + 1):
        reason = probe(args.url, timeout=args.timeout)
        if reason is None:
            print(f"OK: {args.url} is healthy (attempt {attempt})")
            _write_github_output(healthy="true", reason="", url=args.url)
            return 0
        print(f"attempt {attempt}/{args.attempts} failed: {reason}", file=sys.stderr)
        if attempt < args.attempts:
            time.sleep(args.delay)
    print(f"DOWN: {args.url}: {reason}")
    _write_github_output(healthy="false", reason=reason or "unknown", url=args.url)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
