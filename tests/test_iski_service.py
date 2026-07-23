import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache, source_cache_snapshot
from app.services.iski import IskiService


FAULTS_GEOJSON = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "ILCE_KODU": "AO",
                "MAHALLE_KODU": 607,
                "MAHALLE_ADI": "ATAŞEHİR ATATÜRK MAH",
                "ILCE_ADI": "ATAŞEHİR",
                "ARIZA_NO": "10000511781",
                "ARIZA_NEVI_ACIKLAMASI": "100 MM ÇAPLI ŞEBEKE HATTI ARIZASI",
                "BASLAMA_TARIHI": "2026-06-23 10:23:52",
                "TAHMINI_BITIS_TARIHI": "23/6/2026 17:00",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [29.1230, 40.9920],
                        [29.1250, 40.9920],
                        [29.1250, 40.9940],
                        [29.1230, 40.9940],
                    ]
                ],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "ILCE_ADI": "BEŞİKTAŞ",
                "MAHALLE_ADI": "LEVENT MAH",
                "ARIZA_NO": "200",
                "ARIZA_NEVI_ACIKLAMASI": "İÇME SUYU HATTI ARIZASI",
                "BASLAMA_TARIHI": "2026-06-23 11:00:00",
                "TAHMINI_BITIS_TARIHI": "23/6/2026 18:00",
            },
            "geometry": {
                "type": "Polygon",
                "coordinates": [
                    [
                        [29.0100, 41.0800],
                        [29.0120, 41.0800],
                        [29.0120, 41.0820],
                        [29.0100, 41.0820],
                    ]
                ],
            },
        },
    ],
}

DAMS = [
    {
        "kaynakAdi": "Alibey",
        "baslikAdi": "Alibey Barajı",
        "verim": "36",
        "biriktirmeHacmi": "34.14",
        "mevcutSuHacmi": "20.29",
        "dolulukOrani": "59.44",
        "azamiSuSeviyesi": "28.0",
    },
    {
        "kaynakAdi": "Omerli",
        "baslikAdi": "Ömerli Barajı",
        "verim": "220",
        "biriktirmeHacmi": "235.37",
        "mevcutSuHacmi": "140.0",
        "dolulukOrani": "75,5",
        "azamiSuSeviyesi": "62.0",
    },
]


class FakeIski:
    last_faults_source = "live_geojson"
    last_dams_source = "live_json"
    last_faults_source_updated_at = None
    last_dams_source_updated_at = None

    def __init__(self):
        self.fault_calls = 0
        self.dam_calls = 0

    async def active_faults(self):
        self.fault_calls += 1
        return FAULTS_GEOJSON

    async def dams(self):
        self.dam_calls += 1
        return DAMS


class FailingIski:
    async def active_faults(self):
        raise RuntimeError("down")

    async def dams(self):
        raise RuntimeError("down")


class FlakyIski:
    def __init__(self):
        self.fault_calls = 0
        self.dam_calls = 0

    async def active_faults(self):
        self.fault_calls += 1
        if self.fault_calls > 1:
            raise RuntimeError("temporary fault source outage")
        return FAULTS_GEOJSON

    async def dams(self):
        self.dam_calls += 1
        if self.dam_calls > 1:
            raise RuntimeError("temporary dam source outage")
        return DAMS


class SnapshotIski:
    last_faults_source = "snapshot"
    last_dams_source = "snapshot"
    last_faults_source_updated_at = "2026-07-23T10:30:00+00:00"
    last_dams_source_updated_at = "2026-07-23T10:00:00+00:00"

    def __init__(self):
        self.fault_calls = 0
        self.dam_calls = 0

    async def active_faults(self):
        self.fault_calls += 1
        return FAULTS_GEOJSON

    async def dams(self):
        self.dam_calls += 1
        return DAMS


class ExpiringSnapshotIski(SnapshotIski):
    last_faults_cache_max_age_seconds = 1

    async def active_faults(self):
        self.fault_calls += 1
        if self.fault_calls > 1:
            raise RuntimeError("snapshot expired and live sources remain unavailable")
        return FAULTS_GEOJSON


class RelayIski(FakeIski):
    last_faults_source = "relay_geojson"
    last_dams_source = "relay_json"
    last_faults_source_updated_at = None
    last_dams_source_updated_at = None


class EdevletRelayIski(FakeIski):
    last_faults_source = "relay_edevlet"
    last_dams_source = "relay_edevlet"
    last_faults_source_updated_at = None
    last_dams_source_updated_at = None


class StaleRelayIski(EdevletRelayIski):
    last_faults_source_updated_at = "2026-07-23T10:30:00Z"
    last_faults_source_stale = True


def service(client=None):
    clear_source_cache()
    return IskiService(settings=Settings(), client=client or FakeIski())


@pytest.mark.asyncio
async def test_active_faults_filters_district_and_normalizes_rows():
    result = await service().active_faults(district="Ataşehir", limit=5)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    row = result["data"][0]
    assert row["fault_number"] == "10000511781"
    assert row["district"] == "ATAŞEHİR"
    assert row["center"] == {"lat": 40.993, "lon": 29.124}
    assert row["maps_url"] == "https://www.google.com/maps/search/?api=1&query=40.993000,29.124000"
    assert "source=live ISKI GeoJSON" in result["limits"]


@pytest.mark.asyncio
async def test_fault_by_number_returns_active_match():
    result = await service().fault_by_number("200")

    assert result["ok"] is True
    assert result["data"][0]["district"] == "BEŞİKTAŞ"
    assert "found" in result["summary"]


@pytest.mark.asyncio
async def test_fault_by_number_returns_empty_for_unknown_active_fault():
    result = await service().fault_by_number("missing")

    assert result["ok"] is True
    assert result["data"] == []
    assert "No active ISKI fault" in result["summary"]


@pytest.mark.asyncio
async def test_nearby_faults_returns_sorted_distance_matches():
    result = await service().nearby_faults(lat=40.9929, lon=29.1241, radius_m=500, limit=5)

    assert result["ok"] is True
    assert [row["fault_number"] for row in result["data"]] == ["10000511781"]
    assert result["data"][0]["distance_m"] < 50
    assert "distance uses feature center" in result["limits"]


@pytest.mark.asyncio
async def test_nearby_faults_validates_radius():
    result = await service().nearby_faults(lat=40.99, lon=29.12, radius_m=6000, limit=1)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "radius_m"
    assert result["data"][0]["allowed_max"] == 5000


@pytest.mark.asyncio
async def test_dam_occupancy_filters_name_and_minimum():
    result = await service().dam_occupancy(dam_name="Ömerli", min_occupancy=70, limit=10)

    assert result["ok"] is True
    assert [row["name"] for row in result["data"]] == ["Omerli"]
    assert result["data"][0]["occupancy_rate"] == 75.5
    assert result["data"][0]["capacity"] == 235.37


@pytest.mark.asyncio
async def test_dam_occupancy_validates_minimum():
    result = await service().dam_occupancy(min_occupancy=101)

    assert result["ok"] is False
    assert result["data"][0]["field"] == "min_occupancy"


@pytest.mark.asyncio
async def test_iski_source_failure_returns_envelope():
    result = await service(FailingIski()).active_faults()

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "source_unavailable"
    assert result["warnings"] == ["ISKI source request failed: RuntimeError"]


@pytest.mark.asyncio
async def test_iski_faults_use_ttl_cache():
    clear_source_cache()
    fake = FakeIski()
    svc = IskiService(settings=Settings(iski_faults_cache_ttl_seconds=30), client=fake)

    first = await svc.active_faults(limit=5)
    second = await svc.active_faults(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert fake.fault_calls == 1
    assert any(row["source"] == "iski.active_faults" and row["is_fresh"] for row in source_cache_snapshot())


@pytest.mark.asyncio
async def test_iski_faults_return_stale_cache_when_source_fails_after_refresh():
    clear_source_cache()
    fake = FlakyIski()
    svc = IskiService(
        settings=Settings(
            iski_faults_cache_ttl_seconds=0,
            iski_faults_stale_if_error_seconds=60,
        ),
        client=fake,
    )

    first = await svc.active_faults(limit=5)
    second = await svc.active_faults(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert "returning cached snapshot" in second["warnings"][0]
    assert fake.fault_calls == 2


@pytest.mark.asyncio
async def test_iski_dams_return_stale_cache_when_source_fails_after_refresh():
    clear_source_cache()
    fake = FlakyIski()
    svc = IskiService(
        settings=Settings(
            iski_dams_cache_ttl_seconds=0,
            iski_dams_stale_if_error_seconds=60,
        ),
        client=fake,
    )

    first = await svc.dam_occupancy(limit=5)
    second = await svc.dam_occupancy(limit=5)

    assert first["ok"] is True
    assert second["ok"] is True
    assert second["freshness"]["status"] == "stale"
    assert "returning cached snapshot" in second["warnings"][0]
    assert fake.dam_calls == 2


@pytest.mark.asyncio
async def test_iski_snapshot_source_mode_survives_cache_hits():
    clear_source_cache()
    fake = SnapshotIski()
    svc = IskiService(settings=Settings(iski_faults_cache_ttl_seconds=30), client=fake)

    first = await svc.active_faults(limit=5)
    second = await svc.nearby_faults(lat=40.9929, lon=29.1241, radius_m=500, limit=5)

    assert first["freshness"]["status"] == "stale"
    assert second["freshness"]["status"] == "stale"
    assert "returning configured snapshot fallback" in second["warnings"][0]
    assert fake.fault_calls == 1


@pytest.mark.asyncio
async def test_iski_snapshot_cache_does_not_outlive_snapshot_age(monkeypatch):
    clear_source_cache()
    clock = [100.0]
    monkeypatch.setattr("app.core.source_cache.time.monotonic", lambda: clock[0])
    fake = ExpiringSnapshotIski()
    svc = IskiService(
        settings=Settings(iski_faults_cache_ttl_seconds=30, iski_faults_stale_if_error_seconds=60),
        client=fake,
    )

    first = await svc.active_faults(limit=1)
    clock[0] = 102.0
    second = await svc.active_faults(limit=1)

    assert first["ok"] is True
    assert second["ok"] is False
    assert fake.fault_calls == 2


@pytest.mark.asyncio
async def test_iski_relay_provenance_is_reported_truthfully():
    clear_source_cache()
    svc = IskiService(
        settings=Settings(iski_relay_base_url="https://relay.example", iski_relay_token="secret"),
        client=RelayIski(),
    )

    result = await svc.active_faults(limit=1)

    assert result["freshness"]["status"] == "fresh"
    assert result["sources"][0]["name"] == "ISKI active water faults relay"
    assert result["sources"][0]["url"] == "https://relay.example/iski/faults"
    assert "source=ISKI relay GeoJSON" in result["limits"]


@pytest.mark.asyncio
async def test_iski_edevlet_relay_provenance_is_reported_truthfully():
    clear_source_cache()
    svc = IskiService(
        settings=Settings(iski_relay_base_url="https://relay.example", iski_relay_token="secret"),
        client=EdevletRelayIski(),
    )

    result = await svc.active_faults(limit=1)

    assert result["sources"][0]["name"] == "Official e-Devlet ISKI outage relay"
    assert result["sources"][0]["url"].startswith("https://www.turkiye.gov.tr/")
    assert "source=official e-Devlet outage relay" in result["limits"]
    assert any("does not provide fault numbers or geometry" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_iski_edevlet_dam_relay_provenance_is_reported_truthfully():
    clear_source_cache()
    svc = IskiService(
        settings=Settings(iski_relay_base_url="https://relay.example", iski_relay_token="secret"),
        client=EdevletRelayIski(),
    )

    result = await svc.dam_occupancy(limit=1)

    assert result["sources"][0]["name"] == "Official e-Devlet ISKI dam occupancy relay"
    assert result["sources"][0]["url"].endswith("baraj-doluluk-oranlari")
    assert "source=official e-Devlet dam relay" in result["limits"]
    assert any("does not provide current volume" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_iski_stale_relay_cache_is_not_reported_as_fresh():
    clear_source_cache()
    svc = IskiService(
        settings=Settings(iski_relay_base_url="https://relay.example", iski_relay_token="secret"),
        client=StaleRelayIski(),
    )

    result = await svc.active_faults(limit=1)

    assert result["freshness"]["status"] == "stale"
    assert result["freshness"]["source_updated_at"] == "2026-07-23T10:30:00Z"
    assert any("relay cache is stale" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_iski_snapshot_reports_capture_time_and_not_live_limit():
    clear_source_cache()
    svc = IskiService(settings=Settings(), client=SnapshotIski())

    result = await svc.active_faults(limit=1)

    assert result["freshness"]["status"] == "stale"
    assert result["freshness"]["source_updated_at"] == "2026-07-23T10:30:00+00:00"
    assert result["sources"][0]["name"] == "Configured ISKI active faults snapshot"
    assert "source=configured ISKI snapshot" in result["limits"]
    assert "source=live ISKI GeoJSON" not in result["limits"]


def test_iski_service_passes_relay_and_snapshot_settings_to_client():
    svc = IskiService(
        settings=Settings(
            iski_relay_base_url="https://relay.example",
            iski_relay_token="secret",
            iski_faults_snapshot_captured_at="2026-07-23T10:30:00Z",
            iski_dams_snapshot_captured_at="2026-07-23T10:00:00Z",
        )
    )

    assert svc.client.relay_base_url == "https://relay.example"
    assert svc.client.relay_token == "secret"
    assert svc.client.relay_timeout == 15.0
    assert svc.client.faults_snapshot_captured_at == "2026-07-23T10:30:00Z"
    assert svc.client.dams_snapshot_captured_at == "2026-07-23T10:00:00Z"
