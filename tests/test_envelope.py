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
