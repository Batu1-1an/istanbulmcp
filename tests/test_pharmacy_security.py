from __future__ import annotations

import inspect

import pytest

from app.connectors.ibb_pharmacy import IbbPharmacyClient
from app.core.settings import Settings
from app.services.pharmacy import IBB_CACHE_KEY, PharmacyService


def test_connector_is_read_only_and_has_no_secret_or_raw_body_logging():
    source = inspect.getsource(IbbPharmacyClient)
    assert '"POST"' not in source
    assert ".text" not in source
    assert "print(" not in source
    assert "Authorization" not in source
    assert IBB_CACHE_KEY == "ibb_pharmacy.on_duty_pharmacies"


def test_connector_rejects_noncanonical_network_target_without_injected_client():
    with pytest.raises(ValueError):
        IbbPharmacyClient("https://example.invalid/pharmacy")
    with pytest.raises(ValueError):
        IbbPharmacyClient("https://cbsproxy.ibb.gov.tr/private")


@pytest.mark.asyncio
async def test_service_enforces_radius_and_limit_bounds_before_fetch():
    class Client:
        calls = 0

        async def roster(self):
            self.calls += 1
            return []

    client = Client()
    service = PharmacyService(settings=Settings(), ibb_client=client)
    too_far = await service.nearby(lat=41.0, lon=29.0, radius_m=5001)
    too_many = await service.by_district(district="Kadıköy", limit=101)
    non_integer = await service.nearby(lat=41.0, lon=29.0, radius_m=1.5)
    assert too_far["ok"] is False
    assert too_many["ok"] is False
    assert non_integer["ok"] is False
    assert client.calls == 0
