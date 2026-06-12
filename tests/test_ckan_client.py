import json

import httpx
import pytest

from app.connectors.ckan import CkanClient, CkanError


class RecordingLimiter:
    def __init__(self):
        self.acquired: list[str] = []
        self.penalties: list[float] = []

    async def acquire(self, source: str) -> None:
        self.acquired.append(source)

    def penalize(self, retry_after_seconds: float) -> None:
        self.penalties.append(retry_after_seconds)


@pytest.mark.asyncio
async def test_package_search_posts_to_ckan_action():
    limiter = RecordingLimiter()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/package_search")
        assert request.method == "POST"
        assert json.loads(request.content)["q"] == "trafik"
        return httpx.Response(200, json={"success": True, "result": {"count": 1, "results": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = CkanClient(
            base_url="https://example.test/api/3/action",
            http_client=http_client,
            rate_limiter=limiter,
        )
        result = await client.package_search(query="trafik", rows=5)

    assert result["count"] == 1
    assert limiter.acquired == ["ckan"]


@pytest.mark.asyncio
async def test_ckan_error_on_unsuccessful_response():
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"success": False, "error": {"message": "bad"}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = CkanClient(base_url="https://example.test/api/3/action", http_client=http_client)
        with pytest.raises(CkanError):
            await client.package_show("missing")
