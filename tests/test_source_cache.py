import pytest

from app.core.settings import get_settings
from app.core.source_cache import cached_source_data, clear_source_cache, source_cache_snapshot


@pytest.fixture(autouse=True)
def clear_cache_and_settings():
    clear_source_cache()
    get_settings.cache_clear()
    yield
    clear_source_cache()
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_source_cache_evicts_oldest_entry_when_max_entries_reached(monkeypatch):
    monkeypatch.setenv("SOURCE_CACHE_MAX_ENTRIES", "2")
    get_settings.cache_clear()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return {"call": calls}

    await cached_source_data("source.a", ttl_seconds=60, loader=loader)
    await cached_source_data("source.b", ttl_seconds=60, loader=loader)
    await cached_source_data("source.c", ttl_seconds=60, loader=loader)

    snapshot = source_cache_snapshot()
    assert len(snapshot) == 2
    assert {row["source"] for row in snapshot} == {"source.b", "source.c"}
