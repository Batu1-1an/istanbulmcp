from pathlib import Path

import httpx
import pytest

from app.connectors.metro import MetroClient, MetroPayloadError


FIXTURES = Path(__file__).parent / "fixtures"


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


def fixture_text(path: str) -> str:
    return (FIXTURES / path).read_text(encoding="utf-8")


def json_client(body: str, *, url: str, status_code: int = 200):
    async def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == url
        assert request.method == "GET"
        return httpx.Response(status_code, text=body, request=request)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# --- Summary source (GetFaultyEquipments JSON) ---


@pytest.mark.asyncio
async def test_metro_equipment_summary_maps_categories_and_preserves_source_order():
    limiter = RecordingLimiter()
    async with json_client(
        fixture_text("metro/equipment_summary_success.json"),
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=limiter,
        )
        rows = await client.equipment_summary()

    # Rows follow the source order from the JSON payload; the live-shaped fixture is
    # a single-element Data list with Active/Inactive/IsShow fields.
    assert rows[0]["category_key"] == "line"
    assert rows[0]["category_name"] == "Hatlar"
    assert rows[0]["active_count"] == 18
    assert rows[0]["inactive_count"] == 1
    assert rows[0]["is_visible"] is True
    # Fixture: EquipmentServiceStatus (Hatlar, Yürüyen Merdiven) then
    # StationServiceStatus (İstasyonlar, Giriş / Çıkış).
    assert rows[1]["category_key"] == "escalator"
    assert rows[1]["active_count"] == 1963
    assert rows[2]["category_key"] == "station"
    assert rows[2]["category_name"] == "İstasyonlar"
    assert rows[3]["category_key"] == "entrance_exit"
    assert limiter.acquired == ["metro"]


@pytest.mark.asyncio
async def test_metro_equipment_summary_accepts_checked_empty():
    async with json_client(
        fixture_text("metro/equipment_summary_empty.json"),
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        rows = await MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_summary()

    assert rows == []


@pytest.mark.asyncio
async def test_metro_equipment_summary_preserves_unknown_category():
    async with json_client(
        fixture_text("metro/equipment_summary_unknown_category.json"),
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        rows = await MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_summary()

    unknown = [row for row in rows if row["category_name"] == "Gece Işıklandırma"]
    assert len(unknown) == 1
    assert unknown[0]["category_key"] == "equipment:gece isiklandirma"


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_malformed_payload():
    async with json_client(
        fixture_text("metro/equipment_summary_malformed.json"),
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="list"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_missing_success_marker():
    body = '{"Data": {"EquipmentServiceStatus": []}}'
    async with json_client(
        body,
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="Success"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_negative_count():
    body = (
        '{"Success": true, "Data": {"EquipmentServiceStatus": ['
        '{"Name": "Asansörler", "ActiveCount": 10, "InactiveCount": -5}]}}'
    )
    async with json_client(
        body,
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="counts"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_boolean_count():
    body = (
        '{"Success": true, "Data": {"EquipmentServiceStatus": ['
        '{"Name": "Asansörler", "ActiveCount": true, "InactiveCount": 0}]}}'
    )
    async with json_client(
        body,
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="counts"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_non_integral_count():
    body = (
        '{"Success": true, "Data": {"EquipmentServiceStatus": ['
        '{"Name": "Asansörler", "ActiveCount": 3.5, "InactiveCount": 0}]}}'
    )
    async with json_client(
        body,
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="counts"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_rejects_data_without_status_groups():
    body = '{"Success": true, "Data": {"Other": []}}'
    async with json_client(
        body,
        url="https://example.test/metro/GetFaultyEquipments",
    ) as http_client:
        client = MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="status groups"):
            await client.equipment_summary()


@pytest.mark.asyncio
async def test_metro_equipment_summary_uses_only_get_method():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(405, request=request)
        return httpx.Response(200, text=fixture_text("metro/equipment_summary_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        rows = await MetroClient(
            equipment_summary_url="https://example.test/metro/GetFaultyEquipments",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_summary()
    assert rows == []


# --- Detail source (HTML fault page) ---


@pytest.mark.asyncio
async def test_metro_equipment_faults_parses_html_rows_and_preserves_source_fields():
    async with json_client(
        fixture_text("metro/equipment_faults_success.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        client = MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        rows = await client.equipment_faults()

    assert len(rows) == 2
    assert rows[0]["source_fault_id"] == "001003618886"
    assert rows[0]["source_line_id"] == "M1A"
    assert rows[0]["station_name"] == "Aksaray"
    assert rows[0]["equipment_type"] == "Yürüyen Merdiven"
    assert rows[0]["expected_return"] == "İnceleniyor"
    assert rows[0]["status"] is None
    # Same physical fault under a different line context is preserved.
    assert rows[1]["source_line_id"] == "M1B"


@pytest.mark.asyncio
async def test_metro_equipment_faults_accepts_checked_empty_page():
    async with json_client(
        fixture_text("metro/equipment_faults_empty.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        rows = await MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_faults()
    assert rows == []


@pytest.mark.asyncio
async def test_metro_equipment_faults_preserves_exact_duplicates_for_service_dedup():
    async with json_client(
        fixture_text("metro/equipment_faults_duplicates.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        rows = await MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_faults()
    assert len(rows) == 2
    assert rows[0] == rows[1]


@pytest.mark.asyncio
async def test_metro_equipment_faults_keeps_missing_expected_return_as_none():
    async with json_client(
        fixture_text("metro/equipment_faults_missing_fields.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        rows = await MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_faults()
    assert rows[0]["expected_return"] is None
    assert rows[0]["station_name"] == "Sanayi"
    assert rows[0]["equipment_type"] == "Yürüyen Bant"


@pytest.mark.asyncio
async def test_metro_equipment_faults_rejects_changed_markup_as_malformed():
    async with json_client(
        fixture_text("metro/equipment_faults_malformed.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        client = MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        )
        with pytest.raises(MetroPayloadError, match="markup"):
            await client.equipment_faults()


@pytest.mark.asyncio
async def test_metro_equipment_faults_distinguishes_checked_empty_from_changed_markup():
    # An empty table body with the official header is a legitimate checked-empty page.
    async with json_client(
        fixture_text("metro/equipment_faults_empty.html"),
        url="https://example.test/metro/ariza",
    ) as http_client:
        rows = await MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_faults()
    assert rows == []


@pytest.mark.asyncio
async def test_metro_equipment_faults_counts_malformed_rows_beside_valid_ones():
    html = (
        "<html><body><table><thead><tr><th>İstasyon</th><th>Ekipman</th>"
        "<th>Arıza Nedeni</th><th>Planlanan Dönüş</th></tr></thead><tbody>"
        # Valid row
        '<tr data-arizaid="1" data-hatid="M2" data-refekipman="AS"><td>Levent</td>'
        '<td>Turnike katındaki asansör</td><td>Arıza</td><td>İnceleniyor</td></tr>'
        # Malformed row: no cell content (empty station + no location)
        '<tr data-arizaid="2" data-hatid="M2"><td></td></tr>'
        "</tbody></table></body></html>"
    )
    client = MetroClient()
    rows = client._parse_equipment_faults(html)
    assert len(rows) == 1
    assert rows[0]["source_fault_id"] == "1"
    assert client._last_malformed_detail_count == 1


@pytest.mark.asyncio
async def test_metro_equipment_faults_all_malformed_structured_page_is_source_failure():
    # A structured page where every data row carries a fault id but no usable cells
    # is a schema-drift source failure, not a checked-empty result.
    html = (
        "<html><body><table><thead><tr><th>İstasyon</th><th>Ekipman</th>"
        "<th>Arıza Nedeni</th><th>Planlanan Dönüş</th></tr></thead><tbody>"
        '<tr data-arizaid="9" data-hatid="M2"></tr>'
        "</tbody></table></body></html>"
    )
    client = MetroClient()
    with pytest.raises(MetroPayloadError, match="malformed"):
        client._parse_equipment_faults(html)


@pytest.mark.asyncio
async def test_metro_equipment_faults_uses_only_get_method():
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            return httpx.Response(405, request=request)
        return httpx.Response(200, text=fixture_text("metro/equipment_faults_empty.html"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        rows = await MetroClient(
            equipment_faults_url="https://example.test/metro/ariza",
            http_client=http_client,
            rate_limiter=RecordingLimiter(),
        ).equipment_faults()
    assert rows == []
