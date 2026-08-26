from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.metro_accessibility import MetroAccessibilityService


@pytest.fixture(autouse=True)
def _clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


class FakeMetroClient:
    def __init__(self, summary_rows, fault_rows):
        self.summary_rows = summary_rows
        self.fault_rows = fault_rows
        self.equipment_summary_url = "https://example.test/summary"
        self.equipment_faults_url = "https://example.test/ariza"

    async def equipment_summary(self):
        return list(self.summary_rows)

    async def equipment_faults(self):
        return list(self.fault_rows)


def make_rows(count: int):
    rows = []
    for i in range(count):
        rows.append(
            {
                "source_fault_id": str(5000 + i),
                "source_line_id": "2",
                "line_code": "M2",
                "station_name": f"İstasyon {i}",
                "equipment_type": "Asansör",
                "location_description": f"konum {i}",
                "reason": "Arıza",
                "expected_return": "İnceleniyor",
            }
        )
    return rows


SUMMARY = [
    {"category_key": "elevator", "category_name": "Asansörler", "group_name": "Asansör", "active_count": 668, "inactive_count": 12, "is_visible": True, "source_order": 4},
    {"category_key": "escalator", "category_name": "Yürüyen Merdivenler", "group_name": "Yürüyen Merdiven", "active_count": 120, "inactive_count": 3, "is_visible": True, "source_order": 1},
    {"category_key": "station:gece isiklandirma", "category_name": "Gece Işıklandırma", "group_name": "Işıklandırma", "active_count": 300, "inactive_count": 7, "is_visible": False, "source_order": 11},
]


def make_service(rows):
    return MetroAccessibilityService(
        settings=Settings(),
        metro_client=FakeMetroClient(SUMMARY, rows),
    )


@pytest.mark.asyncio
async def test_warm_cache_p95_under_5_seconds():
    rows = make_rows(120)
    service = make_service(rows)

    # Warm the source cache once; the 100+ measurements below are cache hits.
    await service.status()
    latencies = []
    for _ in range(100):
        start = time.perf_counter()
        await service.status()
        latencies.append((time.perf_counter() - start) * 1000)

    latencies.sort()
    p95_ms = latencies[int(0.95 * (len(latencies) - 1))]
    assert p95_ms < 5000


@pytest.mark.asyncio
async def test_concurrent_single_flight_reuses_one_upstream_call():
    rows = make_rows(50)
    client = FakeMetroClient(SUMMARY, rows)
    summary_calls = {"n": 0}
    detail_calls = {"n": 0}
    orig_summary = client.equipment_summary
    orig_details = client.equipment_faults

    async def counting_summary():
        summary_calls["n"] += 1
        return await orig_summary()

    async def counting_details():
        detail_calls["n"] += 1
        return await orig_details()

    client.equipment_summary = counting_summary
    client.equipment_faults = counting_details

    service = MetroAccessibilityService(settings=Settings(), metro_client=client)
    # Fire many concurrent requests; the shared cache should collapse each refresh
    # into a single upstream call while the value is fresh.
    await asyncio.gather(*(service.status() for _ in range(30)))
    assert summary_calls["n"] == 1
    assert detail_calls["n"] == 1


@pytest.mark.asyncio
async def test_cold_concurrent_per_query_p95_under_5_seconds_single_upstream_call():
    # Measure the INDIVIDUAL completion latency of each cold concurrent query (not
    # the aggregate wall time) and assert the per-query p95 is <= 5 seconds, while
    # also confirming the shared cache collapses to exactly one upstream call.
    rows = make_rows(120)
    client = FakeMetroClient(SUMMARY, rows)
    summary_calls = {"n": 0}
    detail_calls = {"n": 0}
    orig_summary = client.equipment_summary
    orig_details = client.equipment_faults

    async def counting_summary():
        summary_calls["n"] += 1
        return await orig_summary()

    async def counting_details():
        detail_calls["n"] += 1
        return await orig_details()

    client.equipment_summary = counting_summary
    client.equipment_faults = counting_details

    service = MetroAccessibilityService(settings=Settings(), metro_client=client)

    async def timed_call() -> float:
        start = time.perf_counter()
        await service.status(limit=5)
        return (time.perf_counter() - start) * 1000

    # Launch all 100 cold queries concurrently and time each one individually.
    latencies = await asyncio.gather(*(timed_call() for _ in range(100)))
    latencies.sort()
    p95_ms = latencies[int(0.95 * (len(latencies) - 1))]

    assert p95_ms <= 5000
    assert summary_calls["n"] == 1
    assert detail_calls["n"] == 1


@pytest.mark.asyncio
async def test_concurrent_p95_under_5_seconds_and_single_upstream_call():
    rows = make_rows(60)
    client = FakeMetroClient(SUMMARY, rows)
    summary_calls = {"n": 0}
    detail_calls = {"n": 0}
    orig_summary = client.equipment_summary
    orig_details = client.equipment_faults

    async def counting_summary():
        summary_calls["n"] += 1
        return await orig_summary()

    async def counting_details():
        detail_calls["n"] += 1
        return await orig_details()

    client.equipment_summary = counting_summary
    client.equipment_faults = counting_details

    service = MetroAccessibilityService(settings=Settings(), metro_client=client)
    # Warm the cache once so concurrent runs observe enforced single-flight and
    # per-query latency.
    await service.status()

    async def timed_call() -> float:
        start = time.perf_counter()
        await service.status(limit=10)
        return (time.perf_counter() - start) * 1000

    latencies = await asyncio.gather(*(timed_call() for _ in range(100)))
    p95_ms = sorted(latencies)[int(0.95 * (len(latencies) - 1))]

    assert p95_ms <= 5000
    # After the warm call the shared cache keeps one upstream call per source.
    assert summary_calls["n"] == 1
    assert detail_calls["n"] == 1
