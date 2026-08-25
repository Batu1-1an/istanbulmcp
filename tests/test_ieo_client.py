from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from app.connectors.ieo import IeoAccessError, IeoClient, IeoPayloadError, IeoSourceError


FIXTURES = Path(__file__).parent / "fixtures" / "ieo"
BASE_URL = "https://fixture.example/nobetci-eczane/index.php"


class NoopLimiter:
    def __init__(self):
        self.sources: list[str] = []

    async def acquire(self, source: str) -> None:
        self.sources.append(source)

    def penalize(self, _retry_after_seconds: float) -> None:
        pass


def fixture_text(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_ieo_client_preserves_session_and_ajax_contract():
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(
                200,
                text=fixture_text("index.html"),
                headers={"set-cookie": "PHPSESSID=fixture-session; Path=/"},
                request=request,
            )
        assert request.method == "POST"
        form = parse_qs(request.content.decode("utf-8"))
        assert form == {
            "jx": ["1"],
            "islem": ["get_eczane_markers"],
            "h": ["fixture-access-token"],
        }
        assert request.headers["referer"] == BASE_URL
        assert request.headers["x-requested-with"] == "XMLHttpRequest"
        assert "PHPSESSID=fixture-session" in request.headers["cookie"]
        return httpx.Response(200, text=fixture_text("markers_success.json"), request=request)

    limiter = NoopLimiter()
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await IeoClient(
            base_url=BASE_URL,
            http_client=client,
            rate_limiter=limiter,
            attempts=2,
        ).markers()

    assert len(rows) == 4
    assert [request.method for request in requests] == ["GET", "POST"]
    assert limiter.sources == ["ieo"]


@pytest.mark.asyncio
async def test_ieo_client_repeats_complete_handshake_after_access_failure():
    get_count = 0
    post_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count, post_count
        if request.method == "GET":
            get_count += 1
            token = f"fixture-access-token-{get_count}"
            return httpx.Response(
                200,
                text=f'<input type="hidden" id="h" value="{token}">',
                headers={"set-cookie": f"PHPSESSID=session-{get_count}; Path=/"},
                request=request,
            )
        post_count += 1
        if post_count == 1:
            return httpx.Response(403, text="expired access", request=request)
        form = parse_qs(request.content.decode("utf-8"))
        assert form["h"] == ["fixture-access-token-2"]
        assert "PHPSESSID=session-2" in request.headers["cookie"]
        return httpx.Response(200, text=fixture_text("markers_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await IeoClient(
            base_url=BASE_URL,
            http_client=client,
            rate_limiter=NoopLimiter(),
            attempts=2,
        ).markers()

    assert rows == []
    assert (get_count, post_count) == (2, 2)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403, 419])
async def test_ieo_client_retries_complete_handshake_after_page_access_failure(status_code: int):
    get_count = 0
    post_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count, post_count
        if request.method == "GET":
            get_count += 1
            if get_count == 1:
                return httpx.Response(status_code, text="access denied", request=request)
            return httpx.Response(200, text=fixture_text("index.html"), request=request)
        post_count += 1
        return httpx.Response(200, text=fixture_text("markers_empty.json"), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows = await IeoClient(
            base_url=BASE_URL,
            http_client=client,
            rate_limiter=NoopLimiter(),
            attempts=2,
        ).markers()

    assert rows == []
    assert (get_count, post_count) == (2, 1)


@pytest.mark.asyncio
async def test_ieo_client_surfaces_page_access_error_after_bounded_handshakes():
    get_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal get_count
        get_count += 1
        return httpx.Response(403, text="access denied", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IeoAccessError):
            await IeoClient(
                base_url=BASE_URL,
                http_client=client,
                rate_limiter=NoopLimiter(),
                attempts=2,
            ).markers()

    assert get_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (httpx.Response(200, text=fixture_text("markers_malformed.json")), IeoPayloadError),
        (httpx.Response(200, text=json.dumps({"error": 1, "eczaneler": None})), IeoPayloadError),
    ],
)
async def test_ieo_client_rejects_malformed_marker_payload(response: httpx.Response, expected: type[Exception]):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=fixture_text("index.html"), request=request)
        return httpx.Response(response.status_code, text=response.text, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(expected):
            await IeoClient(base_url=BASE_URL, http_client=client, rate_limiter=NoopLimiter()).markers()


@pytest.mark.asyncio
async def test_ieo_client_rejects_missing_access_value_without_posting():
    post_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_called
        if request.method == "POST":
            post_called = True
        return httpx.Response(200, text="<html><body>No access field</body></html>", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IeoPayloadError, match="access"):
            await IeoClient(base_url=BASE_URL, http_client=client, rate_limiter=NoopLimiter()).markers()

    assert post_called is False


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 429])
async def test_ieo_client_surfaces_non_success_source_responses(status_code: int):
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=fixture_text("index.html"), request=request)
        return httpx.Response(status_code, text="upstream failure", headers={"retry-after": "0"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IeoSourceError):
            await IeoClient(
                base_url=BASE_URL,
                http_client=client,
                rate_limiter=NoopLimiter(),
                attempts=2,
            ).markers()


@pytest.mark.asyncio
async def test_ieo_client_wraps_timeout_after_bounded_retries():
    post_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal post_calls
        if request.method == "GET":
            return httpx.Response(200, text=fixture_text("index.html"), request=request)
        post_calls += 1
        raise httpx.ReadTimeout("fixture timeout", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(IeoSourceError):
            await IeoClient(
                base_url=BASE_URL,
                http_client=client,
                rate_limiter=NoopLimiter(),
                attempts=2,
            ).markers()

    assert post_calls == 2
