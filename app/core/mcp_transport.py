from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import Message, Receive, Scope, Send

ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


class McpJsonRpcGuard:
    """Reject invalid JSON-RPC requests before they reach the MCP SDK."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._should_inspect(scope):
            await self.app(scope, receive, send)
            return

        body, messages = await self._read_body(receive)
        if self._has_null_id(body):
            response = JSONResponse(
                {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request: id must not be null.",
                    },
                },
                status_code=400,
            )
            await response(scope, receive, send)
            return

        async def replay_receive() -> Message:
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        await self.app(scope, replay_receive, send)

    def _should_inspect(self, scope: Scope) -> bool:
        if scope.get("type") != "http":
            return False
        if scope.get("method") != "POST":
            return False
        if scope.get("path") not in {"/mcp", "/mcp/"}:
            return False
        headers = {
            key.decode("latin-1").lower(): value.decode("latin-1")
            for key, value in scope.get("headers", [])
        }
        return "application/json" in headers.get("content-type", "")

    async def _read_body(self, receive: Receive) -> tuple[bytes, list[Message]]:
        messages: list[Message] = []
        chunks: list[bytes] = []
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] != "http.request":
                break
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        return b"".join(chunks), messages

    def _has_null_id(self, body: bytes) -> bool:
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            return False

        requests: list[Any]
        if isinstance(payload, list):
            requests = payload
        else:
            requests = [payload]

        return any(
            isinstance(item, dict) and "id" in item and item["id"] is None
            for item in requests
        )
