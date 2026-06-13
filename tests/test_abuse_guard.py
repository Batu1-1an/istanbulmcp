import pytest
from starlette.testclient import TestClient

from app.core.abuse_guard import ConcurrencyLimiter
from app.core.settings import get_settings
from app.main import create_app


@pytest.fixture(autouse=True)
def clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_mcp_request_body_limit_returns_413(monkeypatch):
    monkeypatch.setenv("MCP_MAX_BODY_BYTES", "32")
    client = TestClient(create_app(), base_url="http://localhost")

    response = client.post(
        "/mcp/",
        headers={"content-type": "application/json"},
        content=b'{"jsonrpc":"2.0","id":1,"method":"ping","padding":"' + b"x" * 80 + b'"}',
    )

    assert response.status_code == 413
    assert response.json()["ok"] is False


def test_mcp_rate_limit_returns_429(monkeypatch):
    monkeypatch.setenv("MCP_RATE_LIMIT_CAPACITY", "1")
    monkeypatch.setenv("MCP_RATE_LIMIT_REFILL_PER_SECOND", "0.001")
    client = TestClient(create_app(), base_url="http://localhost")
    first = client.post(
        "/mcp/",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": None, "method": "ping"},
    )
    second = client.post(
        "/mcp/",
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        json={"jsonrpc": "2.0", "id": 2, "method": "ping"},
    )

    assert first.status_code != 429
    assert second.status_code == 429
    assert second.headers["retry-after"] == "1000"
    assert second.json()["ok"] is False


@pytest.mark.asyncio
async def test_concurrency_limiter_rejects_above_limit():
    limiter = ConcurrencyLimiter(max_concurrent=1)

    assert await limiter.acquire() is True
    assert await limiter.acquire() is False
    assert limiter.snapshot()["rejected"] == 1
    await limiter.release()
    assert await limiter.acquire() is True
