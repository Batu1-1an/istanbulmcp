"""District and reference-point contracts; all external data is mocked."""
from unittest.mock import AsyncMock
import json

import pytest
from mcp import Client

from app.core.envelope import Source
from app.core.settings import Settings
from app.mcp.registry import create_mcp_server
from app.services.places import district_names
from tests.test_city_service import service


@pytest.mark.asyncio
@pytest.mark.parametrize("district", district_names())
@pytest.mark.parametrize("argument", ["place", "district"])
async def test_city_services_supports_every_district_without_inventing_coordinates(tmp_path, district, argument):
    svc = service(tmp_path)
    svc._wifi_nearby = AsyncMock(side_effect=AssertionError("No point provided"))
    svc._libraries_for_district = AsyncMock(return_value=[{"name": "Fixture library", "district": district}])
    svc._cultural_centres_for_district = AsyncMock(return_value=([], Source(name="Fixture culture", matched_total=0)))

    result = await svc.city_services_nearby(**{argument: district}, limit=2)

    assert result["ok"] is True
    row = result["data"][0]
    assert row["query"] == {"district": district, "scope": "district", "distance_included": False}
    assert row["wifi_locations"] == []
    assert len(row["libraries"]) == 1
    svc._libraries_for_district.assert_awaited_once_with(district, limit=2)
    svc._wifi_nearby.assert_not_awaited()
    assert all(source["coverage_status"] == "checked" for source in result["sources"])
    assert any("WiFi was not checked" in warning for warning in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("district", district_names())
async def test_mobility_accepts_every_explicit_district_without_radius_search(tmp_path, district):
    svc = service(tmp_path)
    svc._resolve_location = lambda **_: pytest.fail("Districts must not be geocoded")
    result = await svc.mobility_nearby(district=district, limit=2)
    assert result["ok"] is True
    assert result["data"][0]["query"]["district"] == district
    assert result["data"][0]["query"]["distance_included"] is False
    assert any("were not checked" in warning for warning in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["city_services_nearby", "mobility_nearby"])
@pytest.mark.parametrize("arguments,field", [
    ({"district": "Atlantis"}, "district"),
    ({"district": ""}, "district"),
    ({"district": "x" * 81}, "district"),
    ({"district": "Pendik", "place": "Bostancı"}, "district"),
    ({"district": "Pendik", "lat": 41}, "district"),
    ({"district": "Pendik", "lon": 29}, "district"),
    ({"district": "Pendik", "limit": 0}, "limit"),
    ({"district": "Pendik", "radius_m": 5001}, "radius_m"),
    ({"place": "Pendik", "radius_m": 0}, "radius_m"),
    ({"place": "Unknown street Pendik"}, "place"),
    ({"place": "Bostancı, Üsküdar"}, "place"),
])
async def test_invalid_district_or_place_queries_fail_before_loading_sources(tmp_path, method, arguments, field):
    svc = service(tmp_path)
    svc._ispark_parks = AsyncMock(side_effect=AssertionError("Invalid input must not load"))
    svc._wifi_nearby = AsyncMock(side_effect=AssertionError("Invalid input must not load"))
    svc._libraries_for_district = AsyncMock(side_effect=AssertionError("Invalid input must not load"))
    result = await getattr(svc, method)(**arguments)
    assert result["ok"] is False
    assert result["data"][0]["field"] == field
    svc._ispark_parks.assert_not_awaited()
    svc._wifi_nearby.assert_not_awaited()
    svc._libraries_for_district.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["city_services_nearby", "mobility_nearby"])
async def test_bare_acibadem_reports_ambiguity_instead_of_selecting_a_district(tmp_path, method):
    result = await getattr(service(tmp_path), method)(place="Acıbadem")
    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "ambiguous_place"
    assert "Kadıköy" in result["summary"] and "Üsküdar" in result["summary"]


@pytest.mark.asyncio
@pytest.mark.parametrize("place", ["Bostancı", "Karaköy", "Nişantaşı", "Acıbadem, Kadıköy", "Acıbadem, Üsküdar"])
async def test_point_queries_expose_reference_provenance_and_license(tmp_path, place):
    result = await service(tmp_path).city_services_nearby(place=place)
    assert result["ok"] is True
    query = result["data"][0]["query"]
    assert query["coordinate_scope"] == "area_reference_point"
    assert query["source_checked_on"] == "2026-10-25"
    source = next(source for source in result["sources"] if source["scope"] == "static_place_reference")
    assert source["publisher"] == "Wikidata contributors"
    assert source["license"] == "CC0-1.0"
    assert f"oldid={query['source_revision']}" in source["url"]
    assert any("not an exact address" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_district_source_failure_is_not_a_fresh_empty_result(tmp_path):
    svc = service(tmp_path)
    svc._libraries_for_district = AsyncMock(side_effect=TimeoutError())
    partial = await svc.city_services_nearby(district="Pendik")
    assert partial["ok"] is True
    assert partial["freshness"]["status"] == "unknown"
    assert {s["coverage_status"] for s in partial["sources"]} == {"checked", "unavailable"}

    svc._cultural_centres_for_district = AsyncMock(side_effect=TimeoutError())
    unavailable = await svc.city_services_nearby(district="Pendik")
    assert unavailable["ok"] is False
    assert unavailable["freshness"]["status"] == "broken"
    assert unavailable["data"][0]["error_code"] == "source_unavailable"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["legacy", "2026-07-28"])
@pytest.mark.parametrize("name", ["istanbul_city_services_nearby", "istanbul_mobility_nearby"])
async def test_mcp_accepts_district_and_keeps_ambiguity_structured_in_text(mode, name, tmp_path, monkeypatch):
    svc = service(tmp_path)
    monkeypatch.setattr("app.mcp.server.CityService", lambda **_: svc)
    async with Client(create_mcp_server(Settings()), mode=mode) as client:
        listed = await client.list_tools()
        schema = next(t.input_schema for t in listed.tools if t.name == name)
        assert "district" in schema["properties"]
        assert "district" not in schema.get("required", [])

        district = await client.call_tool(name, {"district": "Pendik", "limit": 2})
        assert district.is_error is False
        payload = json.loads(district.content[0].text)
        assert payload["ok"] is True
        assert payload["data"][0]["query"]["scope"] == "district"

        ambiguous = await client.call_tool(name, {"place": "Acıbadem"})
        assert ambiguous.is_error is False
        assert json.loads(ambiguous.content[0].text)["data"][0]["error_code"] == "ambiguous_place"
