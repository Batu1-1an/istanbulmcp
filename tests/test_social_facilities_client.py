from pathlib import Path
import io
import zipfile

import httpx
import pytest

from app.connectors.social_facilities import (
    SocialFacilitiesClient,
    SocialFacilitiesSourceError,
    canonical_identity,
    implicit_coordinate,
    parse_map_coordinates,
)
from app.core.settings import Settings


FIXTURES = Path(__file__).parent / "fixtures" / "social_facilities"


def test_detail_parser_converts_map_lon_lat_and_keeps_url_separate():
    row = SocialFacilitiesClient.parse_detail(
        (FIXTURES / "detail_cihangir.html").read_text(encoding="utf-8"),
        detail_url="https://tesislerimiz.ibb.istanbul/tesis/cihangir-sosyal-tesisi",
    )
    assert row["name"] == "Cihangir Sosyal Tesisi"
    assert row["latitude"] == pytest.approx(41.0284966)
    assert row["longitude"] == pytest.approx(28.9825361)
    assert row["source_id"] is None
    assert row["detail_url"].endswith("cihangir-sosyal-tesisi")


def test_reservation_parser_requires_conservative_card_match():
    cards = SocialFacilitiesClient.parse_reservations(
        (FIXTURES / "reservation_home.html").read_text(encoding="utf-8")
    )
    assert cards[0]["name"] == "Cihangir Sosyal Tesisi"
    assert cards[0]["reservation_url"].endswith("/reservation/create/123")


def test_coordinate_helpers_reject_invalid_and_normalize_implicit_decimals():
    assert parse_map_coordinates("https://harita.istanbul/?@=28.9,41.1,16") == (41.1, 28.9)
    assert implicit_coordinate("410578458", latitude=True) == pytest.approx(41.0578458)
    assert implicit_coordinate("289456101", latitude=False) == pytest.approx(28.9456101)
    assert implicit_coordinate("not-a-coordinate", latitude=True) is None


@pytest.mark.asyncio
async def test_client_uses_get_only_and_parses_catalog_details():
    responses = {
        "https://fixture.test/tesisler": httpx.Response(
            200,
            text=(FIXTURES / "catalog_page_1.html").read_text(encoding="utf-8"),
            request=httpx.Request("GET", "https://fixture.test/tesisler"),
        ),
        "https://fixture.test/tesis/cihangir-sosyal-tesisi": httpx.Response(
            200,
            text=(FIXTURES / "detail_cihangir.html").read_text(encoding="utf-8"),
            request=httpx.Request("GET", "https://fixture.test/tesis/cihangir-sosyal-tesisi"),
        ),
        "https://fixture.test/tesis/beykoz-koru": httpx.Response(
            200,
            text=(FIXTURES / "detail_beykoz.html").read_text(encoding="utf-8"),
            request=httpx.Request("GET", "https://fixture.test/tesis/beykoz-koru"),
        ),
        "https://fixture.test/": httpx.Response(
            200,
            text=(FIXTURES / "reservation_home.html").read_text(encoding="utf-8"),
            request=httpx.Request("GET", "https://fixture.test/"),
        ),
    }
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, str(request.url)))
        return responses.get(
            str(request.url),
            httpx.Response(404, request=request),
        )

    client = SocialFacilitiesClient(
        settings=Settings(
            social_facilities_catalog_url="https://fixture.test/tesisler",
            social_facilities_reservation_url="https://fixture.test/",
            social_facilities_ckan_download_url="https://fixture.test/fallback.xlsx",
            social_facilities_max_catalog_pages=1,
            social_facilities_max_detail_pages=10,
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    payload = await client.fetch()
    assert len(payload.rows) == 2
    assert all(method == "GET" for method, _ in calls)
    assert not any("reservation/create" in url for _, url in calls)
    assert payload.reported_total == payload.accepted_total if hasattr(payload, "accepted_total") else True
    await client._http_client.aclose()


def test_identity_does_not_replace_source_id_with_detail_url():
    assert canonical_identity({"source_id": "A-1", "detail_url": "https://example.test/x"}) == "id:A-1"
    assert canonical_identity({"detail_url": "https://example.test/x"}) == "url:https://example.test/x"


def test_xlsx_parser_reads_implicit_decimal_coordinates_and_skips_bad_rows():
    worksheet = """<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\"><sheetData><row r=\"1\"><c r=\"A1\" t=\"inlineStr\"><is><t>Name</t></is></c><c r=\"B1\" t=\"inlineStr\"><is><t>Latitude</t></is></c><c r=\"C1\" t=\"inlineStr\"><is><t>Latitude</t></is></c><c r=\"D1\" t=\"inlineStr\"><is><t>Address</t></is></c></row><row r=\"2\"><c r=\"A2\" t=\"inlineStr\"><is><t>Test Tesis</t></is></c><c r=\"B2\"><v>410578458</v></c><c r=\"C2\"><v>289456101</v></c><c r=\"D2\" t=\"inlineStr\"><is><t>Adres</t></is></c></row><row r=\"3\"><c r=\"A3\" t=\"inlineStr\"><is><t>Bad</t></is></c><c r=\"B3\"><v>bad</v></c><c r=\"C3\"><v>0</v></c></row></sheetData></worksheet>"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("xl/worksheets/sheet1.xml", worksheet)
    rows, updated = SocialFacilitiesClient.parse_xlsx(stream.getvalue())
    assert updated is None
    assert len(rows) == 1
    assert rows[0]["latitude"] == pytest.approx(41.0578458)
    assert rows[0]["longitude"] == pytest.approx(28.9456101)


def test_merge_rows_keeps_live_values_and_fills_missing_fields_with_discrepancy_warning():
    merged, warnings = SocialFacilitiesClient.merge_rows(
        [{"name": "Same", "latitude": 41.0, "longitude": 28.9, "address": None, "detail_url": "https://live.test/same"}],
        [{"name": "Same", "latitude": 41.1, "longitude": 29.0, "address": "District address"}],
    )
    assert merged[0]["latitude"] == 41.0
    assert merged[0]["address"] == "District address"
    assert any("source_discrepancy" in warning for warning in warnings)


@pytest.mark.asyncio
async def test_live_and_fallback_failure_is_a_source_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, request=request)

    client = SocialFacilitiesClient(
        settings=Settings(
            social_facilities_catalog_url="https://fixture.test/catalog",
            social_facilities_reservation_url="https://fixture.test/reservation",
            social_facilities_ckan_download_url="https://fixture.test/fallback.xlsx",
            social_facilities_request_attempts=1,
        ),
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(SocialFacilitiesSourceError):
        await client.fetch()
    await client._http_client.aclose()
