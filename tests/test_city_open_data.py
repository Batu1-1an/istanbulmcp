"""Static EV/taxi/market/cultural layers and weekly market schedule."""
from dataclasses import replace
import io
import json
from pathlib import Path
import zipfile

import httpx
import pytest

from app.connectors.city_open_data import (
    CULTURAL_URL, EV_URL, MARKET_RESOURCE_ID, TAXI_URL, CityOpenDataClient,
    OpenDataLayer, OpenDataLayerError, _canonical_url, parse_market_coordinate,
    validate_open_data_settings,
)
from app.connectors.xlsx import read_first_sheet_rows
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.city import CityService
from app.services.markets import MarketService, normalize_day
from app.storage.geo import GeoRepository

FIXTURES = Path(__file__).parent / "fixtures" / "city_layers"


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


def xlsx_bytes(rows: list[list[str]]) -> bytes:
    strings = "".join(
        f'<row r="{row_number}">' + "".join(
            f'<c r="{chr(65 + column)}{row_number}" t="inlineStr"><is><t>{value}</t></is></c>'
            for column, value in enumerate(row)
        ) + "</row>"
        for row_number, row in enumerate(rows, 1)
    )
    sheet = f'<?xml version="1.0" encoding="UTF-8"?><worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>{strings}</sheetData></worksheet>'
    workbook = '<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets><sheet name="Sheet1" sheetId="1" r:id="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></sheets></workbook>'
    rels = '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>'
    content_types = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/></Types>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
    return buffer.getvalue()


class FakeRate:
    async def acquire(self, _name):
        return None


class FakeCkan:
    def __init__(self, pages=None, wifi=None, libraries=None):
        self.pages = pages or {}
        self.wifi = wifi or []
        self.libraries = libraries or []

    async def datastore_search_bounded(self, *, resource_id, limit, offset, max_bytes):
        page = self.pages[resource_id][offset:offset + limit]
        result = {"records": page, "total": len(self.pages[resource_id]), "fields": [
            {"id": field} for field in ("Ilce", "Pazar Adi", "Koordinat", "Gun", "Mahalle", "Cadde", "Sokak", "Pazar Tipi")
        ]}
        return result, len(json.dumps(result).encode())

    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        records = self.wifi if resource_id.endswith("5d0a0b1e-9e56-4038-b966-7d3e7b46f882") else self.libraries
        return {"records": records[offset:offset + limit], "total": len(records)}


class FakeOpenData:
    def __init__(self, layers=None, market=None):
        self.layers = layers or {}
        self.market_payload = market

    async def layer(self, kind):
        return self.layers[kind]

    async def market(self):
        return self.market_payload


def settings(tmp_path):
    return Settings(database_path=tmp_path / "city.sqlite3")


def payload(kind, rows, *, url, dataset_id=None, resource_id=None):
    return OpenDataLayer(
        kind=kind, rows=rows, dataset_id=dataset_id, resource_id=resource_id,
        source_url=url, reported_total=len(rows), received_bytes=100, received_total=len(rows),
    )


def geo_service(tmp_path, open_data, ckan=None):
    clear_source_cache()
    settings_ = settings(tmp_path)
    return CityService(
        settings=settings_,
        geo_repository=GeoRepository(settings_.database_path),
        open_data_client=open_data,
        ckan_client=ckan or FakeCkan(),
    )


@pytest.mark.parametrize("field,value", [
    ("open_data_layers_max_bytes", 0),
    ("open_data_layers_max_rows", 10001),
    ("open_data_layers_request_timeout_seconds", 0),
    ("open_data_layers_cache_ttl_seconds", -1),
])
def test_open_data_settings_have_hard_bounds(field, value):
    with pytest.raises(ValueError):
        validate_open_data_settings(replace(Settings(), **{field: value}))


def test_xlsx_reader_handles_inline_strings_and_rejects_empty():
    rows = read_first_sheet_rows(xlsx_bytes([["Ad", "Adres"], ["Kültür", "Kadıköy"]]))
    assert rows == [["Ad", "Adres"], ["Kültür", "Kadıköy"]]
    with pytest.raises(ValueError, match="no rows"):
        read_first_sheet_rows(xlsx_bytes([]))


@pytest.mark.asyncio
async def test_geojson_client_validates_canonical_url_and_feature_count(tmp_path):
    ev = (FIXTURES / "ev_charging.geojson").read_bytes()

    def handler(request):
        assert str(request.url) == EV_URL
        return httpx.Response(200, content=ev, headers={"content-type": "application/geo+json"})

    client = CityOpenDataClient(settings(tmp_path), ckan_client=FakeCkan(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), rate_limiter=FakeRate())
    async with client._client:
        layer = await client.layer("ev_charging")
    assert layer.received_total == 3 and layer.reported_total == 3


def test_static_url_rejects_foreign_host_query_and_wrong_filename():
    for url in (
        "https://example.org/dataset/d/resource/r/download/sarj_istasyonlari.geojson",
        EV_URL + "?token=hidden",
        EV_URL.replace("sarj_istasyonlari.geojson", "stop_times.csv"),
    ):
        with pytest.raises(OpenDataLayerError):
            _canonical_url(url, "r", "sarj_istasyonlari.geojson", "d")


@pytest.mark.asyncio
async def test_xlsx_client_parses_canonical_cultural_layer(tmp_path):
    body = xlsx_bytes([["Kültür Merkezi", "Adres", "İlçe"], ["Kadıköy Kültür", "Kadıköy", "Kadıköy"]])

    def handler(request):
        assert str(request.url) == CULTURAL_URL
        return httpx.Response(200, content=body, headers={"content-type": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"})

    client = CityOpenDataClient(settings(tmp_path), ckan_client=FakeCkan(), http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)), rate_limiter=FakeRate())
    async with client._client:
        layer = await client.layer("cultural_centre")
    assert layer.received_total == 1 and layer.rows[0]["Kültür Merkezi"] == "Kadıköy Kültür"


@pytest.mark.asyncio
async def test_geojson_client_rejects_redirect_compression_and_html(tmp_path):
    for response in (
        httpx.Response(302, headers={"location": "https://example.org/"}),
        httpx.Response(200, headers={"content-encoding": "gzip"}, content=b"x"),
        httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html>"),
    ):
        client = CityOpenDataClient(
            settings(tmp_path), ckan_client=FakeCkan(),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda _: response)),
            rate_limiter=FakeRate(),
        )
        async with client._client:
            with pytest.raises(OpenDataLayerError):
                await client.layer("taxi_stand")


@pytest.mark.asyncio
async def test_market_client_paginates_complete_datastore_and_rejects_changed_total(tmp_path):
    rows = [{"_id": index, "Ilce": "Kadıköy", "Pazar Adi": f"P{index}", "Koordinat": "40.99,29.03", "Gun": "Cumartesi"} for index in range(3)]
    ckan = FakeCkan(pages={MARKET_RESOURCE_ID: rows})
    client = CityOpenDataClient(settings(tmp_path), ckan_client=ckan, rate_limiter=FakeRate())
    layer = await client.market()
    assert layer.received_total == 3 and layer.reported_total == 3

    class ChangingTotal(FakeCkan):
        async def datastore_search_bounded(self, *, resource_id, limit, offset, max_bytes):
            result, size = await super().datastore_search_bounded(resource_id=resource_id, limit=limit, offset=offset, max_bytes=max_bytes)
            if offset:
                result["total"] += 1
            return result, size

    many = rows * 34  # 102 rows, more than one 100-row page.
    with pytest.raises(OpenDataLayerError, match="changed"):
        await CityOpenDataClient(settings(tmp_path), ckan_client=ChangingTotal(pages={MARKET_RESOURCE_ID: many}), rate_limiter=FakeRate()).market()


@pytest.mark.asyncio
async def test_nearby_ev_taxi_and_market_map_valid_points_and_skip_invalid(tmp_path):
    ev = json.loads((FIXTURES / "ev_charging.geojson").read_text())["features"]
    taxi = json.loads((FIXTURES / "taxi_stand.geojson").read_text())["features"]
    market = [
        {"_id": 1, "Ilce": "Kadıköy", "Pazar Adi": "Pazar A", "Koordinat": "40.9910,29.0305", "Mahalle": "Caferağa", "Gun": "Cumartesi", "Pazar Tipi": "Alan"},
        {"_id": 2, "Ilce": "Kadıköy", "Pazar Adi": "Pazar B", "Koordinat": "not-a-point", "Gun": "Pazar"},
    ]
    service = geo_service(tmp_path, FakeOpenData({
        "ev_charging": payload("ev_charging", ev, url=EV_URL),
        "taxi_stand": payload("taxi_stand", taxi, url=TAXI_URL),
    }, market=payload("market", market, url="https://data.ibb.gov.tr")))
    result = await service.nearby(lat=40.991, lon=29.0305, types=["ev_charging", "taxi_stand", "market"], radius_m=1000, limit=10)
    assert result["ok"] is True
    assert {row["feature_type"] for row in result["data"]} == {"ev_charging", "taxi_stand", "market"}
    assert all(row["maps_url"] for row in result["data"])
    assert any(row["properties"].get("operator") == "Test Operatör" for row in result["data"] if row["feature_type"] == "ev_charging")
    assert any(row["properties"].get("day") == "Cumartesi" for row in result["data"] if row["feature_type"] == "market")
    assert all(row["name"] != "Paris outside" for row in result["data"])
    assert any(source["accepted_total"] == 2 for source in result["sources"] if source.get("resource_id") is None)


@pytest.mark.asyncio
async def test_market_schedule_normalizes_turkish_english_and_district(tmp_path):
    rows = [
        {"_id": 1, "Ilce": "Kadıköy", "Pazar Adi": "Cumartesi Pazarı", "Koordinat": "40.9910,29.0305", "Mahalle": "Caferağa", "Cadde": "A", "Sokak": "B", "Gun": "Cumartesi", "Pazar Tipi": "Alan"},
        {"_id": 2, "Ilce": "Beşiktaş", "Pazar Adi": "Pazar Günü", "Koordinat": "41.04,29.00", "Mahalle": "Levent", "Gun": "Pazar", "Pazar Tipi": "Kapalı"},
    ]
    service = MarketService(settings(tmp_path), client=FakeOpenData(market=payload("market", rows, url="https://data.ibb.gov.tr")))
    result = await service.schedule(district="Kadıköy", day="saturday")
    assert result["ok"] is True and [row["market_name"] for row in result["data"]] == ["Cumartesi Pazarı"]
    assert result["data"][0]["maps_url"].startswith("https://www.google.com/maps/search/")
    assert result["data"][0]["day"] == "Cumartesi"
    assert any("static" in warning.lower() or "weekly" in warning.lower() for warning in result["warnings"])
    assert (await service.schedule(day="2026-10-24"))["data"][0]["market_name"] == "Cumartesi Pazarı"
    assert (await service.schedule(day="Pazar"))["data"][0]["market_name"] == "Pazar Günü"
    assert normalize_day("yarın", today=__import__("datetime").date(2026, 10, 23))[0] == "Cumartesi"


@pytest.mark.asyncio
async def test_market_schedule_rejects_bad_day_and_zero_limit(tmp_path):
    service = MarketService(settings(tmp_path), client=FakeOpenData(market=payload("market", [], url="https://data.ibb.gov.tr")))
    assert (await service.schedule(day="not-a-day"))["data"][0]["field"] == "day"
    assert (await service.schedule(limit=0))["data"][0]["field"] == "limit"


@pytest.mark.asyncio
async def test_cultural_centres_are_address_search_not_radius_points(tmp_path):
    rows = [
        {"Kültür Merkezi": "Kadıköy Kültür", "Adres": "Kadıköy test", "İlçe": "Kadıköy", "Açılış-Kapanış Saatleri": "09:00-18:00", "Çocuk Birimi": "Var"},
        {"Kültür Merkezi": "Beşiktaş Kültür", "Adres": "Beşiktaş test", "İlçe": "Beşiktaş"},
    ]
    service = geo_service(tmp_path, FakeOpenData({"cultural_centre": payload("cultural_centre", rows, url=CULTURAL_URL, dataset_id="d", resource_id="r")}), FakeCkan(
        wifi=[{"location": "Kadıköy WiFi", "latitude": 40.991, "longitude": 29.0305, "location_code": "w1"}],
        libraries=[{"Kutuphane Adi": "Kadıköy Kütüphane", "Ilce Adi": "Kadıköy", "Adres": "Kadıköy"}],
    ))
    result = await service.city_services_nearby(place="Kadıköy", radius_m=600, limit=5)
    assert result["ok"] is True
    cultural = result["data"][0]["cultural_centres"]
    assert [row["name"] for row in cultural] == ["Kadıköy Kültür"]
    assert cultural[0]["location_precision"] == "address_search"
    assert cultural[0]["maps_search_url"].startswith("https://www.google.com/maps/search/")
    assert "maps_url" not in cultural[0]
    assert any("address-search" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_static_layer_failure_does_not_remove_previous_geo_rows(tmp_path):
    service = geo_service(tmp_path, FakeOpenData({
        "ev_charging": payload("ev_charging", json.loads((FIXTURES / "ev_charging.geojson").read_text())["features"], url=EV_URL),
    }))
    assert (await service.nearby(lat=40.991, lon=29.0305, types=["ev_charging"]))["ok"] is True
    service.open_data.layers["ev_charging"] = OpenDataLayer("ev_charging", [], None, None, EV_URL, 0, 0, 0)
    clear_source_cache()
    result = await service.nearby(lat=40.991, lon=29.0305, types=["ev_charging"])
    assert result["ok"] is False
    assert service.geo.nearby(lat=40.991, lon=29.0305, radius_m=1000, limit=10, types=["ev_charging"])
