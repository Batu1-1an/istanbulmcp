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

    # Rows follow the source order from the JSON payload.
    assert rows[0]["category_key"] == "elevator"
    assert rows[0]["active_count"] == 668
    assert rows[0]["inactive_count"] == 12
    assert rows[0]["is_visible"] is True
    assert rows[0]["source_order"] == 4
    assert rows[1]["category_key"] == "escalator"
    assert rows[1]["source_order"] == 1
    assert rows[4]["category_key"] == "restroom"
    assert rows[6]["category_key"] == "baby_care_room"
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

    assert len(rows) == 3
    assert rows[0]["source_fault_id"] == "1001"
    assert rows[0]["source_line_id"] == "2"
    assert rows[0]["station_name"] == "Levent"
    assert rows[0]["equipment_type"] == "Asansör"
    assert rows[0]["expected_return"] == "İnceleniyor"
    assert rows[0]["status"] is None


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
        "<html><body><table><thead><tr><th>Hat</th><th>İstasyon</th><th>Ekipman</th>"
        "<th>Konum</th><th>Arıza Nedeni</th><th>Planlanan Dönüş</th></tr></thead><tbody>"
        # Valid row
        '<tr data-arizaid="1" data-hatid="2"><td>M2</td><td>Levent</td><td>Asansör</td>'
        '<td>konum</td><td>Arıza</td><td>İnceleniyor</td></tr>'
        # Malformed row: too few cells
        '<tr data-arizaid="2"><td>M2</td><td>Bozuk</td></tr>'
        "</tbody></table></body></html>"
    )
    client = MetroClient()
    rows = client._parse_equipment_faults(html)
    assert len(rows) == 1
    assert rows[0]["source_fault_id"] == "1"
    assert client._last_malformed_detail_count == 1


@pytest.mark.asyncio
async def test_metro_equipment_faults_all_malformed_structured_page_is_source_failure():
    html = (
        "<html><body><table><thead><tr><th>Hat</th><th>İstasyon</th></tr></thead><tbody>"
        '<tr data-arizaid="9"><td>M2</td></tr>'
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
