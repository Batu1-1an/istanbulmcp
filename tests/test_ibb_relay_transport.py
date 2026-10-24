import json

import httpx
import pytest

from app.connectors.http_retry import request_with_retries
from app.connectors.ibb_relay import RELAY_HOSTS, IbbRelayTransport, ibb_http_client, validate_ibb_relay_settings
from app.core.settings import Settings, get_settings
from app.core.status import build_status
from relays.ibb_relay.server import ALLOWED_HOSTS

TOKEN = "r" * 40


def relay_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=IbbRelayTransport("https://relay.example/base/", TOKEN, inner=httpx.MockTransport(handler)))


@pytest.mark.asyncio
async def test_relay_transport_routes_ibb_hosts_through_relay_with_token() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    async with relay_client(handler) as client:
        get = await client.get("https://api.ibb.gov.tr/ispark/Park?ilce=Kad%C4%B1k%C3%B6y")
        post = await client.post("https://data.ibb.gov.tr/api/3/action/datastore_search", json={"limit": 1})

    assert get.json() == {"ok": True} and post.status_code == 200
    assert str(seen[0].url) == "https://relay.example/base/api.ibb.gov.tr/ispark/Park?ilce=Kad%C4%B1k%C3%B6y"
    assert str(seen[1].url) == "https://relay.example/base/data.ibb.gov.tr/api/3/action/datastore_search"
    assert all(request.headers["x-relay-token"] == TOKEN for request in seen)
    assert all(request.headers["host"] == "relay.example" for request in seen)
    assert json.loads(seen[1].content) == {"limit": 1}
    assert get.request.url.host == "api.ibb.gov.tr"


@pytest.mark.asyncio
async def test_relay_transport_sends_other_hosts_directly() -> None:
    seen: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200)

    async with relay_client(handler) as client:
        await client.get("https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-baraj-doluluk-oranlari")
        await client.get("http://api.ibb.gov.tr/plain-http")

    assert [str(request.url) for request in seen] == [
        "https://www.turkiye.gov.tr/istanbul-su-ve-kanalizasyon-idaresi-baraj-doluluk-oranlari",
        "http://api.ibb.gov.tr/plain-http",
    ]
    assert all("x-relay-token" not in request.headers for request in seen)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("error", "exception"),
    [("connect_timeout", httpx.ConnectTimeout), ("connect_error", httpx.ConnectError), ("read_timeout", httpx.ReadTimeout)],
)
async def test_relay_transport_raises_upstream_failures_as_httpx_errors(error, exception) -> None:
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(504, headers={"X-Relay-Error": error}, json={"error": error})

    async with relay_client(handler) as client:
        with pytest.raises(exception, match="api.ibb.gov.tr"):
            await client.get("https://api.ibb.gov.tr/ispark/Park")


@pytest.mark.asyncio
async def test_relay_connect_timeout_triggers_unreachable_host_cooldown() -> None:
    calls = 0

    async def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(504, headers={"X-Relay-Error": "connect_timeout"})

    async with relay_client(handler) as client:
        for _ in range(2):
            with pytest.raises(httpx.ConnectTimeout):
                await request_with_retries(client, "GET", "https://api.ibb.gov.tr/ispark/Park", attempts=3)

    assert calls == 1


def test_ibb_http_client_uses_relay_only_when_configured(monkeypatch) -> None:
    assert not isinstance(ibb_http_client()._transport, IbbRelayTransport)

    monkeypatch.setenv("IBB_RELAY_BASE_URL", "https://relay.example")
    monkeypatch.setenv("IBB_RELAY_TOKEN", TOKEN)
    get_settings.cache_clear()

    assert isinstance(ibb_http_client(timeout=5)._transport, IbbRelayTransport)
    injected = httpx.MockTransport(lambda _request: httpx.Response(200))
    assert ibb_http_client(transport=injected)._transport is injected


@pytest.mark.parametrize(
    ("url", "token", "message"),
    [
        ("https://relay.example", None, "set together"),
        (None, TOKEN, "set together"),
        ("http://relay.example", TOKEN, "https"),
        ("https://relay.example", "short", "at least"),
    ],
)
def test_ibb_relay_settings_reject_incomplete_or_unsafe_values(url, token, message) -> None:
    with pytest.raises(ValueError, match=message):
        validate_ibb_relay_settings(Settings(ibb_relay_base_url=url, ibb_relay_token=token))


def test_ibb_relay_settings_are_optional() -> None:
    assert validate_ibb_relay_settings(Settings()) is False
    assert validate_ibb_relay_settings(Settings(ibb_relay_base_url="https://relay.example", ibb_relay_token=TOKEN)) is True


def test_relay_host_allowlists_match() -> None:
    assert RELAY_HOSTS == ALLOWED_HOSTS


def test_status_reports_ibb_relay_without_exposing_token() -> None:
    body = build_status(Settings(ibb_relay_base_url="https://relay.example", ibb_relay_token=TOKEN))

    assert body["limits"]["ibb_relay_enabled"] is True
    assert TOKEN not in json.dumps(body)
