"""Deterministic MCP dispatch/envelope contracts, not LLM accuracy evaluations."""
import asyncio
from contextlib import asynccontextmanager
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.applications import Starlette
from starlette.routing import Mount
from starlette.testclient import TestClient

from app.core.envelope import Freshness, ResponseEnvelope, Source, success_envelope
import app.mcp.server as tools_module

CASES = json.loads(
    (Path(__file__).parent / "fixtures/evals/city_questions.json").read_text()
)["cases"]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["id"])
@pytest.mark.parametrize("state", ["fresh", "stale", "broken"])
@pytest.mark.parametrize("surface", ["compact", "legacy"])
def test_question_keeps_dispatch_and_envelope(case, state, surface, monkeypatch):
    payload = success_envelope(
        summary=case["question"],
        data=[case["record"]] if state != "broken" else [],
        sources=[Source(name="Fixture official source", publisher="Fixture", license=None)],
        freshness=Freshness(status=state),
        limits=["fixture scope; not live data"],
        warnings=["Preserve uncertainty; do not infer live availability."],
    )
    payload["ok"] = state != "broken"
    method = AsyncMock(return_value=payload)
    service = SimpleNamespace(**{case["method"]: method})
    monkeypatch.setattr(tools_module, case["service"], lambda **_kw: service)

    from app.core.settings import Settings
    from app.mcp.registry import create_mcp_server

    name = case["legacy_tool"] if surface == "legacy" else case["tool"]
    arguments = case["legacy_arguments"] if surface == "legacy" else case["arguments"]
    configured = create_mcp_server(Settings(mcp_legacy_tools_enabled=surface == "legacy"))
    registered = {tool.name for tool in asyncio.run(configured.list_tools())}
    assert name in registered
    # Exercise the actual registry, including its MCP-only output adapters.
    server = configured

    @asynccontextmanager
    async def lifespan(_app):
        async with server.session_manager.run():
            yield

    app = Starlette(routes=[Mount("/mcp", server.streamable_http_app(
        streamable_http_path="/", stateless_http=True, json_response=True,
    ))], lifespan=lifespan)
    with TestClient(app, base_url="http://localhost:8000") as client:
        response = client.post(
            "/mcp/",
            headers={"accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": name, "arguments": arguments}},
        )

    assert response.status_code == 200
    result = response.json()["result"]
    assert not result.get("isError", False), result
    actual = result.get("structuredContent")
    if actual is None:
        actual = json.loads(result["content"][0]["text"])
    ResponseEnvelope.model_validate(actual)
    assert actual == payload
    method.assert_awaited_once_with(*case["service_args"], **case["service_kwargs"])


def test_eval_has_twenty_unique_questions():
    assert len(CASES) == 20
    assert len({case["id"] for case in CASES}) == 20
    assert all(case["question"] and case["record"] for case in CASES)


@pytest.mark.asyncio
async def test_footprint_separates_output_schema_cost_and_discovery_primitives():
    from app.core.settings import Settings
    from app.mcp.registry import create_mcp_server
    from scripts.eval_tools import footprint

    result = await footprint(create_mcp_server(Settings()))
    assert result["tool_count"] == len(result["tool_names"]) == 15
    assert result["structured_tool_count"] == 5
    assert result["resource_count"] == 3
    assert result["prompt_count"] == 4
    assert result["instructions_utf8_bytes"] > 0
    assert result["output_schema_overhead_utf8_bytes"] > 0
    assert result["definition_utf8_bytes"] == (
        result["definition_without_output_schema_utf8_bytes"] + result["output_schema_overhead_utf8_bytes"]
    )
