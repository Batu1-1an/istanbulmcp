import os

import pytest

from scripts.live_mcp_uat import DEFAULT_BASE_URL, rpc_call

pytestmark = pytest.mark.skipif(
    os.getenv("RUN_LIVE_MCP_TESTS") != "1",
    reason="Set RUN_LIVE_MCP_TESTS=1 to run live MCP regression checks.",
)


def test_live_mcp_health_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9001,
        "istanbul_health",
        {},
    )

    assert error is None
    assert payload["ok"] is True
    assert payload["data"][0]["ready"] is True


def test_live_mcp_search_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9002,
        "istanbul_search_datasets",
        {"query": "trafik", "limit": 2},
    )

    assert error is None
    assert payload["ok"] is True
    assert len(payload["data"]) >= 1


def test_live_mcp_validation_envelope():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9003,
        "istanbul_air_quality_nearby",
        {"lat": 40.9909, "lon": 29.0303, "radius_m": 7000, "limit": 1},
    )

    assert error is None
    assert payload["ok"] is False
    assert payload["data"][0]["field"] == "radius_m"
    assert payload["data"][0]["allowed_max"] == 5000
