from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from app.connectors.ibb_pharmacy import IbbPharmacyClient, IbbPharmacyPayloadError, IbbPharmacySourceError


FIXTURES = Path(__file__).parent / "fixtures" / "ibb_pharmacy"
BASE_URL = "https://fixture.example/?eczanews"


class FakeLimiter:
    def __init__(self):
        self.acquires = []
        self.penalties = []

    async def acquire(self, source: str):
        self.acquires.append(source)

    def penalize(self, retry_after_seconds: float):
        self.penalties.append(retry_after_seconds)


def response_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_client_gets_full_roster_once_and_normalizes_singleton_and_empty():
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        return httpx.Response(200, text=response_fixture("roster_success.json"), request=request)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        limiter = FakeLimiter()
        client = IbbPharmacyClient(BASE_URL, http_client=http_client, rate_limiter=limiter)
        rows = await client.roster()
    assert len(rows) == 3
    assert limiter.acquires == ["ibb_pharmacy"]
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.query == b"eczanews&ilceID=all"

    assert IbbPharmacyClient._parse_payload(json.loads(response_fixture("roster_singleton.json")))
    assert IbbPharmacyClient._parse_payload(json.loads(response_fixture("roster_empty.json"))) == []


@pytest.mark.asyncio
async def test_client_retries_retryable_statuses_with_get_only():
    requests = []

    async def handler(request: httpx.Request):
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(503, request=request)
        return httpx.Response(200, text=response_fixture("roster_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IbbPharmacyClient(BASE_URL, attempts=2, http_client=http_client, rate_limiter=FakeLimiter())
        assert await client.roster() == []
    assert [request.method for request in requests] == ["GET", "GET"]
    assert all(request.url.query == b"eczanews&ilceID=all" for request in requests)


@pytest.mark.asyncio
async def test_client_retries_timeout_then_succeeds():
    calls = 0

    async def handler(request: httpx.Request):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("timed out", request=request)
        return httpx.Response(200, text=response_fixture("roster_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IbbPharmacyClient(BASE_URL, attempts=2, http_client=http_client, rate_limiter=FakeLimiter())
        assert await client.roster() == []
    assert calls == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("fixture", ["roster_malformed.json", "roster_missing_list.json", "roster_wrong_shape.json"])
async def test_client_rejects_invalid_payload_shapes(fixture: str):
    async def handler(request: httpx.Request):
        return httpx.Response(200, text=response_fixture(fixture), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IbbPharmacyClient(BASE_URL, http_client=http_client, rate_limiter=FakeLimiter())
        with pytest.raises(IbbPharmacyPayloadError):
            await client.roster()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [400, 404, 500, 429])
async def test_client_surfaces_non_success_as_safe_source_error(status: int):
    async def handler(request: httpx.Request):
        return httpx.Response(status, text="private upstream body", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        client = IbbPharmacyClient(BASE_URL, attempts=1, http_client=http_client, rate_limiter=FakeLimiter())
        with pytest.raises(IbbPharmacySourceError) as exc_info:
            await client.roster()
    assert "private upstream body" not in str(exc_info.value)
