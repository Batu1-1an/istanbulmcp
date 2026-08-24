import httpx
import pytest
from pathlib import Path

from app.connectors.iett import IettClient, IettSoapError


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


LINE_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetHat_jsonResponse xmlns="http://tempuri.org/">
      <GetHat_jsonResult>[{"SHATKODU":"34A","SHATADI":"CEVIZLIBAG - SOGUTLUCESME","TARIFE":"METROBUS"}]</GetHat_jsonResult>
    </GetHat_jsonResponse>
  </soap:Body>
</soap:Envelope>
"""


STOPS_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <DurakDetay_GYY_wYonAdiResponse xmlns="http://tempuri.org/">
      <DurakDetay_GYY_wYonAdiResult>
        <NewDataSet xmlns="">
          <Table>
            <HATKODU>34A</HATKODU><YON>D</YON><YON_ADI> CEVIZLIBAG </YON_ADI>
            <SIRANO>1</SIRANO><DURAKKODU>900011</DURAKKODU><DURAKADI>SOGUTLUCESME</DURAKADI>
            <XKOORDINATI>29.037636</XKOORDINATI><YKOORDINATI>40.991647</YKOORDINATI>
            <DURAKTIPI>ISTASYON</DURAKTIPI><ILCEADI>Kadikoy</ILCEADI>
          </Table>
        </NewDataSet>
      </DurakDetay_GYY_wYonAdiResult>
    </DurakDetay_GYY_wYonAdiResponse>
  </soap:Body>
</soap:Envelope>
"""

DISRUPTIONS_XML = (Path(__file__).parent / "fixtures" / "iett" / "disruptions_response.xml").read_text(encoding="utf-8")
PLANNED_DEPARTURES_XML = (Path(__file__).parent / "fixtures" / "iett" / "planned_departures_response.xml").read_text(encoding="utf-8")

MALFORMED_ROWS_XML = """<?xml version="1.0" encoding="utf-8"?>
<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">
  <soap:Body>
    <GetDuyurular_jsonResponse xmlns="http://tempuri.org/">
      <GetDuyurular_jsonResult>[{"HAT":"34A"}, "not-an-object"]</GetDuyurular_jsonResult>
    </GetDuyurular_jsonResponse>
  </soap:Body>
</soap:Envelope>
"""


@pytest.mark.asyncio
async def test_line_info_parses_json_result():
    limiter = RecordingLimiter()

    async def handler(_request):
        return httpx.Response(200, text=LINE_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IettClient(http_client=http_client, rate_limiter=limiter)
        rows = await client.line_info("34A")

    assert rows[0]["SHATKODU"] == "34A"
    assert limiter.acquired == ["iett"]


@pytest.mark.asyncio
async def test_stops_for_line_parses_table_result():
    async def handler(_request):
        return httpx.Response(200, text=STOPS_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IettClient(http_client=http_client)
        rows = await client.stops_for_line("34A")

    assert rows[0]["DURAKKODU"] == "900011"
    assert rows[0]["YON_ADI"].strip() == "CEVIZLIBAG"


@pytest.mark.asyncio
async def test_disruptions_parses_fixture_and_uses_configured_endpoint():
    limiter = RecordingLimiter()

    async def handler(request):
        assert str(request.url) == "https://example.test/duyurular"
        return httpx.Response(200, text=DISRUPTIONS_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IettClient(
            http_client=http_client,
            rate_limiter=limiter,
            duyurular_url="https://example.test/duyurular",
        )
        rows = await client.disruptions()

    assert len(rows) == 3
    assert rows[0]["HATKODU"] == "34A"
    assert rows[0]["HAT"] == "BEYLİKDÜZÜ - SÖĞÜTLÜÇEŞME"
    assert limiter.acquired == ["iett"]


@pytest.mark.asyncio
async def test_planned_departures_parses_fixture_and_sends_line_code():
    async def handler(request):
        assert str(request.url) == "https://example.test/planned"
        assert "<HatKodu>500T</HatKodu>" in request.content.decode()
        return httpx.Response(200, text=PLANNED_DEPARTURES_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IettClient(
            http_client=http_client,
            planlanan_sefer_saati_url="https://example.test/planned",
        )
        rows = await client.planned_departures("500T")

    assert len(rows) == 5
    assert rows[0]["SGUNTIPI"] == "I"


@pytest.mark.asyncio
async def test_disruptions_rejects_non_object_json_rows():
    async def handler(_request):
        return httpx.Response(200, text=MALFORMED_ROWS_XML)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IettClient(http_client=http_client, rate_limiter=RecordingLimiter())

        with pytest.raises(IettSoapError, match="object"):
            await client.disruptions()
