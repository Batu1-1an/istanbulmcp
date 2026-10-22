"""Offline HTTP/SQLite/protocol regressions against a small official CSV excerpt."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import time
from unittest.mock import AsyncMock

import httpx
from mcp import Client
import pytest
import pytest_asyncio

from app.connectors.ckan import CkanClient, CkanError
from app.connectors.gtfs import (
    GTFS_METADATA_MAX_BYTES, GtfsStopsClient, GtfsStopsError,
    parse_gtfs_coordinate, validate_gtfs_settings,
)
from app.core.settings import Settings, get_settings
from app.core.source_cache import clear_source_cache, source_cache
from app.mcp.registry import create_mcp_server
import app.mcp.server as handlers
from app.services.city import CityService

FIXTURES = Path(__file__).parent / "fixtures" / "gtfs"
ORIGIN = {"lat": 41.01917, "lon": 28.684353}
STOP_ARGS = {**ORIGIN, "types": ["public_transport_stop"], "radius_m": 2000, "limit": 10}
GOOD_CSV = b"stop_id,stop_name,stop_lat,stop_lon\n1,Stop,41.01917,28.684353\n"


class Limiter:
    def __init__(self):
        self.calls = []

    async def acquire(self, source):
        self.calls.append(source)


class Stream(httpx.AsyncByteStream):
    def __init__(self, *, slow=False, block=False):
        self.closed = False
        self.reads = 0
        self.slow = slow
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def __aiter__(self):
        self.started.set()
        await self.release.wait()
        if self.slow:
            await asyncio.sleep(10)
        for _ in range(4):
            self.reads += 1
            yield b"x" * 65536

    async def aclose(self):
        self.closed = True


class Harness:
    def __init__(self, tmp_path):
        self.settings = Settings(database_path=tmp_path / "gtfs.sqlite3")
        self.package = json.loads((FIXTURES / "package.json").read_text())
        self.body = (FIXTURES / "ibb_stops_sample.csv").read_bytes()
        self.response_factory = None
        self.offline = False
        self.datastore_factory = None
        self.calls = []
        self.limiter = Limiter()

    async def handle(self, request):
        self.calls.append(request)
        assert request.headers["accept-encoding"] == "identity"
        if self.offline:
            raise httpx.ConnectError("fixture unavailable", request=request)
        if request.url.path == "/api/3/action/package_show":
            assert request.method == "POST"
            assert json.loads(request.content) == {"id": "iett-gtfs-verisi"}
            return httpx.Response(200, json={"success": True, "result": self.package})
        if request.url.path == "/api/3/action/datastore_search":
            payload = json.loads(request.content)
            assert payload["sort"] == "_id asc" and payload["include_total"] is True
            assert payload["limit"] == 100 and payload["offset"] <= 50000
            return httpx.Response(200, json={"success": True, "result": self.datastore_factory(payload)})
        if request.url.path.endswith("/download/stops.csv"):
            assert request.method == "GET"
            if self.response_factory is not None:
                return self.response_factory()
            return httpx.Response(200, content=self.body, headers={"content-type": "text/csv; charset=utf-8"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    def client(self, settings=None):
        return GtfsStopsClient(settings=settings or self.settings, ckan_client=self.ckan,
                               http_client=self.http, rate_limiter=self.limiter)

    def service(self, settings=None):
        settings = settings or self.settings
        return CityService(settings=settings, ckan_client=self.ckan, gtfs_client=self.client(settings))


@pytest_asyncio.fixture
async def harness(tmp_path):
    clear_source_cache()
    fixture = Harness(tmp_path)
    async with httpx.AsyncClient(transport=httpx.MockTransport(fixture.handle), follow_redirects=True) as http:
        fixture.http = http
        fixture.ckan = CkanClient(http_client=http, rate_limiter=fixture.limiter)
        yield fixture
    clear_source_cache()


def gtfs_entry():
    return next(entry for key, entry in source_cache._entries.items() if key.startswith("ckan.public_gtfs.stops.v2."))


def expire_gtfs(*, beyond_stale=False):
    entry = gtfs_entry()
    entry.expires_at_monotonic = time.monotonic() - (604801 if beyond_stale else 1)
    if beyond_stale:
        entry.max_age_at_monotonic = time.monotonic() - 1
    return entry


def seed_old(service):
    service.geo.upsert_features([{
        "id": "gtfs_stop:old", "source": "gtfs", "feature_type": "public_transport_stop",
        "source_id": "old", "name": "Old", **ORIGIN,
    }])


def indexed_ids(service):
    return [row["source_id"] for row in service.geo.nearby(**ORIGIN, radius_m=2000, limit=10, types=["public_transport_stop"])]


def gtfs_source(result):
    return next(source for source in result["sources"] if source.get("dataset_id") == "iett-gtfs-verisi")


@pytest.mark.asyncio
async def test_official_fixture_uses_two_requests_not_stop_times_datastore(harness):
    payload = await harness.client().fetch()
    assert len(payload.rows) == 7
    assert payload.resource["id"] == "2299bc82-983b-4bdf-8520-5cef8c555e29"
    assert payload.resource["datastore_active"] is False
    assert payload.received_bytes == len(harness.body)
    assert payload.scope == "complete_stops_csv"
    assert len(harness.calls) == 2
    assert not any("stop_times" in str(request.url) or "datastore" in str(request.url) for request in harness.calls)
    assert harness.limiter.calls == ["ckan", "ckan"]


@pytest.mark.asyncio
async def test_csv_nearby_bbox_counts_unicode_maps_and_cache_hit(harness):
    service = harness.service()
    result = await service.nearby(**STOP_ARGS)
    assert result["ok"] is True and result["freshness"]["status"] == "fresh"
    assert len(result["data"]) == 3
    assert result["data"][0]["name"] == "RIFAT ILGAZ CADDESİ"
    assert result["data"][0]["lat"] == pytest.approx(41.0191700005564)
    assert all(row["maps_url"].startswith("https://www.google.com/maps/search/") for row in result["data"])
    distances = [row["distance_m"] for row in result["data"]]
    assert distances == sorted(distances)
    source = gtfs_source(result)
    assert {key: source[key] for key in ("received_total", "accepted_total", "skipped_total")} == {
        "received_total": 7, "accepted_total": 3, "skipped_total": 4,
    }
    assert source["source_updated_at"] == "2026-03-17T12:25:15.191826"
    assert source["coverage_status"] == "checked"
    assert "gtfs_max_rows=50000" in result["limits"]
    assert "gtfs_max_bytes=5242880" in result["limits"]
    assert "gtfs_load_timeout_seconds=20" in result["limits"]
    assert any("static" in warning for warning in result["warnings"])
    assert any("Skipped 4" in warning for warning in result["warnings"])
    assert any("Normalized 3" in warning for warning in result["warnings"])
    bbox = await service.bbox_search(bbox=[28.68, 41.0, 28.70, 41.03], types=["public_transport_stop"])
    assert bbox["ok"] and len(bbox["data"]) == 3
    assert len(harness.calls) == 2


@pytest.mark.asyncio
async def test_checked_empty_is_success_only_after_valid_snapshot_loaded(harness):
    result = await harness.service().nearby(lat=41.3, lon=29.5, types=["public_transport_stop"])
    assert result["ok"] is True and result["data"] == []
    assert gtfs_source(result)["coverage_status"] == "checked"


@pytest.mark.parametrize("value,axis,expected", [
    ("410.191.700.005.564", "lat", 41.0191700005564),
    ("286.843.529.999.755", "lon", 28.6843529999755),
    ("4.093.070.253.870", "lat", 40.93070253870),
    ("41.01917", "lat", 41.01917), (41.01917, "lat", 41.01917),
    (" 28.684353 ", "lon", 28.684353),
    ("40.70", "lat", 40.70), ("41.50", "lat", 41.50),
    ("27.80", "lon", 27.80), ("30.20", "lon", 30.20),
])
def test_coordinate_parser_accepts_only_known_valid_formats(value, axis, expected):
    assert parse_gtfs_coordinate(value, axis=axis) == pytest.approx(expected)


@pytest.mark.parametrize("value", [
    None, True, False, "", "NaN", "nan", float("nan"), "Infinity", float("inf"),
    "4,12E+14", "4.10e1", "41,01917", "410191700005564", 410191700005564,
    "41.00506785536913:17 17.03.20268", "direction: GİDİŞ", "41.01.917", "41..01917",
    "51.500.000.000.000", "29.000.000.000.000", "410.191.700.005.564.000.000",
    29.0, -41, {}, [], "41.50001", "40.69999",
])
def test_coordinate_parser_does_not_guess_malformed_or_foreign_values(value):
    assert parse_gtfs_coordinate(value, axis="lat") is None


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    b"stop_id,stop_name,stop_lat,stop_lon\n1,Stop,41.01917,28.684353\n",
    b'\xef\xbb\xbfstop_id;stop_name;stop_lat;stop_lon;\r\n1;"Name; quoted";41.01917;28.684353;\r\n',
    b'stop_id;stop_name;stop_lat;stop_lon;\n1;Extra unnamed value;41.01917;28.684353;0\n',
])
async def test_csv_supports_standard_comma_and_quoted_semicolon_dialects(harness, body):
    harness.body = body
    payload = await harness.client().fetch()
    assert len(payload.rows) == 1
    assert payload.rows[0]["stop_lat"] == "41.01917"


@pytest.mark.asyncio
@pytest.mark.parametrize("body", [
    b"trip_id,stop_id,arrival_time\n1,2,12:00:00\n",
    b"stop_id,stop_name,stop_lat,stop_lat,stop_lon\n1,N,41,41,29\n",
    b"stop_id,stop_name,,stop_lat,stop_lon\n1,N,,41,29\n",
    b"stop_id,stop_name,stop_lat,stop_lon\n1,Too,many,fields,41,29\n",
    b'stop_id,stop_name,stop_lat,stop_lon\n1,"Unclosed,41,29\n',
    b"stop_id,stop_name,stop_lat,stop_lon\n1,\xff,41,29\n",
    GOOD_CSV.replace(b"Stop", b"Stop\x00"),
    GOOD_CSV + b"1,Duplicate,41,29\n",
    b"stop_id,stop_name,stop_lat,stop_lon\n,Unnamed,41,29\n",
    b"stop_id,stop_name,stop_lat,stop_lon\n",
])
async def test_bad_csv_never_replaces_previous_index(harness, body):
    harness.body = body
    service = harness.service()
    seed_old(service)
    with pytest.raises(GtfsStopsError):
        await service._gtfs_stops()
    assert indexed_ids(service) == ["old"]
    assert not source_cache._entries


@pytest.mark.asyncio
async def test_all_invalid_coordinates_are_unavailable_not_empty_success(harness):
    harness.body = b"stop_id,stop_name,stop_lat,stop_lon\n1,Foreign,51.5,-0.1\n"
    service = harness.service()
    seed_old(service)
    result = await service.nearby(**STOP_ARGS)
    assert result["ok"] is False and result["freshness"]["status"] == "broken"
    assert gtfs_source(result)["coverage_status"] == "unavailable"
    assert indexed_ids(service) == ["old"]


@pytest.mark.asyncio
async def test_snapshot_row_cap_rejects_without_partial_index(harness):
    settings = replace(harness.settings, gtfs_stops_max_rows=6)
    service = harness.service(settings)
    seed_old(service)
    with pytest.raises(GtfsStopsError, match="row limit"):
        await service._gtfs_stops()
    assert indexed_ids(service) == ["old"]


@pytest.mark.asyncio
async def test_declared_download_cap_is_checked_before_reading(harness):
    stream = Stream()
    harness.response_factory = lambda: httpx.Response(200, headers={"content-length": "99999999"}, stream=stream)
    with pytest.raises(GtfsStopsError, match="byte limit"):
        await harness.client().fetch()
    assert stream.closed and stream.reads == 0


@pytest.mark.asyncio
async def test_chunked_download_cap_stops_reading_and_closes(harness):
    stream = Stream()
    harness.response_factory = lambda: httpx.Response(200, stream=stream)
    settings = replace(harness.settings, gtfs_stops_max_bytes=65537)
    with pytest.raises(GtfsStopsError, match="byte limit"):
        await harness.client(settings).fetch()
    assert stream.closed and stream.reads == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("headers", [
    {"content-type": "text/html"}, {"content-encoding": "unsupported"},
    {"content-length": "-1"}, {"content-length": "nonsense"},
])
async def test_csv_response_contract_is_fail_closed(harness, headers):
    stream = Stream()
    harness.response_factory = lambda: httpx.Response(200, headers=headers, stream=stream)
    with pytest.raises(GtfsStopsError):
        await harness.client().fetch()
    assert stream.closed and stream.reads == 0


@pytest.mark.asyncio
async def test_csv_does_not_follow_redirect_even_if_http_client_would(harness):
    harness.response_factory = lambda: httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    with pytest.raises(httpx.HTTPStatusError):
        await harness.client().fetch()
    assert len(harness.calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("url", [
    "http://data.ibb.gov.tr/dataset/anything/resource/2299bc82-983b-4bdf-8520-5cef8c555e29/download/stops.csv",
    "https://example.com/stops.csv", "http://127.0.0.1/stops.csv", "file:///tmp/stops.csv",
    "https://data.ibb.gov.tr/stops.csv", "https://data.ibb.gov.tr:8443/stops.csv",
    "https://data.ibb.gov.tr/dataset/x/resource/wrong/download/stops.csv",
    "https://data.ibb.gov.tr/dataset/x/resource/2299bc82-983b-4bdf-8520-5cef8c555e29/download/stops.csv?token=private",
    "https://@data.ibb.gov.tr/dataset/x/resource/2299bc82-983b-4bdf-8520-5cef8c555e29/download/stops.csv",
])
async def test_catalog_cannot_redirect_gtfs_to_untrusted_downloads(harness, url):
    harness.package["resources"][1]["url"] = url
    with pytest.raises(GtfsStopsError):
        await harness.client().fetch()
    assert len(harness.calls) == 1


@pytest.mark.asyncio
async def test_duplicate_stops_resources_fail_instead_of_guessing(harness):
    harness.package["resources"].append(deepcopy(harness.package["resources"][1]))
    with pytest.raises(GtfsStopsError, match="exactly one"):
        await harness.client().fetch()
    assert len(harness.calls) == 1


@pytest.mark.asyncio
async def test_metadata_response_is_also_byte_bounded(harness):
    harness.package["description"] = "x" * (GTFS_METADATA_MAX_BYTES + 1)
    with pytest.raises(CkanError, match="byte limit"):
        await harness.client().fetch()
    assert len(harness.calls) == 1


@pytest.mark.asyncio
async def test_total_deadline_cancels_slow_stream_and_preserves_index(harness):
    stream = Stream(slow=True)
    harness.response_factory = lambda: httpx.Response(200, stream=stream)
    service = harness.service(replace(harness.settings, gtfs_stops_load_timeout_seconds=0.03))
    seed_old(service)
    started = time.monotonic()
    with pytest.raises(TimeoutError):
        await service._gtfs_stops()
    assert time.monotonic() - started < 1
    assert stream.closed and indexed_ids(service) == ["old"]


@pytest.mark.asyncio
async def test_explicit_cancellation_closes_stream_without_publishing_partial_snapshot(harness):
    stream = Stream(block=True)
    harness.response_factory = lambda: httpx.Response(200, stream=stream)
    service = harness.service()
    seed_old(service)
    task = asyncio.create_task(service._gtfs_stops())
    await asyncio.wait_for(stream.started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert stream.closed and indexed_ids(service) == ["old"]
    assert not source_cache._entries


@pytest.mark.asyncio
async def test_concurrent_requests_share_one_successful_csv_capture(harness):
    service = harness.service()
    results = await asyncio.gather(*(service.nearby(**STOP_ARGS) for _ in range(8)))
    assert all(result["ok"] and len(result["data"]) == 3 for result in results)
    assert len(harness.calls) == 2
    assert len(indexed_ids(service)) == 3


@pytest.mark.asyncio
async def test_sqlite_insert_failure_rolls_back_both_data_and_rtree(harness, monkeypatch):
    service = harness.service()
    seed_old(service)
    original = service.geo._insert_feature
    count = 0

    def fail_second(conn, feature):
        nonlocal count
        count += 1
        if count == 2:
            raise RuntimeError("fixture insert failed")
        original(conn, feature)

    monkeypatch.setattr(service.geo, "_insert_feature", fail_second)
    with pytest.raises(RuntimeError, match="fixture insert"):
        await service._gtfs_stops()
    assert indexed_ids(service) == ["old"]
    assert not source_cache._entries


@pytest.mark.asyncio
async def test_failed_refresh_serves_bounded_stale_with_original_provenance(harness):
    service = harness.service()
    fresh = await service.nearby(**STOP_ARGS)
    entry = expire_gtfs()
    old_expiry = entry.expires_at_monotonic
    old_hard_deadline = entry.max_age_at_monotonic
    harness.offline = True
    stale = await service.nearby(**STOP_ARGS)
    assert stale["ok"] and stale["freshness"]["status"] == "stale"
    assert stale["data"] == fresh["data"]
    assert stale["freshness"]["retrieved_at"] == fresh["freshness"]["retrieved_at"]
    assert gtfs_source(stale)["coverage_status"] == "unavailable"
    assert gtfs_source(stale)["last_successful_refresh_at"] == gtfs_source(fresh)["last_successful_refresh_at"]
    assert entry.expires_at_monotonic == old_expiry and entry.max_age_at_monotonic == old_hard_deadline
    assert any("last successful" in warning for warning in stale["warnings"])
    bbox = await service.bbox_search(bbox=[28.68, 41.0, 28.70, 41.03], types=["public_transport_stop"])
    assert bbox["ok"] and bbox["freshness"]["status"] == "stale"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", ["expired", "no_stale", "process_restart"])
async def test_unverified_or_too_old_index_never_leaks_into_success(harness, mode):
    settings = replace(harness.settings, gtfs_stops_stale_if_error_seconds=0) if mode == "no_stale" else harness.settings
    service = harness.service(settings)
    assert (await service.nearby(**STOP_ARGS))["ok"]
    if mode == "process_restart":
        clear_source_cache()
    else:
        expire_gtfs(beyond_stale=mode == "expired")
    harness.offline = True
    nearby = await service.nearby(**STOP_ARGS)
    bbox = await service.bbox_search(bbox=[28.68, 41.0, 28.70, 41.03], types=["public_transport_stop"])
    for result in (nearby, bbox):
        assert result["ok"] is False and result["freshness"]["status"] == "broken"
        assert not any(row.get("source") == "gtfs" for row in result["data"])
        assert gtfs_source(result)["coverage_status"] == "unavailable"
    assert len(indexed_ids(service)) == 3  # Retained transactionally, not exposed.


@pytest.mark.asyncio
async def test_cache_success_does_not_apply_to_a_different_app_database(harness, tmp_path):
    assert (await harness.service().nearby(**STOP_ARGS))["ok"]
    other = harness.service(replace(harness.settings, database_path=tmp_path / "other.sqlite3"))
    result = await other.nearby(**STOP_ARGS)
    assert result["ok"] and len(result["data"]) == 3
    assert len(harness.calls) == 4


@pytest.mark.asyncio
async def test_stricter_limit_profile_cannot_reuse_a_looser_success_cache(harness):
    assert (await harness.service().nearby(**STOP_ARGS))["ok"]
    result = await harness.service(replace(harness.settings, gtfs_stops_max_rows=2)).nearby(**STOP_ARGS)
    assert result["ok"] is False
    assert len(harness.calls) == 4


@pytest.mark.asyncio
async def test_partial_city_search_does_not_become_fresh_when_only_gtfs_succeeds(harness, monkeypatch):
    service = harness.service()
    monkeypatch.setattr(service, "_parks", AsyncMock(side_effect=RuntimeError("offline")))
    result = await service.nearby(**{**STOP_ARGS, "types": ["parking", "public_transport_stop"]})
    assert result["ok"] and len(result["data"]) == 3
    assert result["freshness"]["status"] == "unknown"
    assert any("Parking source refresh failed" in warning for warning in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["legacy", "2026-07-28"])
async def test_real_mcp_registry_preserves_gtfs_success_and_source_failure(harness, monkeypatch, protocol):
    service = harness.service()
    monkeypatch.setattr(handlers, "CityService", lambda **_kwargs: service)
    async with Client(create_mcp_server(harness.settings), mode=protocol) as client:
        result = await client.call_tool("istanbul_nearby", STOP_ARGS)
        assert not result.is_error and result.structured_content["ok"]
        assert len(result.structured_content["data"]) == 3
        assert json.loads(result.content[0].text) == result.structured_content
        expire_gtfs(beyond_stale=True)
        harness.offline = True
        failure = await client.call_tool("istanbul_nearby", STOP_ARGS)
        assert not failure.is_error
        assert failure.structured_content["ok"] is False
        assert failure.structured_content["freshness"]["status"] == "broken"
        assert gtfs_source(failure.structured_content)["coverage_status"] == "unavailable"


@pytest.mark.parametrize("field,value", [
    ("gtfs_stops_max_rows", 0), ("gtfs_stops_max_rows", 100001),
    ("gtfs_stops_max_bytes", 0), ("gtfs_stops_max_bytes", 20971521),
    ("gtfs_stops_load_timeout_seconds", 0), ("gtfs_stops_load_timeout_seconds", 61),
    ("gtfs_stops_load_timeout_seconds", float("inf")), ("gtfs_stops_load_timeout_seconds", float("nan")),
    ("gtfs_stops_cache_ttl_seconds", 0), ("gtfs_stops_cache_ttl_seconds", 86401),
    ("gtfs_stops_stale_if_error_seconds", -1), ("gtfs_stops_stale_if_error_seconds", 604801),
])
def test_invalid_gtfs_configuration_is_rejected(field, value):
    with pytest.raises(ValueError, match=field.upper()):
        validate_gtfs_settings(replace(Settings(), **{field: value}))


def test_gtfs_env_settings_are_loaded(monkeypatch):
    for name, value in {"GTFS_STOPS_MAX_ROWS": "1000", "GTFS_STOPS_MAX_BYTES": "2000",
                        "GTFS_STOPS_LOAD_TIMEOUT_SECONDS": "2.5", "GTFS_STOPS_CACHE_TTL_SECONDS": "20",
                        "GTFS_STOPS_STALE_IF_ERROR_SECONDS": "40"}.items():
        monkeypatch.setenv(name, value)
    settings = get_settings()
    assert settings.gtfs_stops_max_rows == 1000 and settings.gtfs_stops_max_bytes == 2000
    assert settings.gtfs_stops_load_timeout_seconds == 2.5
    assert settings.gtfs_stops_cache_ttl_seconds == 20 and settings.gtfs_stops_stale_if_error_seconds == 40


def test_app_rejects_invalid_gtfs_limits_before_serving(monkeypatch):
    from app.main import create_app
    monkeypatch.setenv("GTFS_STOPS_MAX_ROWS", "0")
    get_settings.cache_clear()
    with pytest.raises(ValueError, match="GTFS_STOPS_MAX_ROWS"):
        create_app()


def datastore_fixture(harness, *, count=101):
    resource = deepcopy(harness.package["resources"][1])
    resource["url"] = ""
    resource["datastore_active"] = True
    harness.package["resources"] = [resource]
    rows = [{"stop_id": str(i), "stop_name": f"Stop {i}", "stop_lat": 41.01917, "stop_lon": 28.684353}
            for i in range(count)]
    fields = [{"id": name} for name in ("stop_id", "stop_name", "stop_lat", "stop_lon")]

    def page(payload):
        return {"fields": fields, "total": count, "records": rows[payload["offset"]:payload["offset"] + 100]}

    harness.datastore_factory = page
    return page


@pytest.mark.asyncio
async def test_compatible_datastore_capture_is_complete_sorted_and_bounded(harness):
    datastore_fixture(harness)
    cached = await harness.service()._gtfs_stops()
    assert len(cached.value) == 101 and cached.metadata["accepted_total"] == 101
    assert cached.metadata["scope"] == "all_active_datastore_records"
    assert [json.loads(request.content).get("offset") for request in harness.calls] == [None, 0, 100]
    assert not any(request.method == "GET" for request in harness.calls)


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["wrong_schema", "huge_total", "invalid_total", "total_changed", "incomplete", "excess", "empty"])
async def test_bad_datastore_capture_never_replaces_index(harness, fault):
    original = datastore_fixture(harness)

    def broken(payload):
        page = original(payload)
        if fault == "wrong_schema":
            page["fields"] = [{"id": "trip_id"}, {"id": "stop_id"}]
        elif fault == "huge_total":
            page["total"] = 1048575
        elif fault == "invalid_total":
            page["total"] = True
        elif fault == "total_changed" and payload["offset"]:
            page["total"] = 102
        elif fault == "incomplete" and payload["offset"]:
            page["records"] = []
        elif fault == "excess":
            page["records"] = page["records"] * 2
        elif fault == "empty":
            page.update(total=0, records=[])
        return page

    harness.datastore_factory = broken
    service = harness.service()
    seed_old(service)
    with pytest.raises(GtfsStopsError):
        await service._gtfs_stops()
    assert indexed_ids(service) == ["old"]
    assert len(harness.calls) <= 3


@pytest.mark.asyncio
async def test_datastore_bytes_are_aggregate_not_a_per_page_allowance(harness):
    page = datastore_fixture(harness)
    sizes = [len(httpx.Response(200, json={"success": True, "result": page({"offset": offset})}).content)
             for offset in (0, 100)]
    cap = sum(sizes) - 1
    assert cap > max(sizes)
    settings = replace(harness.settings, gtfs_stops_max_bytes=cap)
    service = harness.service(settings)
    seed_old(service)
    with pytest.raises(CkanError, match="byte limit"):
        await service._gtfs_stops()
    assert len(harness.calls) == 3 and indexed_ids(service) == ["old"]


@pytest.mark.asyncio
async def test_total_deadline_also_covers_metadata_phase(harness, monkeypatch):
    async def slow_metadata(*_args, **_kwargs):
        await asyncio.sleep(10)
    monkeypatch.setattr(harness.ckan, "package_show_bounded", slow_metadata)
    settings = replace(harness.settings, gtfs_stops_load_timeout_seconds=0.02)
    with pytest.raises(TimeoutError):
        await harness.client(settings).fetch()
    assert not harness.calls


@pytest.mark.asyncio
async def test_late_synchronous_parse_is_rejected_before_indexing(harness, monkeypatch):
    client = harness.client(replace(harness.settings, gtfs_stops_load_timeout_seconds=0.02))
    original = client._parse_csv

    def slow_parse(body):
        time.sleep(0.04)
        return original(body)

    monkeypatch.setattr(client, "_parse_csv", slow_parse)
    with pytest.raises(TimeoutError, match="load deadline"):
        await client.fetch()


@pytest.mark.asyncio
async def test_cancelled_cache_waiter_does_not_cancel_the_active_loader(harness):
    class GatedCsv(Stream):
        async def __aiter__(self):
            self.started.set()
            await self.release.wait()
            yield GOOD_CSV

    stream = GatedCsv(block=True)
    harness.response_factory = lambda: httpx.Response(200, stream=stream)
    service = harness.service()
    owner = asyncio.create_task(service.nearby(**STOP_ARGS))
    await asyncio.wait_for(stream.started.wait(), timeout=1)
    waiter = asyncio.create_task(service.nearby(**STOP_ARGS))
    await asyncio.sleep(0)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    assert not stream.closed
    stream.release.set()
    result = await asyncio.wait_for(owner, timeout=1)
    assert result["ok"] and len(result["data"]) == 1
    assert stream.closed and len(harness.calls) == 2


@pytest.mark.asyncio
async def test_mobility_propagates_static_stale_and_unavailable_stop_coverage(harness, monkeypatch):
    service = harness.service()
    component = {"ok": True, "data": [], "freshness": {"status": "fresh"}, "warnings": []}
    for method in ("parking_nearby", "metro_stations_nearby", "traffic_status"):
        monkeypatch.setattr(service, method, AsyncMock(return_value=deepcopy(component)))
    monkeypatch.setattr(service, "_air_quality_stations_nearby_summary", AsyncMock(return_value=[]))
    args = {**ORIGIN, "radius_m": 2000, "limit": 10}
    fresh = await service.mobility_nearby(**args)
    assert len(fresh["data"][0]["public_transport_stops"]) == 3
    assert fresh["freshness"]["status"] == "fresh"
    expire_gtfs()
    harness.offline = True
    stale = await service.mobility_nearby(**args)
    assert stale["ok"] and stale["freshness"]["status"] == "stale"
    assert len(stale["data"][0]["public_transport_stops"]) == 3
    assert gtfs_source(stale)["coverage_status"] == "unavailable"
    expire_gtfs(beyond_stale=True)
    unavailable = await service.mobility_nearby(**args)
    assert unavailable["ok"] and unavailable["freshness"]["status"] == "unknown"
    assert unavailable["data"][0]["public_transport_stops"] == []
    assert gtfs_source(unavailable)["coverage_status"] == "unavailable"
    assert any("GTFS stops unavailable" in warning for warning in unavailable["warnings"])


@pytest.mark.asyncio
async def test_default_city_layers_do_not_leak_unrequested_persisted_stops(harness, monkeypatch):
    service = harness.service()
    seed_old(service)
    for method in ("_parks", "_metro_stations", "_air_quality_stations"):
        monkeypatch.setattr(service, method, AsyncMock(return_value=[]))
    result = await service.nearby(**ORIGIN)
    assert result["ok"] and result["data"] == []
    assert indexed_ids(service) == ["old"] and not harness.calls


@pytest.mark.asyncio
async def test_catalog_size_is_used_to_reject_a_well_formed_partial_csv(harness):
    harness.package["resources"][1]["size"] = len(harness.body)
    harness.body = GOOD_CSV
    service = harness.service()
    seed_old(service)
    with pytest.raises(GtfsStopsError, match="size does not match catalog"):
        await service._gtfs_stops()
    assert indexed_ids(service) == ["old"]


@pytest.mark.asyncio
async def test_oversized_catalog_file_is_rejected_before_its_download(harness):
    harness.package["resources"][1]["size"] = harness.settings.gtfs_stops_max_bytes + 1
    with pytest.raises(GtfsStopsError, match="byte limit"):
        await harness.client().fetch()
    assert len(harness.calls) == 1


@pytest.mark.asyncio
async def test_exact_catalog_and_configured_size_limits_succeed(harness):
    harness.package["resources"][1]["size"] = len(harness.body)
    settings = replace(harness.settings, gtfs_stops_max_bytes=len(harness.body), gtfs_stops_max_rows=7)
    payload = await harness.client(settings).fetch()
    assert len(payload.rows) == 7 and payload.received_bytes == len(harness.body)
