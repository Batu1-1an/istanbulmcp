from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.pharmacy import IBB_CACHE_KEY, PharmacyService


FIXTURES = Path(__file__).parent / "fixtures" / "ibb_pharmacy"


def fixture_rows(name: str) -> list[dict]:
    payload = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    rows = payload["ArrayOfAramaList"]["AramaList"]
    return [rows] if isinstance(rows, dict) else rows


class FakeIbb:
    def __init__(self, rows: list[dict], error: Exception | None = None):
        self.rows = rows
        self.error = error
        self.calls = 0

    async def roster(self):
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def service(rows: list[dict], **kwargs):
    settings = Settings(**kwargs)
    client = FakeIbb(rows)
    return PharmacyService(settings=settings, ibb_client=client), client


@pytest.mark.asyncio
async def test_load_maps_ibb_fields_and_metadata():
    svc, _ = service(fixture_rows("roster_success.json"))
    cached = await svc._roster()
    assert len(cached.value.rows) == 3
    row = cached.value.rows[0]
    assert row["district_id"] == "1421"
    assert row["province"] == "İstanbul"
    assert row["duty_ends_at"] is None
    assert row["maps_url"].startswith("https://www.google.com/maps/search/")
    assert cached.metadata == {
        "scope": "İstanbul on-duty roster",
        "reported_total": 3,
        "received_total": 3,
        "accepted_total": 3,
        "skipped_total": 0,
        "invalid_total": 0,
        "duplicate_total": 0,
        "geo_eligible_total": 3,
    }
    result = await svc.by_district(district="Kadıköy")
    assert result["sources"][0]["operator"] == "ibb"


@pytest.mark.asyncio
async def test_domain_valid_rows_with_bad_coordinates_are_kept_but_not_geo_eligible():
    rows = fixture_rows("roster_invalid_rows.json")
    svc, _ = service(rows)
    cached = await svc._roster()
    assert len(cached.value.rows) == 3
    assert cached.metadata["accepted_total"] == 3
    assert cached.metadata["skipped_total"] == 2
    assert cached.metadata["geo_eligible_total"] == 1
    bad = next(row for row in cached.value.rows if row["name"] == "Bozuk Konum")
    assert bad["lat"] is None and bad["lon"] is None and bad["maps_url"] is None


@pytest.mark.asyncio
async def test_all_domain_invalid_nonempty_roster_is_source_failure_not_empty_success():
    rows = [{"ADI": "", "ADRES": "Adres", "ILCEADI": "Kadıköy", "ILCEID": "1"}]
    svc, _ = service(rows)
    result = await svc.by_district(district="Kadıköy")
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["data"][0]["error_code"] == "source_unavailable"


@pytest.mark.asyncio
async def test_dedup_is_deterministic_and_same_name_different_district_id_is_retained():
    svc, _ = service(fixture_rows("roster_duplicates.json"))
    cached = await svc._roster()
    assert len(cached.value.rows) == 2
    assert {row["district_id"] for row in cached.value.rows} == {"1421", "9999"}
    assert cached.metadata["duplicate_total"] == 1
    assert all(row["source_id"].startswith("ibb:") for row in cached.value.rows)


@pytest.mark.asyncio
async def test_nearby_sorts_by_distance_and_limits_after_sorting():
    svc, client = service(fixture_rows("roster_success.json"), default_limit=20)
    result = await svc.nearby(lat=40.9909, lon=29.0303, radius_m=5000, limit=2)
    assert result["ok"] is True
    assert len(result["data"]) == 2
    assert result["data"][0]["name"] == "Moda Eczanesi"
    assert all("distance_m" in row for row in result["data"])
    assert result["sources"][0]["name"].startswith("İBB")
    assert client.calls == 1


@pytest.mark.asyncio
async def test_nearby_invalid_input_does_not_fetch_source():
    svc, client = service(fixture_rows("roster_success.json"))
    result = await svc.nearby(lat=float("nan"), lon=29.0)
    assert result["ok"] is False
    assert result["data"][0]["field"] == "lat"
    assert client.calls == 0


@pytest.mark.asyncio
async def test_by_district_normalizes_exact_name_and_preserves_id_without_distance():
    svc, _ = service(fixture_rows("roster_success.json"))
    result = await svc.by_district(district=" kadikoy ")
    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["district_id"] == "1421"
    assert "distance_m" not in result["data"][0]
    assert any("mesafe" in warning.lower() for warning in result["warnings"])


@pytest.mark.asyncio
async def test_cache_is_shared_by_nearby_and_district():
    svc, client = service(fixture_rows("roster_success.json"))
    await svc.nearby(lat=40.99, lon=29.03)
    await svc.by_district(district="Kadıköy")
    assert client.calls == 1
    assert IBB_CACHE_KEY == "ibb_pharmacy.on_duty_pharmacies"


@pytest.mark.asyncio
async def test_rate_limit_and_source_errors_are_safe():
    settings = Settings()
    rate = SourceRateLimitExceeded(source="ibb_pharmacy", retry_after_seconds=4.0)
    svc = PharmacyService(settings=settings, ibb_client=FakeIbb([], error=rate))
    limited = await svc.by_district(district="Kadıköy")
    assert limited["ok"] is False
    assert limited["limits"][0] == "source=ibb_pharmacy"

    svc = PharmacyService(settings=settings, ibb_client=FakeIbb([], error=RuntimeError("private raw upstream body")))
    failed = await svc.by_district(district="Kadıköy")
    assert failed["ok"] is False
    assert "private raw upstream body" not in str(failed)
    assert failed["data"][0]["error_code"] == "source_unavailable"
    assert failed["sources"][0]["coverage_status"] == "unavailable"


@pytest.mark.asyncio
async def test_empty_roster_is_checked_empty_success():
    svc, _ = service([])
    result = await svc.by_district(district="Kadıköy")
    assert result["ok"] is True
    assert result["data"] == []
    assert result["freshness"]["status"] == "fresh"
    assert result["sources"][0]["reported_total"] == 0


@pytest.mark.asyncio
async def test_stale_snapshot_is_used_after_refresh_failure_within_age_cap():
    settings = Settings(ibb_pharmacy_cache_ttl_seconds=0, ibb_pharmacy_stale_if_error_seconds=1500)
    client = FakeIbb(fixture_rows("roster_success.json"))
    svc = PharmacyService(settings=settings, ibb_client=client)
    first = await svc.by_district(district="Kadıköy")
    assert first["freshness"]["status"] == "fresh"
    client.error = RuntimeError("upstream down")
    stale = await svc.by_district(district="Kadıköy")
    assert stale["ok"] is True
    assert stale["freshness"]["status"] == "stale"
    assert any("stale" in warning.lower() for warning in stale["warnings"])
