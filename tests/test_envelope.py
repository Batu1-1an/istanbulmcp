import pytest

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


@pytest.mark.parametrize("url", [
    "https://api.ibb.gov.tr",
    "https://api.ibb.gov.tr/tkmservices/api/TrafficData/v1",
    "https://api.ibb.gov.tr/iett/UlasimDinamikVeri/Duyurular.asmx",
    "https://iskiapi.iski.istanbul/api/iski/baraj/listesi/v2",
    "https://cbsproxy.ibb.gov.tr/?eczanews&ilceID=all",
    "https://data.ibb.gov.tr/api/3/action/datastore_search?resource_id=x",
    "https://data.ibb.gov.tr/dataset/x/resource/y/download/stops.csv",
    "https://harita.iski.gov.tr/data/baraj.json",
    "https://harita.iski.gov.tr/data/mahallelerKesinti.geojson",
    "https://example.test/ibb-sosyal-tesis-konumlar.XLSX",
    "http://sehirhatlari.istanbul/tr/iptal-seferler",
    "javascript:alert(1)",
    "",
])
def test_source_url_omits_api_endpoints_and_data_files_from_answers(url):
    for payload in (
        success_envelope(summary="ok", sources=[Source(name="Machine source", url=url)]),
        error_envelope(summary="failed", warning="down", sources=[Source(name="Machine source", url=url)]),
        success_envelope(summary="ok", sources=[Source(name="Copied").model_copy(update={"url": url})]),
    ):
        assert payload["sources"][0]["url"] is None
        assert payload["sources"][0]["name"] in {"Machine source", "Copied"}


@pytest.mark.parametrize("url", [
    "https://data.ibb.gov.tr",
    "https://data.ibb.gov.tr/dataset/iett-gtfs-verisi",
    "https://sehirhatlari.istanbul/tr/iptal-seferler",
    "https://www.metro.istanbul/MetroIstanbulBuzPateni2024/SeferDurumlari/Ariza",
    "https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-baraj-doluluk-oranlari",
    "https://tesislerimiz.ibb.istanbul/tesisler",
    "https://www.wikidata.org/w/index.php?title=Q1&oldid=2",
])
def test_source_url_keeps_human_readable_pages(url):
    payload = success_envelope(summary="ok", sources=[Source(name="Page source", url=url)])

    assert payload["sources"][0]["url"] == url
