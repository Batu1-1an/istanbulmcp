import pytest

from app.core.settings import get_settings
from app.core.source_cache import SourceTTLCache, cached_source_data, clear_source_cache, source_cache_snapshot


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
    assert all("cache_key_hash" in row for row in snapshot)


@pytest.mark.asyncio
async def test_source_cache_snapshot_does_not_expose_raw_user_parameters():
    async def loader():
        return {"ok": True}

    await cached_source_data(
        'ckan.package_search.{"query":"private search term","rows":1,"formats":[]}',
        ttl_seconds=60,
        loader=loader,
    )

    snapshot = source_cache_snapshot()

    assert snapshot == [
        {
            "source": "ckan.package_search",
            "cache_key_hash": snapshot[0]["cache_key_hash"],
            "refreshed_at": snapshot[0]["refreshed_at"],
            "expires_in_seconds": snapshot[0]["expires_in_seconds"],
            "is_fresh": True,
        }
    ]
    assert "private search term" not in str(snapshot)


@pytest.mark.asyncio
async def test_source_cache_removes_failed_key_locks():
    cache = SourceTTLCache()

    async def failing_loader():
        raise RuntimeError("upstream failed")

    for index in range(5):
        with pytest.raises(RuntimeError):
            await cache.get(
                f"ckan.package_search.failure-{index}",
                ttl_seconds=60,
                max_entries=2,
                loader=failing_loader,
            )

    assert len(cache._entries) == 0
    assert len(cache._locks) == 0
