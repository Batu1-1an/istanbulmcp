from app.core.envelope import Freshness, Source, error_envelope, success_envelope


def test_success_envelope_includes_source_and_freshness():
    envelope = success_envelope(
        summary="ok",
        data=[{"value": 1}],
        sources=[Source(name="Test Source")],
        freshness=Freshness(status="fresh", ttl_seconds=60),
        limits=["limit=20"],
    )

    assert envelope["ok"] is True
    assert envelope["summary"] == "ok"
    assert envelope["sources"][0]["name"] == "Test Source"
    assert envelope["freshness"]["status"] == "fresh"
    assert envelope["limits"] == ["limit=20"]


def test_error_envelope_is_structured():
    envelope = error_envelope(summary="failed", warning="source unavailable")

    assert envelope["ok"] is False
    assert envelope["freshness"]["status"] == "broken"
    assert envelope["warnings"] == ["source unavailable"]


def test_source_preserves_gtfs_refresh_context():
    source = Source(
        name="GTFS stops",
        dataset_id="iett-gtfs-verisi",
        resource_id="resource-current",
        source_updated_at="2026-08-24T08:00:00Z",
        last_successful_refresh_at="2026-08-24T08:05:00Z",
        scope="all_active_datastore_records",
        reported_total=102,
        received_total=102,
        accepted_total=101,
        skipped_total=1,
    )

    payload = source.model_dump(mode="json")

    assert payload["resource_id"] == "resource-current"
    assert payload["last_successful_refresh_at"] == "2026-08-24T08:05:00Z"
    assert payload["reported_total"] == 102
    assert payload["accepted_total"] == 101
    assert payload["skipped_total"] == 1


def test_source_preserves_transport_coverage_context_without_changing_envelope_shape():
    source = Source(
        name="Metro İstanbul Service Status",
        operator="metro_istanbul",
        modes=["metro", "tram", "funicular", "cable_car"],
        coverage_kind="live_status",
        coverage_status="checked",
        last_checked_at="2026-08-25T12:00:00Z",
    )

    payload = success_envelope(
        summary="checked",
        data=[{"operator": "metro_istanbul", "mode": "tram", "message": "delay"}],
        sources=[source],
        freshness=Freshness(status="fresh", ttl_seconds=120),
    )

    assert payload["data"][0]["operator"] == "metro_istanbul"
    assert "source" not in payload["data"][0]
    assert payload["sources"][0]["operator"] == "metro_istanbul"
    assert payload["sources"][0]["coverage_status"] == "checked"
    assert payload["sources"][0]["modes"] == ["metro", "tram", "funicular", "cable_car"]
    assert payload["freshness"]["ttl_seconds"] == 120
