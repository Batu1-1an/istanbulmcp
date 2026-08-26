from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.pharmacy import PharmacyService


FIXTURE = Path(__file__).parent / "fixtures" / "ibb_pharmacy" / "roster_success.json"


class FastClient:
    def __init__(self, rows):
        self.rows = rows
        self.calls = 0

    async def roster(self):
        self.calls += 1
        await asyncio.sleep(0)
        return self.rows


@pytest.mark.asyncio
async def test_pharmacy_fresh_warm_cache_and_single_flight_p95_under_five_seconds():
    clear_source_cache()
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))["ArrayOfAramaList"]["AramaList"]
    client = FastClient(rows)
    service = PharmacyService(settings=Settings(), ibb_client=client)

    fresh_samples = []
    service.settings = Settings(ibb_pharmacy_cache_ttl_seconds=0)
    for _ in range(100):
        started = time.perf_counter()
        await service.nearby(lat=40.9909, lon=29.0303)
        fresh_samples.append(time.perf_counter() - started)
    fresh_samples.sort()

    clear_source_cache()
    service.settings = Settings()
    warm_samples = []
    await service.nearby(lat=40.9909, lon=29.0303)
    for _ in range(100):
        started = time.perf_counter()
        await service.nearby(lat=40.9909, lon=29.0303)
        warm_samples.append(time.perf_counter() - started)
    warm_samples.sort()
    assert fresh_samples[94] < 5
    assert warm_samples[94] < 5
    assert client.calls == 101

    clear_source_cache()
    client = FastClient(rows)
    service = PharmacyService(settings=Settings(), ibb_client=client)
    await asyncio.gather(
        service.nearby(lat=40.9909, lon=29.0303),
        service.nearby(lat=40.9909, lon=29.0303),
    )
    assert client.calls == 1
