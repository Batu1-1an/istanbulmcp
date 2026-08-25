import json
import time
from pathlib import Path

import pytest

from app.connectors.istanbulkart import IstanbulkartPayload
from app.core.settings import Settings
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.source_cache import clear_source_cache
from app.services.istanbulkart import IstanbulkartService


FIXTURES = Path(__file__).parent / "fixtures" / "istanbulkart"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeClient:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.payload


def payload_from_fixtures() -> IstanbulkartPayload:
    page1 = load_fixture("datastore_page_1.json")["result"]
    page2 = load_fixture("datastore_page_2.json")["result"]
    package = load_fixture("package_show.json")["result"]
    resource = package["resources"][-1]
    return IstanbulkartPayload(
        rows=tuple(page1["records"] + page2["records"]),
        dataset_id=package["name"],
        resource_id=resource["id"],
        resource_year=2025,
        source_updated_at=resource["last_modified"],
        package_updated_at=package["metadata_modified"],
        schema_fields=tuple(field["id"] for field in page1["fields"]),
        reported_total=4,
    )


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


@pytest.mark.asyncio
async def test_nearby_normalizes_coordinates_sorts_and_limits():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(settings=Settings(default_limit=20), client=fake)

    response = await service.nearby(lat=41.038878, lon=28.961898, radius_m=5000, limit=2)

    assert response["ok"] is True
    assert len(response["data"]) == 2
    assert response["data"][0]["source_id"] == "301684"
    assert response["data"][0]["distance_m"] == 0.0
    assert response["data"][1]["latitude"] == pytest.approx(41.015354)
    assert response["data"][1]["longitude"] == pytest.approx(28.93314)
    assert response["data"][0]["maps_url"].startswith("https://www.google.com/maps/")
    assert response["sources"][0]["resource_id"] == "a40d07e1-5464-4c0d-b4fd-ff37c40ba162"
    assert response["freshness"]["source_updated_at"] == "2026-03-02T12:40:44.994009"


@pytest.mark.asyncio
async def test_invalid_input_does_not_call_upstream():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(settings=Settings(), client=fake)

    response = await service.nearby(lat=41.0, lon=29.0, radius_m=0)

    assert response["ok"] is False
    assert response["freshness"]["status"] == "unknown"
    assert fake.calls == 0


@pytest.mark.asyncio
async def test_valid_no_match_is_empty_success():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(settings=Settings(), client=fake)

    response = await service.nearby(lat=40.710, lon=27.900, radius_m=1000)

    assert response["ok"] is True
    assert response["data"] == []
    assert "0 İstanbulkart dolum merkezi" in response["summary"]
    assert response["sources"][0]["accepted_total"] == 4


@pytest.mark.asyncio
async def test_cache_hit_and_fresh_queries_are_fast():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(settings=Settings(), client=fake)

    durations = []
    for _ in range(20):
        start = time.perf_counter()
        await service.nearby(lat=41.038878, lon=28.961898)
        durations.append(time.perf_counter() - start)

    p95 = sorted(durations)[int(len(durations) * 0.95) - 1]
    assert p95 < 5
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_source_failure_is_structured():
    fake = FakeClient(error=RuntimeError("offline"))
    service = IstanbulkartService(settings=Settings(), client=fake)

    response = await service.nearby(lat=41.0, lon=29.0)

    assert response["ok"] is False
    assert response["freshness"]["status"] == "broken"
    assert response["data"][0]["error_code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_stale_snapshot_is_explicit_and_has_source_failure_warning():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(
        settings=Settings(istanbulkart_cache_ttl_seconds=0, istanbulkart_stale_if_error_seconds=600),
        client=fake,
    )
    first = await service.nearby(lat=41.038878, lon=28.961898)
    fake.error = RuntimeError("temporary outage")
    second = await service.nearby(lat=41.038878, lon=28.961898)

    assert first["freshness"]["status"] == "fresh"
    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert any("RuntimeError" in warning for warning in second["warnings"])


@pytest.mark.asyncio
async def test_stale_window_expiry_returns_broken_source_error():
    fake = FakeClient(payload_from_fixtures())
    service = IstanbulkartService(
        settings=Settings(istanbulkart_cache_ttl_seconds=0, istanbulkart_stale_if_error_seconds=0),
        client=fake,
    )
    await service.nearby(lat=41.038878, lon=28.961898)
    fake.error = RuntimeError("expired")
    response = await service.nearby(lat=41.038878, lon=28.961898)

    assert response["ok"] is False
    assert response["freshness"]["status"] == "broken"


@pytest.mark.asyncio
async def test_rate_limit_error_is_structured():
    fake = FakeClient(
        error=SourceRateLimitExceeded(source="ckan", retry_after_seconds=1.5)
    )
    service = IstanbulkartService(settings=Settings(), client=fake)

    response = await service.nearby(lat=41.0, lon=29.0)

    assert response["ok"] is False
    assert "rate limit" in response["warnings"][0].lower()
    assert response["limits"][0] == "source=ckan"


@pytest.mark.asyncio
async def test_quality_accounting_deduplicates_and_warns_without_fabricating_fields():
    package = load_fixture("package_show.json")["result"]
    resource = package["resources"][-1]
    payload = IstanbulkartPayload(
        rows=tuple(load_fixture("data_quality_rows.json")),
        dataset_id=package["name"],
        resource_id=resource["id"],
        resource_year=2025,
        source_updated_at=resource["last_modified"],
        package_updated_at=package["metadata_modified"],
        schema_fields=("terminal_id", "terminal_subtype_definition_desc_cd", "town_id", "longitude", "latitude"),
        reported_total=7,
    )
    fake = FakeClient(payload)
    service = IstanbulkartService(settings=Settings(), client=fake)

    response = await service.nearby(lat=41.038878, lon=28.961898, radius_m=5000, limit=100)

    assert response["ok"] is True
    assert response["sources"][0]["accepted_total"] == 2
    assert response["sources"][0]["skipped_total"] == 5
    assert len(response["data"]) == 2
    assert any("duplicate" in warning.lower() for warning in response["warnings"])
    assert any("no terminal type" in warning.lower() for warning in response["warnings"])
    assert all("status" not in row and "balance" not in row for row in response["data"])


@pytest.mark.asyncio
async def test_empty_source_is_success_with_counters():
    package = load_fixture("package_show.json")["result"]
    resource = package["resources"][-1]
    payload = IstanbulkartPayload(
        rows=(),
        dataset_id=package["name"],
        resource_id=resource["id"],
        resource_year=2025,
        source_updated_at=resource["last_modified"],
        package_updated_at=package["metadata_modified"],
        schema_fields=("terminal_id", "terminal_subtype_definition_desc_cd", "town_id", "longitude", "latitude"),
        reported_total=0,
    )
    response = await IstanbulkartService(settings=Settings(), client=FakeClient(payload)).nearby(
        lat=41.0, lon=29.0
    )

    assert response["ok"] is True
    assert response["data"] == []
    assert response["sources"][0]["reported_total"] == 0
