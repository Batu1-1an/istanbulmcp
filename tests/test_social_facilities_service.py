import asyncio
import json
import time

import pytest

from app.connectors.social_facilities import SocialFacilitiesPayload
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.social_facilities import SocialFacilitiesService


class FakeClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def fetch(self):
        self.calls += 1
        return SocialFacilitiesPayload(
            rows=tuple(self.rows),
            reported_total=len(self.rows),
            received_total=len(self.rows),
            primary_source_url="https://fixture.test/catalog",
        )


class FailingClient:
    async def fetch(self):
        raise RuntimeError("fixture source unavailable")


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def _settings():
    return Settings(social_facilities_cache_ttl_seconds=3600, social_facilities_stale_if_error_seconds=604800)


@pytest.mark.asyncio
async def test_nearby_filters_radius_sorts_and_keeps_nullable_optional_keys():
    fake = FakeClient(
        [
            {"name": "Far", "latitude": 41.10, "longitude": 29.00},
            {"name": "Near", "latitude": 41.03, "longitude": 28.98, "detail_url": "https://example.test/near"},
        ]
    )
    result = await SocialFacilitiesService(settings=_settings(), client=fake).nearby(
        lat=41.0285, lon=28.9825, radius_m=2000, limit=1
    )
    assert result["ok"] is True
    assert [item["name"] for item in result["data"]] == ["Near"]
    item = result["data"][0]
    assert item["maps_url"].startswith("https://www.google.com/maps")
    assert item["source_id"] is None
    assert item["reservation_url"] is None
    assert "distance_m" in item


@pytest.mark.asyncio
async def test_invalid_input_does_not_call_source_and_empty_is_success():
    fake = FakeClient([])
    service = SocialFacilitiesService(settings=_settings(), client=fake)
    invalid = await service.nearby(lat=41.0, lon=28.0, radius_m=0)
    assert invalid["ok"] is False
    assert fake.calls == 0
    empty = await service.nearby(lat=41.0, lon=28.0, radius_m=1000)
    assert empty["ok"] is True
    assert empty["data"] == []
    outside = await service.nearby(lat=0.0, lon=0.0, radius_m=1000)
    assert outside["ok"] is True
    assert outside["data"] == []


@pytest.mark.asyncio
async def test_cache_hit_handles_twenty_queries_quickly_and_forbids_operational_fields():
    fake = FakeClient([{"name": "Test", "latitude": 41.0, "longitude": 28.9}])
    service = SocialFacilitiesService(settings=_settings(), client=fake)
    started = time.perf_counter()
    results = await asyncio.gather(*(service.nearby(lat=41.0, lon=28.9, radius_m=1000) for _ in range(20)))
    assert time.perf_counter() - started < 5
    assert fake.calls == 1
    assert all(not (set(item) & {"capacity", "occupancy", "availability", "queue", "open", "closed"}) for item in results[0]["data"])
    assert "capacity" not in json.dumps(results[0]).lower()


@pytest.mark.asyncio
async def test_snapshot_exposes_accounting_and_stale_warning_after_refresh_failure():
    settings = Settings(social_facilities_cache_ttl_seconds=0, social_facilities_stale_if_error_seconds=600)
    good = SocialFacilitiesService(
        settings=settings,
        client=FakeClient([{"name": "Test", "latitude": 41.0, "longitude": 28.9}]),
    )
    first = await good.nearby(lat=41.0, lon=28.9, radius_m=1000)
    assert first["sources"][0]["accepted_total"] == 1
    stale = await SocialFacilitiesService(settings=settings, client=FailingClient()).nearby(
        lat=41.0, lon=28.9, radius_m=1000
    )
    assert stale["ok"] is True
    assert stale["freshness"]["status"] == "stale"
    assert any("stale" in warning for warning in stale["warnings"])
