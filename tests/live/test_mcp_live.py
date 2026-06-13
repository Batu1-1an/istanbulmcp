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


def test_live_mcp_mobility_nearby_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9004,
        "istanbul_mobility_nearby",
        {"place": "Kadıköy Rıhtım", "radius_m": 1500, "limit": 3},
    )

    assert error is None
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert "public_transport_stops" in payload["data"][0]


def test_live_mcp_mobility_district_prompt_returns_parking_without_distance():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9008,
        "istanbul_mobility_nearby",
        {"place": "Başakşehir merkez", "radius_m": 1500, "limit": 5},
    )

    assert error is None
    assert payload["ok"] is True
    assert "ilçe geneli otopark" in payload["summary"]
    parking = payload["data"][0]["parking"]
    assert len(parking) >= 1
    assert "distance_m" not in parking[0]


def test_live_mcp_parking_by_district_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9007,
        "istanbul_parking_by_district",
        {"district": "Başakşehir", "limit": 5},
    )

    assert error is None
    assert payload["ok"] is True
    assert len(payload["data"]) >= 1
    assert "distance_m" not in payload["data"][0]


def test_live_mcp_city_services_nearby_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9005,
        "istanbul_city_services_nearby",
        {"place": "Taksim", "radius_m": 1500, "limit": 3},
    )

    assert error is None
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert "wifi_locations" in payload["data"][0]


def test_live_mcp_neighborhood_profile_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9006,
        "istanbul_neighborhood_profile",
        {"district": "Kadıköy", "neighborhood": "Caferağa"},
    )

    assert error is None
    assert payload["ok"] is True
    assert len(payload["data"]) == 1
    assert payload["data"][0]["coverage"]["earthquake_scenario"] is True
