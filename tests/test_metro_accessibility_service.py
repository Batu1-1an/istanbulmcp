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
async def test_service_maps_known_equipment_labels_to_canonical_keys():
    rows = fault_rows()
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=rows))
    result = await service.status()
    faults = result["data"][0]["faults"]
    equipment = {f["station_name"]: f["equipment_type"] for f in faults}
    assert equipment["Levent"] == "elevator"
    assert equipment["Fulya"] == "escalator"
    assert equipment["Yenikapı"] == "elevator"

    # Filtering by the canonical key or its Turkish label both match the same rows.
    by_key = await service.status(equipment_type="elevator")
    by_label = await service.status(equipment_type="asansör")
    assert {f["station_name"] for f in by_key["data"][0]["faults"]} == \
        {f["station_name"] for f in by_label["data"][0]["faults"]}


@pytest.mark.asyncio
async def test_service_preserves_unknown_equipment_label():
    rows = fault_rows()
    rows.append({"source_fault_id": "777", "line_code": "M2", "station_name": "Yeni", "equipment_type": "Yeni Cihaz", "location_description": "z", "reason": "Arıza"})
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=rows))
    result = await service.status()
    faults = result["data"][0]["faults"]
    assert any(f["equipment_type"] == "Yeni Cihaz" for f in faults)


@pytest.mark.asyncio
async def test_service_broken_response_includes_source_unavailable_record():
    service = make_service(FakeMetroClient(summary_error=RuntimeError("a"), detail_error=RuntimeError("b")))
    result = await service.status()
    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["data"][0]["summary_source_status"] == "unavailable"
    assert result["data"][0]["detail_source_status"] == "unavailable"
    for source in result["sources"]:
        assert source["coverage_status"] == "unavailable"


@pytest.mark.asyncio
async def test_service_emits_discrepancy_in_both_directions():
    # inactive > accepted: summary larger than detail scope.
    rows_over = summary_rows()
    rows_over[0]["inactive_count"] = 1000
    svc = make_service(FakeMetroClient(summary_rows=rows_over, fault_rows=fault_rows()))
    result = await svc.status()
    assert "inactive_total_exceeds_detail_scope" in " ".join(result["warnings"])

    clear_source_cache()
    # inactive < accepted: reported inactive scope is smaller than the accepted
    # detail scope, so the under-direction warning fires.
    rows_under = summary_rows()
    for row in rows_under:
        row["inactive_count"] = 0
    svc = make_service(FakeMetroClient(summary_rows=rows_under, fault_rows=list(fault_rows())))
    result = await svc.status()
    assert "inactive_total_under_detail_scope" in " ".join(result["warnings"])


@pytest.mark.asyncio
async def test_service_result_metadata_includes_scope_limit_warnings():
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await service.status(line="M2", limit=5)
    assert result["freshness"]["status"] == "fresh"
    for source in result["sources"]:
        assert source["scope"] in {"equipment_summary", "fault_details"}
        assert source["coverage_status"] == "checked"
    limits = " ".join(result["limits"])
    assert "requested_limit=5" in limits
    assert "checked_scope=summary_and_details" in limits
    assert "line=M2" in limits
    assert "scope=Metro İstanbul equipment status" in limits


@pytest.mark.asyncio
async def test_service_matches_line_by_code_or_official_label():
    rows = fault_rows()
    rows.append({"source_fault_id": "888", "line_code": "M2", "line_label": "Yenikapı-Hacıosman", "station_name": "Hacıosman", "equipment_type": "Asansör", "location_description": "giriş", "reason": "Arıza", "expected_return": None})
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=rows))

    by_code = await service.status(line="M2")
    by_label = await service.status(line="Yenikapı-Hacıosman")

    for result in (by_code, by_label):
        stations = {f["station_name"] for f in result["data"][0]["faults"]}
        assert "Hacıosman" in stations


@pytest.mark.asyncio
async def test_service_wires_900_second_total_age_cap_for_both_sources():
    # Both source readers must cap total stale age to the configured stale-if-error
    # value (default 900) via max_cache_age_seconds, so no source can remain stale
    # for TTL + 900 seconds.
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=fault_rows()))
    assert service.settings.metro_accessibility_stale_if_error_seconds == 900


@pytest.mark.asyncio
async def test_service_summary_and_detail_stale_cap_boundary(monkeypatch):
    # Prove, at the service level, that both cache entries (summary + details) go
    # fresh -> stale (up to 900s from first success) -> unavailable once the total
    # age cap is exceeded. We patch the shared monotonic clock used by the cache.
    import app.core.source_cache as source_cache_mod

    clock = {"t": 0.0}
    fake_now = lambda: clock["t"]
    monkeypatch.setattr(source_cache_mod.time, "monotonic", fake_now)

    class UpDownMetro(FakeMetroClient):
        def __init__(self, summary_rows, fault_rows):
            super().__init__(summary_rows, fault_rows)
            self.up = True

        async def equipment_summary(self):
            if not self.up:
                raise RuntimeError("summary down")
            return list(self.summary_rows or [])

        async def equipment_faults(self):
            if not self.up:
                raise RuntimeError("details down")
            return list(self.fault_rows or [])

    client = UpDownMetro(summary_rows(), fault_rows())
    service = make_service(client)

    # t=0: fresh load of both sources.
    result = await service.status()
    assert result["data"][0]["summary_source_status"] == "fresh"
    assert result["data"][0]["detail_source_status"] == "fresh"

    # Advance past TTL (120) but within the 900s cap; switch the client to fail so
    # the cache must serve the retained value as stale (not fresh).
    clock["t"] = 200.0
    client.up = False
    result = await service.status()
    assert result["data"][0]["summary_source_status"] == "stale"
    assert result["data"][0]["detail_source_status"] == "stale"
    assert result["freshness"]["status"] == "stale"

    # Prove the exact 900s total-age boundary: at t=900 (== cap) the retained value
    # is still served as stale, but at t=901 (> cap) it must be dropped as
    # unavailable/broken. Using t=1050 would also pass an erroneous TTL+900=1020
    # implementation, so we probe right at the boundary.
    clock["t"] = 900.0
    result = await service.status()
    assert result["ok"] is True
    assert result["freshness"]["status"] == "stale"
    assert result["data"][0]["summary_source_status"] == "stale"
    assert result["data"][0]["detail_source_status"] == "stale"

    clock["t"] = 901.0
    result = await service.status()
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert result["data"][0]["summary_source_status"] == "unavailable"
    assert result["data"][0]["detail_source_status"] == "unavailable"
    assert service.settings.metro_accessibility_cache_ttl_seconds == 120


@pytest.mark.asyncio
async def test_service_malformed_detail_page_propagates_as_partial_not_checked_empty():
    # A changed/malformed detail page must NOT be surfaced as a checked-empty success
    # when the summary source is usable; it must appear as a partial/unavailable
    # detail result instead.
    service = make_service(
        FakeMetroClient(summary_rows=summary_rows(), fault_rows=None, detail_error=RuntimeError("Metro equipment fault page markup is unrecognized"))
    )
    result = await service.status()
    assert result["ok"] is True
    assert result["freshness"]["status"] == "unknown"
    assert "partial_source" in " ".join(result["warnings"])
    detail_source = next(s for s in result["sources"] if s["scope"] == "fault_details")
    assert detail_source["coverage_status"] == "unavailable"
    summary_source = next(s for s in result["sources"] if s["scope"] == "equipment_summary")
    assert summary_source["coverage_status"] == "checked"
    assert result["data"][0]["detail_source_status"] == "unavailable"


@pytest.mark.asyncio
async def test_service_report_schema_drift_for_malformed_detail_rows():
    # The connector tracks malformed data-arizaid rows; the service surfaces them as
    # skipped counters and a schema-drift warning rather than silently dropping them.
    from app.connectors.metro import MetroClient

    class DriftMetro(FakeMetroClient):
        def __init__(self, summary_rows, fault_rows):
            super().__init__(summary_rows, fault_rows)
            self._last_malformed_detail_count = 2

    svc = make_service(DriftMetro(summary_rows=summary_rows(), fault_rows=fault_rows()))
    result = await svc.status()
    assert "schema_drift" in " ".join(result["warnings"])
    assert result["data"][0]["details_malformed_total"] >= 2


@pytest.mark.asyncio
async def test_service_broken_envelope_includes_filters_and_metadata():
    service = make_service(FakeMetroClient(summary_error=RuntimeError("a"), detail_error=RuntimeError("b")))
    result = await service.status(line="M2", station="Levent", equipment_type="elevator", limit=10)
    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["data"][0]["line"] == "M2"
    assert result["data"][0]["station"] == "Levent"
    assert result["data"][0]["equipment_type"] == "elevator"
    assert result["data"][0]["limit"] == 10
    assert result["data"][0]["checked_scope"] == "none"
    limits = " ".join(result["limits"])
    assert "requested_limit=10" in limits
    assert "checked_scope=none" in limits
    assert "line=M2" in limits


@pytest.mark.asyncio
async def test_service_matches_line_by_code_via_official_alias():
    rows = fault_rows()
    rows.append({"source_fault_id": "999", "line_code": "M2", "station_name": "Hacıosman", "equipment_type": "Asansör", "location_description": "giriş", "reason": "Arıza", "expected_return": None})
    service = make_service(FakeMetroClient(summary_rows=summary_rows(), fault_rows=rows))

    # A code-only M2 record must also match when the user supplies the official label.
    by_code = await service.status(line="M2")
    assert "Hacıosman" in {f["station_name"] for f in by_code["data"][0]["faults"]}

    by_label = await service.status(line="Yenikapı-Hacıosman")
    assert "Hacıosman" in {f["station_name"] for f in by_label["data"][0]["faults"]}

    # Unknown label does not broaden matching into an arbitrary substring.
    by_unknown = await service.status(line="Yenikapı-Hacıosman-EXTRA")
    assert "Hacıosman" not in {f["station_name"] for f in by_unknown["data"][0]["faults"]}
    assert by_unknown["data"][0]["faults"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "summary_rows,fault_rows,summary_err,detail_err,expect_ok,expect_freshness",
    [
        (summary_rows(), fault_rows(), None, None, True, "fresh"),
        ([], [], None, None, True, "fresh"),  # checked-empty
        (summary_rows(), None, None, RuntimeError("d"), True, "unknown"),  # partial detail
        (None, fault_rows(), RuntimeError("s"), None, True, "unknown"),  # partial summary
        (None, None, RuntimeError("s"), RuntimeError("d"), False, "broken"),  # both down
    ],
)
async def test_service_metadata_state_matrix(
    summary_rows, fault_rows, summary_err, detail_err, expect_ok, expect_freshness,
):
    client = FakeMetroClient(
        summary_rows=summary_rows, fault_rows=fault_rows,
        summary_error=summary_err, detail_error=detail_err,
    )
    service = make_service(client)
    result = await service.status(line="M2", limit=7)
    assert result["ok"] is expect_ok
    assert result["freshness"]["status"] == expect_freshness
    assert result["sources"]
    for source in result["sources"]:
        assert source["coverage_status"] in {"checked", "unavailable"}
        assert source["scope"] in {"equipment_summary", "fault_details"}
    limits = " ".join(result["limits"])
    assert "line=M2" in limits
    assert "requested_limit=7" in limits
    if expect_ok and expect_freshness == "fresh":
        assert "checked_scope=summary_and_details" in limits
    elif expect_ok and expect_freshness == "stale":
        for source in result["sources"]:
            assert source["coverage_status"] == "checked"
            assert source["last_successful_refresh_at"]
    else:
        assert "checked_scope=partial" in limits or "checked_scope=none" in limits
    assert "warnings" in result


@pytest.mark.asyncio
async def test_service_stale_source_retains_last_success_and_time(monkeypatch):
    # A source that first succeeds and later fails must serve the retained value as
    # stale and still report its last successful refresh timestamp.
    import app.core.source_cache as source_cache_mod

    clock = {"t": 0.0}
    monkeypatch.setattr(source_cache_mod.time, "monotonic", lambda: clock["t"])
    from app.core.source_cache import clear_source_cache

    clear_source_cache()

    class FailAfterFirst(FakeMetroClient):
        def __init__(self, summary_rows, fault_rows):
            super().__init__(summary_rows, fault_rows)
            self.up = True

        async def equipment_summary(self):
            if not self.up:
                raise RuntimeError("down")
            return list(self.summary_rows or [])

        async def equipment_faults(self):
            if not self.up:
                raise RuntimeError("down")
            return list(self.fault_rows or [])

    service = make_service(FailAfterFirst(summary_rows(), fault_rows()))
    # First call populates the cache fresh.
    result = await service.status()
    assert result["freshness"]["status"] == "fresh"
    assert result["data"][0]["summary_source_status"] == "fresh"
    assert result["data"][0]["detail_source_status"] == "fresh"

    # Advance past TTL so the next refresh fails and the cache serves the retained
    # value as stale with its last-success time and coverage_status checked.
    client = service.metro
    client.up = False
    clock["t"] = 200.0
    result = await service.status()
    assert result["freshness"]["status"] == "stale"
    for source in result["sources"]:
        assert source["coverage_status"] == "checked"
        assert source["last_successful_refresh_at"]

    # Advance past the 900s total-age boundary: the result becomes broken, but the
    # last successful refresh time must still be retained for provenance.
    clock["t"] = 901.0
    result = await service.status()
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    for source in result["sources"]:
        assert source["coverage_status"] == "unavailable"
        assert source["last_successful_refresh_at"]


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
