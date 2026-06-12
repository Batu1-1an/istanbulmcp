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
