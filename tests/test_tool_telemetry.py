"""Per-tool metrics are bounded, private, isolated, and do not alter results."""
import asyncio
import json
import logging
from types import SimpleNamespace

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
import pytest
from starlette.testclient import TestClient

from app.core import tool_telemetry as telemetry_module
from app.core.settings import Settings
from app.core.source_cache import SourceTTLCache
from app.core.tool_telemetry import CallObservation, ToolTelemetry, observe_cache
from app.main import create_app
from app.mcp.registry import create_mcp_server


def row(telemetry, name="test"):
    return next(item for item in telemetry.snapshot()["tools"] if item["tool"] == name)


def result(payload, *, structured=True):
    return SimpleNamespace(is_error=False, structured_content=payload if structured else None,
                           content=[SimpleNamespace(text=json.dumps(payload))])


@pytest.mark.parametrize("structured", [True, False])
def test_envelopes_classify_domain_errors_stale_partial_and_counts(structured):
    telemetry = ToolTelemetry({"test"})
    with telemetry.track("test") as observation:
        observation.result(result({
            "ok": False, "error": {"code": "source_unavailable"}, "data": [{}, {}],
            "freshness": {"status": "stale"}, "sources": [
                {"coverage_status": "checked"}, {"coverage_status": "unavailable"},
            ],
        }, structured=structured))
    measured = row(telemetry)
    assert measured["calls"] == 1 and measured["in_flight"] == 0
    assert measured["outcomes"]["domain_error"] == 1
    assert measured["errors"] == {"source_unavailable": 1}
    assert measured["stale_responses"] == measured["partial_responses"] == 1
    assert measured["returned_total"] == 2


def test_latency_and_in_flight_snapshot_are_exact_and_detached(monkeypatch):
    ticks = iter([10, 11.25, 20, 20.25])
    monkeypatch.setattr(telemetry_module.time, "perf_counter", lambda: next(ticks))
    telemetry = ToolTelemetry({"test"})
    with telemetry.track("test"):
        current = row(telemetry)
        assert current["in_flight"] == 1 and current["duration_ms_mean"] is None
    with telemetry.track("test"):
        pass
    measured = row(telemetry)
    assert measured["slow_calls"] == 1
    assert measured["duration_ms_total"] == 1500
    assert measured["duration_ms_mean"] == 750
    assert measured["duration_ms_max"] == 1250
    measured["outcomes"]["success"] = 1000
    measured["cache"]["hit"] = 1000
    assert row(telemetry)["outcomes"]["success"] == 2
    assert row(telemetry)["cache"]["hit"] == 0


@pytest.mark.parametrize("payload", [
    None, [], {"freshness": {"status": []}}, {"ok": False, "error": {"code": "PRIVATE"}},
    {"ok": False, "data": [{"error_code": "validation_error"}]},
])
def test_classifier_handles_legacy_and_malformed_payloads(payload):
    observation = CallObservation()
    observation.result(result(payload))
    assert observation.error_code != "PRIVATE"
    if isinstance(payload, dict) and payload.get("data"):
        assert observation.error_code == "validation_error"


def test_text_parsing_is_bounded_and_tool_error_flag_is_observed():
    observation = CallObservation()
    observation.result(SimpleNamespace(content=[SimpleNamespace(text="x" * (1024 * 1024 + 1))]))
    assert observation.outcome == "success" and observation.returned is None
    observation.result(SimpleNamespace(is_error=True))
    assert observation.outcome == "tool_error"


@pytest.mark.parametrize("error,outcome", [
    (ToolError("private error"), "tool_error"),
    (UnexpectedToolError("private error"), "exception"),
    (RuntimeError("private error"), "exception"),
    (asyncio.CancelledError(), "cancelled"),
])
def test_original_exceptions_and_cancellation_are_preserved(error, outcome):
    telemetry = ToolTelemetry({"test"})
    with pytest.raises(type(error)) as caught:
        with telemetry.track("test"):
            raise error
    assert caught.value is error
    assert row(telemetry)["outcomes"][outcome] == 1
    assert row(telemetry)["in_flight"] == 0
    observe_cache("hit")
    assert row(telemetry)["cache"]["hit"] == 0


def test_unknown_names_and_error_codes_are_bounded_and_private(caplog):
    caplog.set_level(logging.INFO, logger="istanbul_mcp.tools")
    telemetry = ToolTelemetry({"test"})
    for i in range(100):
        with telemetry.track(f"private-name-{i}") as observation:
            observation.result(result({"ok": False, "error": {"code": f"private-code-{i}"},
                                       "data": [{"query": "private-query", "lat": 41.123456}],
                                       "summary": "private-summary"}))
    assert len(telemetry.snapshot()["tools"]) == 2
    assert row(telemetry, "__unknown__")["errors"] == {"other_error": 100}
    serialized = json.dumps(telemetry.snapshot()) + caplog.text
    assert "private-" not in serialized and "41.123456" not in serialized
    assert all(json.loads(record.message)["tool"] == "__unknown__" for record in caplog.records)


def test_broken_log_handler_cannot_change_result_or_replace_original_error(monkeypatch):
    def broken(*_args, **_kwargs):
        raise RuntimeError("private logger failure")
    monkeypatch.setattr(telemetry_module.logger, "info", broken)
    telemetry = ToolTelemetry({"test"})
    with telemetry.track("test"):
        pass
    error = ToolError("original")
    with pytest.raises(ToolError) as caught:
        with telemetry.track("test"):
            raise error
    assert caught.value is error
    assert row(telemetry)["calls"] == 2


@pytest.mark.asyncio
async def test_concurrent_nested_and_background_contexts_do_not_cross_calls():
    telemetry = ToolTelemetry({"a", "b"})
    release = asyncio.Event()

    async def late():
        await release.wait()
        observe_cache("error")

    async def call(name, event):
        with telemetry.track(name):
            observe_cache(event)
            await asyncio.sleep(0)
            observe_cache(event)
            return asyncio.create_task(late())

    tasks = await asyncio.gather(call("a", "hit"), call("b", "miss"))
    release.set()
    await asyncio.gather(*tasks)
    assert row(telemetry, "a")["cache"]["hit"] == 2
    assert row(telemetry, "a")["cache"]["miss"] == 0
    assert row(telemetry, "b")["cache"]["miss"] == 2
    assert row(telemetry, "b")["cache"]["hit"] == 0
    assert row(telemetry, "a")["cache"]["error"] == 0
    with telemetry.track("a"):
        with telemetry.track("b"):
            observe_cache("load")
        observe_cache("stale")
    assert row(telemetry, "b")["cache"]["load"] == 1
    assert row(telemetry, "a")["cache"]["stale"] == 1


@pytest.mark.asyncio
async def test_cache_hit_miss_load_error_stale_and_peek_are_observed():
    cache = SourceTTLCache()
    telemetry = ToolTelemetry({"test"})

    async def loader():
        return ["private cache data"]

    async def broken():
        raise ValueError("private loader failure")

    with telemetry.track("test"):
        options = {"ttl_seconds": 60, "max_entries": 10, "loader": loader}
        await cache.get_with_status("private-key", **options)
        await cache.get_with_status("private-key", **options)
        assert cache.peek_with_status("missing") is None
        assert cache.peek_with_status("private-key").is_fresh
        cache._entries["private-key"].expires_at_monotonic = telemetry_module.time.monotonic() - 1
        stale = await cache.get_with_status("private-key", **{**options, "loader": broken}, stale_if_error_seconds=60)
        assert stale.is_stale
        assert cache.peek_with_status("private-key", stale_if_error_seconds=60).is_stale
    assert row(telemetry)["cache"] == {"hit": 2, "miss": 3, "load": 2, "wait": 0, "stale": 2, "error": 1}


@pytest.mark.asyncio
async def test_single_flight_wait_is_attributed_to_waiting_call():
    cache = SourceTTLCache()
    telemetry = ToolTelemetry({"a", "b"})
    entered, release = asyncio.Event(), asyncio.Event()

    async def loader():
        entered.set()
        await release.wait()
        return 42

    async def call(name):
        with telemetry.track(name):
            return await cache.get("key", ttl_seconds=60, max_entries=10, loader=loader)

    first = asyncio.create_task(call("a"))
    await entered.wait()
    second = asyncio.create_task(call("b"))
    await asyncio.sleep(0)
    release.set()
    assert await asyncio.gather(first, second) == [42, 42]
    assert row(telemetry, "a")["cache"]["load"] == 1
    assert row(telemetry, "b")["cache"]["load"] == 0
    assert row(telemetry, "b")["cache"]["wait"] == 1
    assert row(telemetry, "b")["cache"]["hit"] == 1


@pytest.mark.asyncio
async def test_real_sdk_calls_measure_success_invalid_arguments_and_unknown_name(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "sdk.sqlite3"))
    server = create_mcp_server(Settings())
    health = await server.call_tool("istanbul_health", {})
    assert not health.is_error
    with pytest.raises(ToolError):
        await server.call_tool("istanbul_get_dataset", {})
    with pytest.raises(ToolError, match="tools/list"):
        await server.call_tool("private-unknown", {})
    assert row(server.telemetry, "istanbul_health")["outcomes"]["success"] == 1
    assert row(server.telemetry, "istanbul_get_dataset")["errors"] == {"invalid_arguments": 1}
    assert row(server.telemetry, "__unknown__")["errors"] == {"unknown_tool": 1}


def test_http_status_reports_tool_calls_for_both_protocol_eras(monkeypatch, tmp_path):
    from scripts.smoke_mcp import rpc

    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "http.sqlite3"))
    with TestClient(create_app(), base_url="http://localhost") as client:
        before = client.get("/status").json()["tool_metrics"]
        assert before["enabled"] and before["reset_on_restart"]
        for modern in (False, True):
            params = {"name": "istanbul_health", "arguments": {}}
            headers = {"accept": "application/json, text/event-stream"}
            if modern:
                headers.update({"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/call",
                                "mcp-name": "istanbul_health"})
            response = client.post("/mcp/", headers=headers, json=rpc("tools/call", params, modern=modern))
            assert response.status_code == 200 and not response.json()["result"].get("isError")
        measured = client.get("/status").json()["tool_metrics"]
        health = next(item for item in measured["tools"] if item["tool"] == "istanbul_health")
        assert health["calls"] == health["outcomes"]["success"] == 2
        assert health["in_flight"] == 0
        headers = {"accept": "application/json, text/event-stream"}
        invalid = client.post("/mcp/", headers=headers, json=rpc(
            "tools/call", {"name": "istanbul_get_dataset", "arguments": {}},
        ))
        assert invalid.json()["result"]["isError"] is True
        measured = client.get("/status").json()["tool_metrics"]
        dataset = next(item for item in measured["tools"] if item["tool"] == "istanbul_get_dataset")
        assert dataset["errors"] == {"invalid_arguments": 1}
    assert row(create_mcp_server(Settings()).telemetry, "istanbul_health")["calls"] == 0
