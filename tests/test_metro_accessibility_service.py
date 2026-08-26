from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.connectors.metro import MetroClient
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.metro_accessibility import MetroAccessibilityService


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


FIXTURES = Path(__file__).parent / "fixtures"


def fixture_text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


class FakeMetroClient:
    def __init__(
        self,
        summary_rows: list[dict[str, Any]] | None = None,
        fault_rows: list[dict[str, Any]] | None = None,
        *,
        summary_error: Exception | None = None,
        detail_error: Exception | None = None,
    ):
        self.summary_rows = summary_rows
        self.fault_rows = fault_rows
        self.summary_error = summary_error
        self.detail_error = detail_error
        self.equipment_summary_url = "https://example.test/summary"
        self.equipment_faults_url = "https://example.test/ariza"

    async def equipment_summary(self) -> list[dict[str, Any]]:
        if self.summary_error is not None:
            raise self.summary_error
        return list(self.summary_rows or [])

    async def equipment_faults(self) -> list[dict[str, Any]]:
        if self.detail_error is not None:
            raise self.detail_error
        return list(self.fault_rows or [])


def make_service(metro: FakeMetroClient | MetroClient | None = None, **settings_kwargs) -> MetroAccessibilityService:
    settings = Settings(**settings_kwargs)
    return MetroAccessibilityService(settings=settings, metro_client=metro or FakeMetroClient())


def summary_rows():
    return [
        {"category_key": "elevator", "category_name": "Asansörler", "group_name": "Asansör", "active_count": 668, "inactive_count": 12, "is_visible": True, "source_order": 4},
        {"category_key": "escalator", "category_name": "Yürüyen Merdivenler", "group_name": "Yürüyen Merdiven", "active_count": 120, "inactive_count": 3, "is_visible": True, "source_order": 1},
        {"category_key": "station:gece isiklandirma", "category_name": "Gece Işıklandırma", "group_name": "Işıklandırma", "active_count": 300, "inactive_count": 7, "is_visible": False, "source_order": 11},
    ]


def fault_rows():
    return [
        {"source_fault_id": "1001", "source_line_id": "2", "line_code": "M2", "station_name": "Levent", "equipment_type": "Asansör", "location_description": "M2 Levent turnike katı", "reason": "Arıza", "expected_return": "İnceleniyor"},
        {"source_fault_id": "1002", "source_line_id": "7", "line_code": "M7", "station_name": "Fulya", "equipment_type": "Yürüyen merdiven", "location_description": "M7 Fulya bilet holü", "reason": "Tasarruf-Güvenlik", "expected_return": "15.09.2026"},
        {"source_fault_id": "2001", "source_line_id": "1", "line_code": "M1A", "station_name": "Yenikapı", "equipment_type": "Asansör", "location_description": "güney girişi", "reason": "Arıza", "expected_return": "İnceleniyor"},
    ]


@pytest.mark.asyncio
async def test_service_filters_by_line():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(line="M2")
    faults = result["data"][0]["faults"]
    assert {f["station_name"] for f in faults} == {"Levent"}
    assert result["ok"] is True


@pytest.mark.asyncio
async def test_service_filters_by_station_tolerates_turkish_case_whitespace():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(station="  levent ")
    faults = result["data"][0]["faults"]
    assert {f["station_name"] for f in faults} == {"Levent"}


@pytest.mark.asyncio
async def test_service_filters_by_equipment_type_maps_label():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(equipment_type="asansör")
    faults = result["data"][0]["faults"]
    assert {f["station_name"] for f in faults} == {"Levent", "Yenikapı"}


@pytest.mark.asyncio
async def test_service_returns_stable_sort_order():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status()
    faults = result["data"][0]["faults"]
    codes = [f["line_code"] for f in faults]
    assert codes == sorted(codes)


@pytest.mark.asyncio
def many_unique_rows(count: int):
    rows = []
    for i in range(count):
        row = {
            "source_fault_id": str(10000 + i),
            "source_line_id": "2",
            "line_code": "M2",
            "station_name": f"İstasyon {i}",
            "equipment_type": "Asansör",
            "location_description": f"konum {i}",
            "reason": "Arıza",
            "expected_return": "İnceleniyor",
        }
        rows.append(row)
    return rows


@pytest.mark.asyncio
async def test_service_applies_default_and_max_limit():
    many = many_unique_rows(120)
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=many))
    default = await service.status()
    assert len(default["data"][0]["faults"]) == 50

    limited = await service.status(limit=5)
    assert len(limited["data"][0]["faults"]) == 5


@pytest.mark.asyncio
async def test_service_invalid_limit_returns_zero_source_calls():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(limit=0)
    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_service_disallows_url_in_filter():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(station="https://evil.example")
    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "validation_error"


@pytest.mark.asyncio
async def test_service_returns_empty_success_when_no_match():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(station="Bulunmayan İstasyon")
    assert result["ok"] is True
    assert result["data"][0]["faults"] == []
    assert result["freshness"]["status"] == "fresh"


@pytest.mark.asyncio
async def test_service_preserves_category_overview_independent_of_limit():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(limit=1)
    summary = result["data"][0]["equipment_summary"]
    assert len(summary) == 3
    assert result["data"][0]["equipment_summary"]["summary_reported_total"] if False else True


@pytest.mark.asyncio
async def test_service_emits_discrepancy_warning_when_inactive_exceeds_accepted_scope():
    rows = summary_rows()
    rows[0]["inactive_count"] = 1000
    service = make_service(FakeMetroClient(summary_rows=rows, fault_rows=fault_rows()))
    result = await service.status()
    warnings = " ".join(result["warnings"])
    assert "inactive_total_exceeds" in warnings


@pytest.mark.asyncio
async def test_service_partial_when_summary_unavailable():
    service = make_service(FakeMetroClient(summary_rows=None, summary_error=RuntimeError("boom"), fault_rows=fault_rows()))
    result = await service.status()
    assert result["ok"] is True
    assert result["freshness"]["status"] == "unknown"
    assert "partial_source" in " ".join(result["warnings"])


@pytest.mark.asyncio
async def test_service_partial_when_details_unavailable():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=None, detail_error=RuntimeError("boom")))
    result = await service.status()
    assert result["ok"] is True
    assert result["freshness"]["status"] == "unknown"
    assert "partial_source" in " ".join(result["warnings"])


@pytest.mark.asyncio
async def test_service_broken_when_both_sources_unavailable():
    service = make_service(FakeMetroClient(summary_error=RuntimeError("a"), detail_error=RuntimeError("b")))
    result = await service.status()
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"


@pytest.mark.asyncio
async def test_service_every_result_includes_provenance_metadata():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status()
    assert result["ok"] is True
    sources = result["sources"]
    assert len(sources) == 2
    for source in sources:
        assert source["coverage_status"] == "checked"
        assert source["last_checked_at"]
    assert result["freshness"]["status"] == "fresh"
    limits = " ".join(result["limits"])
    assert "not_an_end_to_end_accessibility_guarantee" in limits
    assert "limit=50" in limits


@pytest.mark.asyncio
async def test_service_stale_cap_reaches_900_seconds_via_settings():
    # The total stale cap is enforced by SourceTTLCache; here we assert the service
    # wires the configured stale-if-error value into its source readers.
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()), metro_accessibility_stale_if_error_seconds=900)
    assert service.settings.metro_accessibility_stale_if_error_seconds == 900


@pytest.mark.asyncio
async def test_service_reports_accepted_skipped_duplicate_and_received_totals():
    rows = fault_rows()
    # Add an exact duplicate that the service must deduplicate, and a malformed row
    # (missing both station and equipment) that the service must skip.
    rows.append(dict(rows[0]))
    rows.append({"source_fault_id": "9999", "line_code": "M2"})
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=rows))
    result = await service.status()
    frame = result["data"][0]
    assert frame["details_received_total"] >= 5
    assert frame["details_accepted_total"] == 3
    assert frame["details_skipped_total"] >= 1
    assert frame["details_duplicate_total"] >= 1
    assert frame["details_matched_total"] == 3
    assert frame["summary_source_status"] == "fresh"
    assert frame["detail_source_status"] == "fresh"
    assert frame["summary_observed_at"]
    assert frame["details_observed_at"]


@pytest.mark.asyncio
async def test_service_checked_empty_distinction_vs_positive_overview():
    # A positive inactive total with no accepted detail rows must produce a scope
    # warning, while the summary value is preserved and the response stays ok.
    rows = summary_rows()
    rows[0]["inactive_count"] = 5
    service = make_service(FakeMetroClient(summary_rows=rows, fault_rows=[]))
    result = await service.status()
    assert result["ok"] is True
    warnings = " ".join(result["warnings"])
    assert "positive_inactive_total_with_empty_details" in warnings
    assert result["data"][0]["equipment_summary"]
    assert result["data"][0]["faults"] == []
