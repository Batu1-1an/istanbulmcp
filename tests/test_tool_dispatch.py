import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.settings import Settings
from app.mcp.registry import DEFAULT_TOOL_NAMES, LEGACY_TOOL_NAMES, create_mcp_server
import app.mcp.server as tools


@pytest.mark.parametrize("fn,kwargs,field", [
    ("istanbul_nearby", {}, "lat"),
    ("istanbul_nearby", {"kind": "bogus"}, "kind"),
    ("istanbul_nearby", {"lat": 41}, "lat"),
    ("istanbul_nearby", {"lat": 91, "lon": 29}, "lat"),
    ("istanbul_nearby", {"lat": 41, "lon": 29, "limit": 0}, "limit"),
    ("istanbul_nearby", {"lat": 41, "lon": 29, "radius_m": 5001}, "radius_m"),
    ("istanbul_nearby", {"kind": "pharmacy", "district": "Kadıköy", "lat": 41}, "district"),
    ("istanbul_nearby", {"kind": "pharmacy", "district": "Kadıköy", "radius_m": 1000}, "district"),
    ("istanbul_nearby", {"kind": "air_quality", "district": "Kadıköy"}, "district"),
    ("istanbul_nearby", {"kind": "pharmacy", "types": ["parking"]}, "types"),
    ("istanbul_nearby", {"types": ["not_supported"]}, "types"),
    ("istanbul_nearby", {"kind": "pharmacy", "bbox": [28, 40, 29, 41]}, "bbox"),
    ("istanbul_water_status", {"kind": "dams", "district": "Kadıköy"}, "kind"),
    ("istanbul_water_status", {"dam_name": "Ömerli"}, "kind"),
    ("istanbul_water_status", {"fault_number": "123", "district": "Kadıköy"}, "fault_number"),
    ("istanbul_transit_line", {"line_code": "34A", "action": "stops", "limit": 2}, "limit"),
    ("istanbul_transit_line", {"line_code": "34A", "action": "bogus"}, "action"),
])
@pytest.mark.asyncio
async def test_compact_dispatch_rejects_ambiguous_or_ignored_arguments(fn, kwargs, field, monkeypatch):
    def forbidden(**_kwargs):
        pytest.fail("invalid dispatch must not instantiate a source service")
    for service in ("CityService", "PharmacyService", "IskiService", "TransitService"):
        monkeypatch.setattr(tools, service, forbidden)
    result = await getattr(tools, fn)(**kwargs)
    assert result["ok"] is False
    assert result["data"][0]["field"] == field
    assert result["warnings"] and result["limits"]


@pytest.mark.asyncio
async def test_bbox_and_legacy_coordinate_discovery_keep_city_dispatch(monkeypatch):
    bbox = AsyncMock(return_value={"sentinel": "bbox"})
    nearby = AsyncMock(return_value={"sentinel": "nearby"})
    monkeypatch.setattr(tools, "CityService", lambda **_kw: SimpleNamespace(bbox_search=bbox, nearby=nearby))
    assert await tools.istanbul_nearby(bbox=[28, 40, 29, 41], types=["wifi"]) == {"sentinel": "bbox"}
    bbox.assert_awaited_once_with(bbox=[28, 40, 29, 41], types=["wifi"], limit=None)
    assert await tools.istanbul_nearby(lat=41, lon=29, types=["parking"]) == {"sentinel": "nearby"}
    nearby.assert_awaited_once_with(lat=41, lon=29, radius_m=1000, types=["parking"], limit=None)


@pytest.mark.asyncio
async def test_nearby_faults_keep_iski_approximate_geometry_service(monkeypatch):
    method = AsyncMock(return_value={"sentinel": "water_fault"})
    monkeypatch.setattr(tools, "IskiService", lambda **_kw: SimpleNamespace(nearby_faults=method))
    await tools.istanbul_nearby(kind="water_fault", lat=41, lon=29)
    method.assert_awaited_once_with(lat=41, lon=29, radius_m=1000, limit=None)


def test_legacy_surface_is_opt_in_and_ferry_has_separate_gate():
    compact = create_mcp_server(Settings())
    legacy = create_mcp_server(Settings(mcp_legacy_tools_enabled=True))
    enabled = create_mcp_server(Settings(mcp_legacy_tools_enabled=True, ferry_schedules_enabled=True))
    def names(server):
        return {tool.name for tool in asyncio.run(server.list_tools())}
    assert names(compact) == set(DEFAULT_TOOL_NAMES)
    assert names(legacy) == set(DEFAULT_TOOL_NAMES) | set(LEGACY_TOOL_NAMES)
    assert names(enabled) == names(legacy) | {"istanbul_ferry_schedules"}


def test_separate_http_apps_can_start_and_stop_independently():
    from starlette.testclient import TestClient
    from app.main import create_app

    for _ in range(2):
        with TestClient(create_app(), base_url="http://localhost") as client:
            result = client.post("/mcp/", headers={"accept": "application/json, text/event-stream"},
                                 json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
            assert result.status_code == 200
            assert len(result.json()["result"]["tools"]) == len(DEFAULT_TOOL_NAMES)
