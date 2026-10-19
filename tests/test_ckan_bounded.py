import json

import httpx
import pytest

from app.connectors.ckan import CkanClient, CkanError


class Limiter:
    async def acquire(self, _source):
        pass


def client_for(http_client):
    return CkanClient(base_url="https://fixture.test/api/3/action",
                      http_client=http_client, rate_limiter=Limiter())


@pytest.mark.asyncio
async def test_bounded_ckan_pages_never_send_sql_and_pin_sort():
    async def handler(request):
        assert request.url.path == "/api/3/action/datastore_search"
        assert request.headers["accept-encoding"] == "identity"
        assert json.loads(request.content) == {
            "resource_id": "fixture", "limit": 2, "offset": 3,
            "sort": "_id asc", "include_total": True,
        }
        return httpx.Response(200, json={"success": True, "result": {"total": 0, "fields": [], "records": []}})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result, size = await client_for(http).datastore_search_bounded(
            resource_id="fixture", limit=2, offset=3, max_bytes=1000,
        )
    assert result["total"] == 0
    assert 0 < size <= 1000


@pytest.mark.asyncio
async def test_bounded_ckan_checks_content_length_before_reading():
    async def handler(_request):
        return httpx.Response(200, headers={"content-length": "999999"}, content=b"{}")
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(CkanError, match="byte limit"):
            await client_for(http).datastore_search_bounded(resource_id="fixture", limit=2, offset=0, max_bytes=1000)


@pytest.mark.asyncio
async def test_bounded_ckan_stops_chunked_body_and_closes_response():
    class Stream(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            for _ in range(4):
                yield b"x" * 65536
        async def aclose(self):
            self.closed = True
    stream = Stream()
    async def handler(_request):
        return httpx.Response(200, stream=stream)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(CkanError, match="byte limit"):
            await client_for(http).datastore_search_bounded(
                resource_id="fixture", limit=2, offset=0, max_bytes=1000,
            )
    assert stream.closed


@pytest.mark.parametrize("body,headers", [
    (b'{"success":true,"result":{"x":NaN}}', {}),
    (b'{"success":false,"error":{"message":"fixture"}}', {}),
    (b'{}', {}),
    (b'{}', {"content-encoding": "identity-unexpected"}),
])
@pytest.mark.asyncio
async def test_bounded_ckan_rejects_bad_envelopes_and_unexpected_encoding(body, headers):
    async def handler(_request):
        return httpx.Response(200, content=body, headers=headers)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        with pytest.raises(CkanError):
            await client_for(http).datastore_search_bounded(resource_id="fixture", limit=2, offset=0, max_bytes=1000)


@pytest.mark.asyncio
async def test_bounded_ckan_does_not_follow_redirects():
    calls = []
    async def handler(request):
        calls.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/private"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as http:
        with pytest.raises(httpx.HTTPStatusError):
            await client_for(http).datastore_search_bounded(resource_id="fixture", limit=2, offset=0, max_bytes=1000)
    assert len(calls) == 1
