"""Additive error and result contracts; no external source calls."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.core.envelope import Pagination, Repair, ResponseEnvelope, Source, error_envelope, result_info, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.core.validation import InputValidationError
from app.services.catalog import CatalogService
from app.services.city import CityService
from app.services.transit import TransitService
from tests.test_catalog_service import CountingCkan, RateLimitedCkan
from tests.test_city_service import FakeIspark, service as city_service
from tests.test_transit_service import FakeIett


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def test_unknown_completeness_is_not_claimed_as_complete_or_pageable():
    payload = success_envelope(summary="Unknown scope", data=[{"name": "test"}])
    assert payload["error"] is None
    assert payload["result_info"]["returned"] == 1
    assert payload["result_info"]["matched"] is None
    assert payload["result_info"]["truncated"] is None
    assert "unknown" in payload["result_info"]["next_step"]
    assert "next_offset" not in payload["result_info"]
    assert ResponseEnvelope.model_validate(payload).model_dump(mode="json") == payload


@pytest.mark.parametrize("returned,matched,truncated", [(0, 0, False), (1, 1, False), (1, 2, True)])
def test_known_counts_distinguish_full_empty_and_truncated(returned, matched, truncated):
    info = result_info(returned=returned, matched=matched)
    assert info.truncated is truncated
    assert bool(info.next_step) is truncated


def test_pagination_estimate_does_not_become_an_exact_matched_count():
    payload = success_envelope(summary="Page", data=[{}],
                               pagination=Pagination(limit=1, offset=2, total_estimate=5))
    assert payload["result_info"]["truncated"] is True
    assert payload["result_info"]["matched"] is None


def test_validation_keeps_legacy_details_and_exposes_repair():
    repair = Repair(next_step="Inspect schema", tool="istanbul_get_resource_schema", arguments={"resource_id": "r"})
    payload = validation_error_envelope(InputValidationError("Unknown field", field="filters"), repair=repair)
    assert payload["data"][0]["error_code"] == "validation_error"
    assert payload["error"] == {
        "code": "validation_error", "temporary": False, "retry_after_ms": None,
        "field": "filters", "repair": repair.model_dump(mode="json"),
    }
    assert payload["result_info"]["scope"] == "error_details"


@pytest.mark.parametrize("seconds,expected", [(1.25, 1250), (0, 0), (.0001, 1)])
def test_retry_delay_is_machine_readable_without_removing_seconds(seconds, expected):
    payload = error_envelope(summary="Rate limited", warning="Retry later",
                             data=[{"retry_after_seconds": seconds}])
    assert payload["error"]["code"] == "source_rate_limited"
    assert payload["error"]["temporary"] is True
    assert payload["error"]["retry_after_ms"] == expected
    assert payload["data"][0]["retry_after_seconds"] == seconds


@pytest.mark.parametrize("delay", [float("nan"), float("inf"), -1, True, "60"])
def test_invalid_retry_delays_do_not_produce_retry_instructions(delay):
    payload = error_envelope(summary="Failure", warning="No delay supplied", data=[{"retry_after_seconds": delay}])
    assert payload["error"]["code"] == "request_failed"
    assert payload["error"]["retry_after_ms"] is None


def test_permanent_error_never_advertises_retry_delay():
    payload = error_envelope(summary="Disabled", warning="No source checked", code="feature_disabled",
                             retry_after_ms=60000, data=[{"retry_after_seconds": 60}])
    assert payload["error"]["temporary"] is False
    assert payload["error"]["retry_after_ms"] is None


def test_source_error_omits_private_exception_text():
    payload = source_error_envelope(summary="Unavailable", warning="Source failed", exception=RuntimeError("secret-path-token"))
    assert payload["error"]["code"] == "source_unavailable"
    assert payload["error"]["temporary"] is True
    assert "secret-path-token" not in str(payload)


@pytest.mark.asyncio
async def test_catalog_repair_points_to_real_schema_tool(tmp_path):
    ckan = CountingCkan()
    service = CatalogService(settings=Settings(database_path=tmp_path / "city.db"), client=ckan)
    payload = await service.query_resource(resource_id="resource-1", filters={"wrong": "x"})
    assert payload["error"]["repair"]["tool"] == "istanbul_get_resource_schema"
    assert payload["error"]["repair"]["arguments"] == {"resource_id": "resource-1"}
    assert ckan.datastore_search_calls == 1  # Schema only; invalid filters were not queried.


@pytest.mark.asyncio
async def test_catalog_rate_limit_has_standard_code_and_milliseconds(tmp_path):
    service = CatalogService(settings=Settings(database_path=tmp_path / "city.db"), client=RateLimitedCkan())
    payload = await service.search_datasets(query="trafik")
    assert payload["error"]["code"] == "source_rate_limited"
    assert payload["error"]["retry_after_ms"] == 1250


@pytest.mark.asyncio
async def test_catalog_truncation_uses_source_total_without_invented_cursor(tmp_path):
    ckan = SimpleNamespace(datastore_search=AsyncMock(return_value={"records": [{"x": 1}], "total": 137}))
    service = CatalogService(settings=Settings(database_path=tmp_path / "city.db"), client=ckan)
    payload = await service.query_resource(resource_id="resource-1", limit=1)
    assert payload["result_info"]["matched"] == 137
    assert payload["result_info"]["truncated"] is True
    assert "cursor" not in payload["result_info"]


@pytest.mark.asyncio
async def test_terminal_departures_and_disruptions_report_pre_limit_counts(tmp_path):
    service = TransitService(settings=Settings(database_path=tmp_path / "city.db"), iett_client=FakeIett())
    departures = await service.planned_departures(line_code="34A", limit=1)
    disruptions = await service.disruptions(limit=1)
    assert departures["result_info"]["matched"] == 4
    assert disruptions["result_info"]["matched"] == 2
    assert departures["result_info"]["truncated"] and disruptions["result_info"]["truncated"]
    assert departures["data"][0]["realtime"] is False
    assert departures["data"][0]["schedule_relationship"] == "STATIC"


@pytest.mark.parametrize("limit,truncated", [(1, True), (2, False)])
@pytest.mark.asyncio
async def test_geographic_lists_look_one_row_ahead_without_changing_output_limit(tmp_path, limit, truncated):
    parks = FakeIspark()
    original = await parks.parks()
    parks.parks = AsyncMock(return_value=[original[0], {**original[0], "parkID": 3}])
    service = CityService(settings=Settings(database_path=tmp_path / "city.db"), ispark_client=parks)
    payload = await service.parking_nearby(lat=40.9909, lon=29.0303, limit=limit)
    assert len(payload["data"]) == limit
    assert payload["result_info"]["truncated"] is truncated
    assert payload["result_info"]["matched"] is None


@pytest.mark.asyncio
async def test_composite_sections_report_truncation_without_exposing_lookahead(tmp_path):
    svc = city_service(tmp_path)
    svc._libraries_for_district = AsyncMock(return_value=[{"name": str(i)} for i in range(3)])
    svc._cultural_centres_for_district = AsyncMock(return_value=([], Source(name="Culture", matched_total=0)))
    result = await svc.city_services_nearby(district="Kadıköy", limit=2)
    row = result["data"][0]
    assert len(row["libraries"]) == 2
    assert row["result_info"]["libraries"]["truncated"] is True
    assert row["result_info"]["libraries"]["matched"] is None
    assert row["result_info"]["wifi_locations"]["truncated"] is None
    assert row["result_info"]["cultural_centres"]["matched"] == 0
