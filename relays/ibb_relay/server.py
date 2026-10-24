from __future__ import annotations

import hmac
import http.client
import json
import os
import ssl
import sys
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ALLOWED_HOSTS = frozenset({
    "api.ibb.gov.tr",
    "data.ibb.gov.tr",
    "cbsproxy.ibb.gov.tr",
    "tesislerimiz.ibb.istanbul",
    "www.metro.istanbul",
    "harita.iski.gov.tr",
    "iskiapi.iski.istanbul",
    "sehirhatlari.istanbul",
    "www.sehirhatlari.istanbul",
    "tesislerrezervasyon.ibb.istanbul",
    "www.tcddtasimacilik.gov.tr",
    "marmarayapi.tcddtasimacilik.gov.tr",
})
ALLOWED_METHODS = frozenset({"GET", "HEAD", "POST"})
TOKEN_HEADER = "X-Relay-Token"
ERROR_HEADER = "X-Relay-Error"
MIN_TOKEN_LENGTH = 32
MAX_REQUEST_BYTES = 1024 * 1024
MAX_STREAMED_RESPONSE_BYTES = 128 * 1024 * 1024
MAX_BUFFERED_RESPONSE_BYTES = 32 * 1024 * 1024
CONNECT_TIMEOUT_SECONDS = 5.0
READ_TIMEOUT_SECONDS = 60.0
HOP_BY_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "proxy-connection",
    "te", "trailer", "transfer-encoding", "upgrade",
})
DROPPED_REQUEST_HEADERS = HOP_BY_HOP | {"host", "content-length", "forwarded", "via", "x-real-ip", TOKEN_HEADER.lower()}
DROPPED_REQUEST_PREFIXES = ("cdn-", "x-forwarded-")
DROPPED_RESPONSE_HEADERS = HOP_BY_HOP | {"content-length", "cache-control"}

Connector = Callable[[str], http.client.HTTPConnection]


def https_connection(host: str) -> http.client.HTTPConnection:
    return http.client.HTTPSConnection(host, timeout=CONNECT_TIMEOUT_SECONDS, context=ssl.create_default_context())


class RelayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], token: str, connect: Connector = https_connection):
        if len(token) < MIN_TOKEN_LENGTH:
            raise ValueError(f"RELAY_TOKEN must be at least {MIN_TOKEN_LENGTH} characters")
        super().__init__(address, RelayHandler)
        self.token = token.encode()
        self.connect = connect


class RelayHandler(BaseHTTPRequestHandler):
    server: RelayServer
    server_version = "istanbul-mcp-relay"
    sys_version = ""

    def do_GET(self) -> None:
        self.relay()

    def do_HEAD(self) -> None:
        self.relay()

    def do_POST(self) -> None:
        self.relay()

    def do_PUT(self) -> None:
        self.reply_json(405, {"error": "method not allowed"})

    do_DELETE = do_PATCH = do_OPTIONS = do_PUT

    def relay(self) -> None:
        started = time.monotonic()
        host, status = "-", 0
        try:
            if self.path == "/healthz":
                status = self.reply_json(200, {"ok": True})
                return
            given = self.headers.get(TOKEN_HEADER, "").encode("utf-8", "replace")
            if not hmac.compare_digest(given, self.server.token):
                status = self.reply_json(401, {"error": "unauthorized"})
                return
            host, _, rest = self.path.lstrip("/").partition("/")
            if host not in ALLOWED_HOSTS:
                status = self.reply_json(404, {"error": "host not allowed"})
                return
            if self.command not in ALLOWED_METHODS:
                status = self.reply_json(405, {"error": "method not allowed"})
                return
            body = self.read_body()
            if isinstance(body, int):
                status = self.reply_json(body, {"error": "request body rejected"})
                return
            status = self.forward(host, "/" + rest, body)
        finally:
            elapsed = int((time.monotonic() - started) * 1000)
            sys.stderr.write(json.dumps({"method": self.command, "host": host, "status": status, "ms": elapsed}) + "\n")

    def read_body(self) -> bytes | None | int:
        if self.headers.get("Transfer-Encoding"):
            return 411
        length = self.headers.get("Content-Length")
        if length is None:
            return None
        if not length.isdecimal() or int(length) > MAX_REQUEST_BYTES:
            return 413
        return self.rfile.read(int(length))

    def forward(self, host: str, target: str, body: bytes | None) -> int:
        headers = {
            key: value for key, value in self.headers.items()
            if key.lower() not in DROPPED_REQUEST_HEADERS and not key.lower().startswith(DROPPED_REQUEST_PREFIXES)
        }
        connection = self.server.connect(host)
        try:
            try:
                connection.connect()
            except TimeoutError:
                return self.relay_error(504, "connect_timeout")
            except OSError:
                return self.relay_error(502, "connect_error")
            connection.sock.settimeout(READ_TIMEOUT_SECONDS)
            try:
                connection.request(self.command, target, body=body, headers=headers)
                upstream = connection.getresponse()
                declared = upstream.getheader("Content-Length")
                if declared is not None and declared.isdecimal():
                    if int(declared) > MAX_STREAMED_RESPONSE_BYTES:
                        return self.relay_error(502, "response_too_large")
                    return self.stream(upstream, int(declared))
                payload = upstream.read(MAX_BUFFERED_RESPONSE_BYTES + 1)
                if len(payload) > MAX_BUFFERED_RESPONSE_BYTES:
                    return self.relay_error(502, "response_too_large")
                return self.send_upstream(upstream, payload)
            except TimeoutError:
                return self.relay_error(504, "read_timeout")
            except (OSError, http.client.HTTPException):
                return self.relay_error(502, "upstream_error")
        finally:
            connection.close()

    def start_upstream_response(self, upstream: http.client.HTTPResponse, length: int) -> None:
        self.send_response(upstream.status, upstream.reason)
        for key, value in upstream.getheaders():
            if key.lower() not in DROPPED_RESPONSE_HEADERS:
                self.send_header(key, value)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def stream(self, upstream: http.client.HTTPResponse, length: int) -> int:
        self.start_upstream_response(upstream, length)
        if self.command != "HEAD":
            while chunk := upstream.read(64 * 1024):
                self.wfile.write(chunk)
        return upstream.status

    def send_upstream(self, upstream: http.client.HTTPResponse, payload: bytes) -> int:
        self.start_upstream_response(upstream, len(payload))
        if self.command != "HEAD":
            self.wfile.write(payload)
        return upstream.status

    def relay_error(self, status: int, error: str) -> int:
        return self.reply_json(status, {"error": error}, {ERROR_HEADER: error})

    def reply_json(self, status: int, payload: dict, extra: dict[str, str] | None = None) -> int:
        body = json.dumps(payload).encode()
        self.send_response(status)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)
        return status

    def log_request(self, code: int | str = "-", size: int | str = "-") -> None:
        return None


def main() -> None:
    port = int(os.environ.get("PORT", "8080"))
    RelayServer(("0.0.0.0", port), os.environ.get("RELAY_TOKEN", "")).serve_forever()


if __name__ == "__main__":
    main()
