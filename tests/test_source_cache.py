import pytest

from app.core.settings import get_settings
from app.core.source_cache import (
    SourceLoadResult,
    SourceTTLCache,
    cached_source_data,
    clear_source_cache,
    source_cache_snapshot,
)


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
async def test_source_cache_boundary_fresh_then_stale_then_unavailable(monkeypatch):
    """Prove fresh through TTL, explicit stale up to max_age, then unavailable."""
    from app.core.source_cache import CachedSourceData, SourceTTLCache, cached_source_data_with_status

    clock = {"t": 0.0}

    def fake_monotonic() -> float:
        return clock["t"]

    monkeypatch.setattr("app.core.source_cache.time.monotonic", fake_monotonic)

    cache = SourceTTLCache()
    load_calls = {"n": 0}

    async def loader():
        load_calls["n"] += 1
        return [{"id": "1"}]

    # t=0 -> fresh load
    entry = await cache.get_with_status(
        "metro_accessibility.details",
        ttl_seconds=120,
        max_entries=100,
        loader=loader,
        stale_if_error_seconds=900,
    )
    assert entry.is_fresh is True and entry.is_stale is False

    # advance beyond TTL but within total-age cap -> next call must become stale
    clock["t"] = 200.0
    load_calls["n"] = 0

    async def failing_loader():
        load_calls["n"] += 1
        raise RuntimeError("upstream down")

    entry = await cache.get_with_status(
        "metro_accessibility.details",
        ttl_seconds=120,
        max_entries=100,
        loader=failing_loader,
        stale_if_error_seconds=900,
    )
    assert entry.is_fresh is False
    assert entry.is_stale is True
    assert entry.error is not None

    # advance beyond TTL + max-age (120 + 900) -> unavailable/raise; the entry must
    # no longer be served and the cache must drop the stale source.
    clock["t"] = 1050.0
    import pytest as _pytest

    with _pytest.raises(RuntimeError):
        await cache.get_with_status(
            "metro_accessibility.details",
            ttl_seconds=120,
            max_entries=100,
            loader=failing_loader,
            stale_if_error_seconds=900,
        )

    # After expiry the cache no longer holds the stale entry, so a later successful
    # load returns fresh rather than the previously cached stale value.
    clock["t"] = 1050.0
    entry = await cache.get_with_status(
        "metro_accessibility.details",
        ttl_seconds=120,
        max_entries=100,
        loader=loader,
        stale_if_error_seconds=900,
    )
    assert entry.is_fresh is True
    assert entry.is_stale is False


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


@pytest.mark.asyncio
async def test_source_cache_enforces_total_age_cap_and_single_flight(monkeypatch):
    clock = {"t": 100.0}
    monkeypatch.setattr("app.core.source_cache.time.monotonic", lambda: clock["t"])
    cache = SourceTTLCache()
    calls = 0

    async def loader():
        nonlocal calls
        calls += 1
        return SourceLoadResult(value={"calls": calls}, max_cache_age_seconds=1800)

    first = await cache.get_with_status(
        "ibb_pharmacy.roster",
        ttl_seconds=300,
        max_entries=10,
        loader=loader,
        stale_if_error_seconds=1500,
    )
    assert first.is_fresh
    clock["t"] = 401.0

    async def failing():
        raise RuntimeError("source unavailable")

    stale = await cache.get_with_status(
        "ibb_pharmacy.roster",
        ttl_seconds=300,
        max_entries=10,
        loader=failing,
        stale_if_error_seconds=1500,
    )
    assert stale.is_stale
    clock["t"] = 1901.0
    with pytest.raises(RuntimeError):
        await cache.get_with_status(
            "ibb_pharmacy.roster",
            ttl_seconds=300,
            max_entries=10,
            loader=failing,
            stale_if_error_seconds=1500,
        )

    # Two concurrent callers share one refresh lock.
    clear_source_cache()
    cache = SourceTTLCache()
    calls = 0
    import asyncio

    async def slow_loader():
        nonlocal calls
        calls += 1
        await asyncio.sleep(0)
        return SourceLoadResult(value={"calls": calls}, max_cache_age_seconds=1800)

    await asyncio.gather(
        cache.get_with_status("ibb_pharmacy.roster", ttl_seconds=300, max_entries=10, loader=slow_loader),
        cache.get_with_status("ibb_pharmacy.roster", ttl_seconds=300, max_entries=10, loader=slow_loader),
    )
    assert calls == 1
