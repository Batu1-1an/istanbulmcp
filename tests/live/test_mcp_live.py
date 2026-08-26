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


def test_live_mcp_ferry_schedule_scope_is_explicit():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9030,
        "istanbul_ferry_schedules",
        {"route": "Kadıköy - Beşiktaş", "limit": 3},
    )

    assert error is None
    assert payload["freshness"]["status"] in {"fresh", "unknown", "broken"}
    if payload["sources"]:
        assert all(source.get("coverage_kind") == "published_timetable" for source in payload["sources"])
    assert any("ETA" in text or "canlı" in text for text in payload.get("warnings", []) + payload.get("limits", []))


def test_live_mcp_metro_planned_notice_scope_is_reported():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9031,
        "istanbul_transport_disruptions",
        {"operator": "metro_istanbul", "line": "M7", "limit": 5},
    )

    assert error is None
    assert any(source.get("coverage_kind") == "official_announcements" for source in payload["sources"])


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


def test_live_mcp_nobetci_eczane_by_district_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9020,
        "istanbul_nobetci_eczane_by_district",
        {"district": "Kadıköy", "limit": 20},
    )

    assert error is None
    assert "freshness" in payload
    if payload["ok"]:
        assert payload["sources"][0]["name"].startswith("İBB Şehir Haritası")
        assert all(row["province"] == "İstanbul" for row in payload["data"])
        assert all("distance_m" not in row for row in payload["data"])
        assert all(row["duty_ends_at"] is None for row in payload["data"])
    else:
        assert payload["freshness"]["status"] in {"broken", "stale"}


def test_live_mcp_nobetci_eczane_nearby_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9021,
        "istanbul_nobetci_eczane_nearby",
        {"lat": 40.9909, "lon": 29.0303, "radius_m": 5000, "limit": 20},
    )

    assert error is None
    assert "freshness" in payload
    if payload["ok"]:
        assert payload["sources"][0]["name"].startswith("İBB Şehir Haritası")
        assert all(row["province"] == "İstanbul" for row in payload["data"])
        assert all(row["distance_m"] <= 5000 for row in payload["data"])
        assert all(row["duty_ends_at"] is None for row in payload["data"])
        assert all(
            payload["data"][index]["distance_m"] <= payload["data"][index + 1]["distance_m"]
            for index in range(len(payload["data"]) - 1)
        )
    else:
        assert payload["freshness"]["status"] in {"broken", "stale"}


def test_live_mcp_istanbulkart_centers_nearby_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9022,
        "istanbul_istanbulkart_centers_nearby",
        {"lat": 41.038878, "lon": 28.961898, "radius_m": 5000, "limit": 20},
    )

    assert error is None
    assert "freshness" in payload
    if payload["ok"]:
        assert payload["sources"]
        assert all(row["distance_m"] <= 5000 for row in payload["data"])
        assert all("status" not in row and "balance" not in row for row in payload["data"])
    else:
        assert payload["freshness"]["status"] in {"broken", "stale"}


def test_live_mcp_social_facilities_nearby_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9023,
        "istanbul_sosyal_tesis_nearby",
        {"lat": 41.038878, "lon": 28.961898, "radius_m": 5000, "limit": 20},
    )

    assert error is None
    assert "freshness" in payload
    if payload["ok"]:
        assert payload["sources"]
        assert all(row["distance_m"] <= 5000 for row in payload["data"])
        assert all(
            payload["data"][index]["distance_m"] <= payload["data"][index + 1]["distance_m"]
            for index in range(len(payload["data"]) - 1)
        )
        forbidden = {"capacity", "occupancy", "availability", "queue", "open", "closed"}
        assert all(not forbidden.intersection(row) for row in payload["data"])
    else:
        assert payload["freshness"]["status"] in {"broken", "stale"}


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


def test_live_mcp_transit_disruptions_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9010,
        "istanbul_transit_disruptions",
        {"limit": 5},
    )

    assert error is None
    assert payload["ok"] is True
    assert any("IETT" in source["name"] for source in payload["sources"])


def test_live_mcp_transit_disruptions_line_filter_preserves_line_code():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9012,
        "istanbul_transit_disruptions",
        {"line_code": "34A", "limit": 5},
    )

    assert error is None
    assert payload["ok"] is True
    assert all(row["line_code"] == "34A" for row in payload["data"])


@pytest.mark.parametrize(
    ("request_id", "args", "expected_operator", "expected_mode"),
    [
        (9013, {"limit": 5}, None, None),
        (9014, {"mode": "metro", "limit": 5}, "metro_istanbul", "metro"),
        (9015, {"mode": "ferry", "limit": 5}, "sehir_hatlari", "ferry"),
        (9016, {"mode": "suburban_rail", "limit": 5}, "marmaray", "suburban_rail"),
    ],
)
def test_live_mcp_transport_disruptions_coverage_flows(request_id, args, expected_operator, expected_mode):
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        request_id,
        "istanbul_transport_disruptions",
        args,
    )

    assert error is None
    assert "freshness" in payload
    assert payload["sources"]
    if expected_operator:
        assert {source["operator"] for source in payload["sources"]} == {expected_operator}
        assert all(row["mode"] == expected_mode for row in payload["data"])


def test_live_mcp_transport_disruptions_partial_coverage_is_explicit():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9017,
        "istanbul_transport_disruptions",
        {"operator": "marmaray", "limit": 5},
    )

    assert error is None
    assert payload["sources"]
    assert payload["sources"][0]["coverage_status"] in {"checked", "unavailable"}
    assert "warnings" in payload


def test_live_mcp_planned_departures_tool():
    payload, error, _elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9011,
        "istanbul_planned_departures",
        {"line_code": "34A", "limit": 5},
    )

    assert error is None
    assert payload["ok"] is True
    assert "main-terminal planned departures" in payload["limits"]
    assert "not intermediate-stop ETA" in payload["limits"]


def test_live_mcp_metro_accessibility_smoke():
    payload, error, elapsed = rpc_call(
        os.getenv("MCP_LIVE_BASE_URL", DEFAULT_BASE_URL),
        9012,
        "istanbul_metro_accessibility_status",
        {"limit": 20},
    )

    assert error is None
    assert "freshness" in payload
    assert "sources" in payload
    # The live check is non-deterministic; it must record an observed duration and
    # either report a successful/partial envelope or a structured failure.
    assert elapsed >= 0
    if payload["ok"]:
        assert payload["sources"]
        for source in payload["sources"]:
            assert source["coverage_status"] in {"checked", "unavailable"}
        assert "not_an_end_to_end_accessibility_guarantee" in " ".join(payload.get("limits", []))
        for frame in payload.get("data", []):
            # No fabricated accessibility guarantee or inferred alternative route.
            assert "faults" in frame
            assert "equipment_summary" in frame
