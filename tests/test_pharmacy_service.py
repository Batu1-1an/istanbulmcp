from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.source_cache import clear_source_cache
from app.services.pharmacy import PharmacyService


FIXTURES = Path(__file__).parent / "fixtures" / "ieo"


def fixture_rows(name: str) -> list[dict]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))["eczaneler"]


class FakeIeo:
    def __init__(self, rows: list[dict], error: Exception | None = None):
        self.rows = rows
        self.error = error
        self.calls = 0

    async def markers(self) -> list[dict]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.rows


@pytest.fixture(autouse=True)
def reset_source_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def service(rows: list[dict], tmp_path) -> tuple[PharmacyService, FakeIeo]:
    client = FakeIeo(rows)
    settings = Settings(database_path=tmp_path / "pharmacy.sqlite3")
    return PharmacyService(settings=settings, ieo_client=client), client


@pytest.mark.asyncio
async def test_nearby_filters_yalova_deduplicates_and_sorts_by_distance(tmp_path):
    rows = fixture_rows("markers_success.json") + [
        {**fixture_rows("markers_success.json")[0], "eczane_ad": "Duplicate Moda"},
    ]
    svc, client = service(rows, tmp_path)

    result = await svc.nearby(lat=41.0200, lon=29.0200, radius_m=5000, limit=20)

    assert result["ok"] is True
    assert all(row["province"] == "İstanbul" for row in result["data"])
    assert "Yalova" not in {row["province"] for row in result["data"]}
    assert [row["source_id"] for row in result["data"]] == ["1003", "1002", "1001"]
    assert all(row["distance_m"] <= 5000 for row in result["data"])
    assert all(
        result["data"][index]["distance_m"] <= result["data"][index + 1]["distance_m"]
        for index in range(len(result["data"]) - 1)
    )
    assert result["sources"][0]["reported_total"] == 5
    assert result["sources"][0]["accepted_total"] == 3
    assert result["sources"][0]["skipped_total"] == 2
    assert client.calls == 1


@pytest.mark.asyncio
async def test_nearby_returns_normalized_fields_maps_url_and_defaults(tmp_path):
    svc, _ = service(fixture_rows("markers_success.json"), tmp_path)

    result = await svc.nearby(lat=40.9909, lon=29.0303)
    row = result["data"][0]

    assert result["ok"] is True
    assert result["limits"] == ["radius_m=1000", "limit=20", "scope=İstanbul on-duty roster"]
    assert row["name"] == "Moda Eczanesi"
    assert row["phone"] == "0216 555 10 01"
    assert row["area"] == "Moda"
    assert row["street"] == "Moda Caddesi"
    assert row["duty_ends_at"] is None
    assert row["maps_url"].startswith("https://www.google.com/maps/search/?api=1&query=")
    assert row["distance_m"] == 0.0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("kwargs", "field"),
    [
        ({"radius_m": 0}, "radius_m"),
        ({"radius_m": 5001}, "radius_m"),
        ({"limit": 0}, "limit"),
        ({"limit": 101}, "limit"),
    ],
)
async def test_nearby_validates_radius_and_limit(tmp_path, kwargs, field):
    svc, _ = service(fixture_rows("markers_success.json"), tmp_path)

    result = await svc.nearby(lat=40.9909, lon=29.0303, **kwargs)

    assert result["ok"] is False
    assert result["data"][0]["field"] == field
    assert result["freshness"]["status"] == "unknown"


@pytest.mark.asyncio
async def test_by_district_normalizes_turkish_characters_and_is_deterministic(tmp_path):
    rows = fixture_rows("markers_success.json")
    rows.append({**rows[0], "sicil": "1004", "eczane_ad": "Alfa Kadıköy", "ilce": "KADIKOY"})
    svc, _ = service(rows, tmp_path)

    accented = await svc.by_district(district="Kadıköy", limit=20)
    ascii_name = await svc.by_district(district="kadikoy", limit=20)

    assert accented["ok"] is True
    assert [row["source_id"] for row in accented["data"]] == ["1004", "1001"]
    assert [row["source_id"] for row in ascii_name["data"]] == ["1004", "1001"]
    assert all("distance_m" not in row for row in accented["data"])
    assert any("mesafe hesaplanmadı" in warning for warning in accented["warnings"])


@pytest.mark.asyncio
async def test_by_district_sorts_with_turkish_normalized_name_then_source_id(tmp_path):
    rows = fixture_rows("markers_success.json")
    rows.extend(
        [
            {**rows[0], "sicil": "2002", "eczane_ad": "Çınar Eczanesi"},
            {**rows[0], "sicil": "2003", "eczane_ad": "Ornek Eczanesi"},
            {**rows[0], "sicil": "2004", "eczane_ad": "Örnek Eczanesi"},
            {**rows[0], "sicil": "2005", "eczane_ad": "Beta Eczanesi"},
        ]
    )
    svc, _ = service(rows, tmp_path)

    result = await svc.by_district(district="Kadıköy", limit=20)

    assert result["ok"] is True
    assert [row["source_id"] for row in result["data"]] == [
        "2005",
        "2002",
        "1001",
        "2003",
        "2004",
    ]


@pytest.mark.asyncio
async def test_by_district_unknown_returns_empty_success(tmp_path):
    svc, _ = service(fixture_rows("markers_success.json"), tmp_path)

    result = await svc.by_district(district="Atlantis", limit=20)

    assert result["ok"] is True
    assert result["data"] == []
    assert "0 nöbetçi eczane" in result["summary"]


@pytest.mark.asyncio
async def test_by_district_applies_bounded_limit(tmp_path):
    rows = fixture_rows("markers_success.json")
    rows.append({**rows[0], "sicil": "1004", "eczane_ad": "Alfa Kadıköy"})
    svc, _ = service(rows, tmp_path)

    result = await svc.by_district(district="Kadıköy", limit=1)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["data"][0]["name"] == "Alfa Kadıköy"


@pytest.mark.asyncio
async def test_fresh_cache_then_stale_if_error_preserves_source_metadata(tmp_path):
    client = FakeIeo(fixture_rows("markers_success.json"))
    settings = Settings(
        database_path=tmp_path / "pharmacy.sqlite3",
        ieo_cache_ttl_seconds=0,
        ieo_stale_if_error_seconds=1800,
    )
    svc = PharmacyService(settings=settings, ieo_client=client)

    fresh = await svc.by_district(district="Kadıköy")
    client.error = RuntimeError("fixture source down")
    stale = await svc.by_district(district="Kadıköy")

    assert fresh["ok"] is True
    assert fresh["freshness"]["status"] == "fresh"
    assert stale["ok"] is True
    assert stale["freshness"]["status"] == "stale"
    assert any("stale" in warning for warning in stale["warnings"])
    assert stale["sources"][0]["accepted_total"] == 3
    assert client.calls == 2


@pytest.mark.asyncio
async def test_source_failure_is_broken_and_does_not_expose_exception_message(tmp_path):
    svc, _ = service([], tmp_path)
    svc.ieo = FakeIeo([], error=RuntimeError("private raw upstream body"))

    result = await svc.nearby(lat=40.9909, lon=29.0303)

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert "private raw upstream body" not in str(result)


@pytest.mark.asyncio
async def test_rate_limit_returns_structured_source_error(tmp_path):
    svc, _ = service([], tmp_path)
    svc.ieo = FakeIeo([], error=SourceRateLimitExceeded(source="ieo", retry_after_seconds=4.0))

    result = await svc.by_district(district="Kadıköy")

    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["limits"] == ["source=ieo", "retry_after_seconds=4.0"]
    assert "retry_after_seconds=4.0" in result["warnings"][0]


@pytest.mark.asyncio
async def test_missing_duty_end_is_nullable_and_warned(tmp_path):
    svc, _ = service(fixture_rows("markers_success.json"), tmp_path)

    result = await svc.by_district(district="Kadıköy")

    assert result["data"][0]["duty_ends_at"] is None
    assert any("bitiş zamanı tahmin edilmedi" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_invalid_rows_are_skipped_and_counted(tmp_path):
    svc, _ = service(fixture_rows("markers_invalid_rows.json"), tmp_path)

    result = await svc.by_district(district="Kadıköy")

    assert result["ok"] is True
    assert [row["source_id"] for row in result["data"]] == ["missing-coordinates", "1001"]
    missing = result["data"][0]
    assert missing["lat"] is None
    assert missing["lon"] == 29.0303
    assert missing["maps_url"] is None
    assert any("koordinat" in warning for warning in result["warnings"])
    assert result["sources"][0]["reported_total"] == 4
    assert result["sources"][0]["accepted_total"] == 2
    assert result["sources"][0]["skipped_total"] == 2


@pytest.mark.asyncio
async def test_missing_coordinates_are_kept_for_district_but_excluded_from_nearby(tmp_path):
    rows = fixture_rows("markers_success.json")
    rows.append(
        {
            **rows[0],
            "sicil": "missing-coordinate-row",
            "eczane_ad": "Koordinatsız Kadıköy",
            "lat": "invalid",
            "lng": "invalid",
        }
    )
    svc, _ = service(rows, tmp_path)

    district = await svc.by_district(district="Kadıköy", limit=20)
    nearby = await svc.nearby(lat=40.9909, lon=29.0303, radius_m=1000, limit=20)

    assert "Koordinatsız Kadıköy" in {row["name"] for row in district["data"]}
    assert "Koordinatsız Kadıköy" not in {row["name"] for row in nearby["data"]}
    assert any("konum" in warning for warning in district["warnings"])
    assert any("konum" in warning for warning in nearby["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "kwargs", "field", "allowed_max"),
    [
        ("nearby", {"lat": 40.9909, "lon": 29.0303, "radius_m": 5001}, "radius_m", 5000),
        ("nearby", {"lat": 40.9909, "lon": 29.0303, "limit": 101}, "limit", 100),
        ("by_district", {"district": "Kadıköy", "limit": 101}, "limit", 100),
    ],
)
async def test_ieo_limits_remain_bounded_when_global_settings_are_broader(
    tmp_path, method, kwargs, field, allowed_max
):
    client = FakeIeo(fixture_rows("markers_success.json"))
    settings = Settings(
        database_path=tmp_path / "pharmacy.sqlite3",
        max_radius_m=50_000,
        max_limit=1_000,
    )
    svc = PharmacyService(settings=settings, ieo_client=client)

    result = await getattr(svc, method)(**kwargs)

    assert result["ok"] is False
    assert result["data"][0]["field"] == field
    assert result["data"][0]["allowed_max"] == allowed_max


@pytest.mark.asyncio
async def test_repeated_fresh_refresh_and_cache_hit_p95_performance_are_bounded(tmp_path):
    fresh_client = FakeIeo(fixture_rows("markers_success.json"))
    fresh_settings = Settings(
        database_path=tmp_path / "fresh.sqlite3",
        ieo_cache_ttl_seconds=0,
    )
    fresh_service = PharmacyService(settings=fresh_settings, ieo_client=fresh_client)
    fresh_durations = []
    for _ in range(20):
        started = time.perf_counter()
        await fresh_service.nearby(lat=40.9909, lon=29.0303, radius_m=1000, limit=5)
        fresh_durations.append(time.perf_counter() - started)

    clear_source_cache()
    hit_client = FakeIeo(fixture_rows("markers_success.json"))
    hit_service = PharmacyService(
        settings=Settings(database_path=tmp_path / "hit.sqlite3"),
        ieo_client=hit_client,
    )
    await hit_service.nearby(lat=40.9909, lon=29.0303, radius_m=1000, limit=5)
    hit_durations = []
    for _ in range(20):
        started = time.perf_counter()
        await hit_service.nearby(lat=40.9909, lon=29.0303, radius_m=1000, limit=5)
        hit_durations.append(time.perf_counter() - started)

    def p95(samples: list[float]) -> float:
        return sorted(samples)[max(0, int(len(samples) * 0.95) - 1)]

    assert p95(fresh_durations) < 5
    assert p95(hit_durations) < 5
    assert fresh_client.calls == 20
    assert hit_client.calls == 1
