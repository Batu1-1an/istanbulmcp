"""Event source parsing, persistence, MCP contracts and planning invariants."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import gzip
import json
from pathlib import Path

import httpx
from mcp import Client
import pytest

from app.connectors.biletinial import parse_biletinial_detail, parse_biletinial_list
from app.connectors.events_http import EventSourceError, read_event_body, event_rate_limiter
from app.connectors.ticketmaster import parse_ticketmaster, TicketmasterClient
from app.core.envelope import ResponseEnvelope
from app.core.events import EventObservation, EventOffer, EventVenue, ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.mcp.events import EVENT_TOOL_NAMES
from app.mcp.registry import create_mcp_server
from app.services.events import EventService, availability, deduplicate, event_card
from app.services.events import current_observation
from app.services.event_plan import EventPlanService, enumerate_plans
from app.storage.events import EventRepository

FIXTURES = Path(__file__).parent / "fixtures/events"


@pytest.fixture(autouse=True)
def event_cache():
    clear_source_cache()
    event_rate_limiter.cache_clear()
    yield
    clear_source_cache()
    event_rate_limiter.cache_clear()


def observation(identity="one", **updates):
    row = EventObservation(source="biletinial", source_id=identity, series_key=identity, title="Örnek Oyun",
        category="theatre", start_at=datetime(2030, 11, 8, 18, tzinfo=ISTANBUL), end_at=datetime(2030, 11, 8, 19, tzinfo=ISTANBUL),
        venue=EventVenue(name="Örnek Sahne",district="Kadıköy",lat=40.987,lon=29.028,side="asia"),
        offers=[EventOffer(price=100,currency="TRY",availability="in_stock")],
        ticket_url="https://biletinial.com/tr-tr/tiyatro/ornek-oyun", observed_at=datetime.now(timezone.utc), detail_checked=True)
    return row.model_copy(update=updates)


@pytest.fixture
def service(tmp_path):
    settings = Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/"events.sqlite3")
    repo=EventRepository(settings.database_path)
    repo.publish("biletinial", [observation()], {"received":1,"accepted":1,"skipped":0,"complete":True})
    return EventService(settings,repository=repo)


def test_ticketmaster_keeps_unknown_price_and_availability_and_filters_city():
    rows,meta=parse_ticketmaster(json.loads((FIXTURES/"ticketmaster.json").read_text()))
    assert len(rows)==2 and meta["received"]==3
    assert not rows[0].offers and availability(rows[0])=="unknown"
    assert rows[0].sales_status=="on_sale" and rows[0].end_at is None
    assert rows[0].start_at.hour==20
    assert rows[1].program_status=="cancelled"


def test_event_card_explains_source_topic_without_html_scripts_or_embedded_links():
    row = observation(description='<p>İki kardeşin yıllar sonra karşılaşmasını anlatan bir oyun.</p>'
                      '<script>secret_script()</script><style>hidden_css</style>'
                      '<p>Ayrıntı: https://example.test/story</p>')
    about = event_card(row)['about']
    assert 'İki kardeşin yıllar sonra karşılaşmasını anlatan bir oyun.' in about['text']
    assert not any(value in about['text'] for value in ('<p>', 'secret_script', 'hidden_css', 'https://'))
    assert about['source_url'] == row.ticket_url and about['observed_at'] == row.observed_at.isoformat()
    assert about['status'] == 'available' and about['is_untrusted_source_text']


@pytest.mark.parametrize('source,checked,status', [
    ('biletinial', False, 'not_checked'), ('biletinial', True, 'not_published'),
    ('ticketmaster', False, 'not_published'),
])
def test_missing_topic_is_distinct_from_uninspected_detail_and_not_invented(source,checked,status):
    about = event_card(observation(source=source, detail_checked=checked, description=None))['about']
    assert about['text'] is None and about['status'] == status


def test_long_source_description_stays_bounded_and_marks_the_excerpt_incomplete():
    about = event_card(observation(description='Kentin hafızasını keşfeden bir sergi. ' * 100))['about']
    assert len(about['text']) <= 500 and about['truncated']
    assert about['kind'] == 'source_excerpt'


@pytest.mark.parametrize('title,label', [
    ('Quintet Dinleti', 'Konseri'),
    ("Mengü Ertel'in Tiyatro Evreni Sergi Turu", 'Biletleri'),
])
def test_heading_and_buttons_alone_do_not_count_as_a_published_topic(title, label):
    raw = f'HAKKINDA {title} {title} {label} Daha fazlasını göster ! Etkinliğe Gitmeden önce kuralları okuyun. →'
    about = event_card(observation(title=title, description=raw))['about']
    assert about['text'] is None and about['status'] == 'not_published'


def test_topic_retains_real_story_after_duplicate_titles_and_buttons_are_removed():
    row = observation(title='Kavuşma', description='HAKKINDA Kavuşma Kavuşma İki eski dost yıllar sonra karşılaşır. '
                      'Daha fazlasını göster ! Etkinliğe Gitmeden önce kuralları okuyun. →')
    about = event_card(row)['about']
    assert about['text'] == 'İki eski dost yıllar sonra karşılaşır.'
    assert about['status'] == 'available'


def test_title_cleanup_preserves_words_that_only_start_with_the_same_letters():
    about = event_card(observation(title='Ada', description='Adalar arasında geçen bir yolculuk hikâyesi.'))['about']
    assert about['text'] == 'Adalar arasında geçen bir yolculuk hikâyesi.'


@pytest.mark.asyncio
async def test_topic_reaches_search_selected_detail_and_daily_plan(service, monkeypatch):
    row = observation(description='Eski bir dostluğu yeniden kuran iki kişinin hikâyesi.')
    async def source_detail(self, *args):
        return [row], {}
    monkeypatch.setattr('app.connectors.biletinial.BiletinialClient.detail', source_detail)
    service.repository.publish('biletinial', [row], {})
    search = await service.search(date_from='2030-11-08', date_to='2030-11-08')
    detail = await service.detail(row.performance_id)
    plan = await EventPlanService(service.settings, events=service).plan(
        date='2030-11-08', start_time='17:00', end_time='22:00', event_ids=[row.performance_id])
    cards = [search['data'][0], detail['data'][0]['performances'][0],
             plan['data'][0]['options'][0]['performances'][0]]
    assert all(card['about']['text'] == row.description for card in cards)
    assert detail['data'][0]['description'] == row.description


def test_biletinial_list_does_not_assign_series_price_or_representative_venue_to_sessions():
    rows,more=parse_biletinial_list(json.loads((FIXTURES/"biletinial-list.json").read_text()),"tiyatro")
    assert not more and len(rows)==2
    assert not rows[0].offers and rows[0].venue.name=="Unknown venue"
    assert not rows[0].detail_checked


def test_biletinial_detail_uses_html_sessions_prices_and_sold_out_beyond_jsonld():
    starts=[datetime(2030,11,8,h,tzinfo=ISTANBUL) for h in (18,20)]
    rows,meta=parse_biletinial_detail((FIXTURES/"biletinial-detail.html").read_text(),"https://biletinial.com/tr-tr/tiyatro/ornek-oyun",starts)
    assert len(rows)==2 and meta["complete"]
    assert rows[0].source_id=="101" and [o.price for o in rows[0].offers]==[100,200]
    assert rows[0].end_at.hour==19
    assert availability(rows[1])=="sold_out" and rows[1].end_at is None


@pytest.mark.asyncio
async def test_event_download_rejects_gzip_bomb():
    async def handler(request):
        return httpx.Response(200,stream=httpx.ByteStream(gzip.compress(b"x"*10000)))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EventSourceError,match="limit"):
            await read_event_body(client,"https://example.test",max_uncompressed=100)


@pytest.mark.asyncio
async def test_feed_redirect_does_not_forward_key_and_rejects_untrusted_destination():
    requests=[]
    def handler(request):
        requests.append(request)
        if request.url.host=="app.ticketmaster.com":
            return httpx.Response(303,headers={"location":"https://s3.amazonaws.com/prd141.dcfd.prod1.us-east-1.tmaws-feeds/20301108/events.json.gz"})
        return httpx.Response(200,stream=httpx.ByteStream(gzip.compress((FIXTURES/"ticketmaster.json").read_bytes())))
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        rows,_=await TicketmasterClient(Settings(ticketmaster_api_key="private-fixture-key"),client).catalogue()
    assert len(rows)==2 and "apikey" not in requests[1].url.params
    def malicious(request):
        return httpx.Response(303,headers={"location":"https://evil.test/steal"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(malicious)) as client:
        with pytest.raises(EventSourceError,match="not allowed"):
            await read_event_body(client,"https://app.ticketmaster.com/test",params={"apikey":"secret"})


def test_failed_snapshot_does_not_retire_previous_rows_and_identity_survives_reschedule(tmp_path):
    repo=EventRepository(tmp_path/"events.sqlite3")
    original=observation()
    repo.publish("biletinial",[original],{})
    with pytest.raises(ValueError):
        repo.publish("biletinial",[observation(source="ticketmaster")],{})
    assert repo.detail(original.event_id)[0].start_at==original.start_at
    shifted=original.model_copy(update={"start_at":original.start_at+timedelta(hours=1)})
    repo.publish("biletinial",[shifted],{})
    assert repo.detail(original.performance_id)[0].performance_id==original.performance_id


def test_fts_normalization_and_update_delete_triggers(tmp_path):
    repo=EventRepository(tmp_path/"events.sqlite3")
    row=observation(title="Sıla")
    repo.publish("biletinial",[row],{})
    assert len(repo.search(row.start_at,row.start_at+timedelta(days=1),query="sila"))==1
    repo.publish("biletinial",[row.model_copy(update={"title":"İclal"})],{})
    assert not repo.search(row.start_at,row.start_at+timedelta(days=1),query="sila")
    assert len(repo.search(row.start_at,row.start_at+timedelta(days=1),query="iclal"))==1


@pytest.mark.asyncio
async def test_search_preserves_unknown_budget_and_honest_publisher(service):
    row=observation(offers=[])
    service.repository.publish("biletinial",[row],{})
    result=await service.search(date_from="2030-11-08",date_to="2030-11-08",max_price_try=500)
    ResponseEnvelope.model_validate(result)
    assert result["ok"] and result["data"][0]["budget_status"]=="unknown"
    assert result["sources"][0]["publisher"]=="Biletinial"
    assert result["sources"][0]["license"] is None
    assert not (await service.search(date_from="2030-11-08",date_to="2030-11-08",free_only=True))["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("args",[{"limit":0},{"lat":float("nan"),"lon":29},{"radius_m":1000},{"category":"cinema"},{"date_from":"2030-11-01","date_to":"2030-12-31"},{"max_price_try":float("inf")},{"district":"Ankara"}])
async def test_event_search_validates_before_network(service,args):
    result=await service.search(**args)
    assert not result["ok"] and result["error"]["code"]=="validation_error"


def test_dedupe_does_not_merge_same_provider_or_different_sessions():
    a=observation("a")
    b=observation("b")
    c=observation("c",source="ticketmaster")
    groups=deduplicate([a,b,c])
    assert len(groups)==2
    assert sum(len(g[1]) for g in groups)==3


def test_enumeration_never_overlaps_and_unknown_end_only_last():
    a=observation("a")
    b=observation("b",start_at=a.start_at+timedelta(hours=2),end_at=None)
    c=observation("c",start_at=a.start_at+timedelta(hours=3),end_at=a.end_at+timedelta(hours=3))
    options,_=enumerate_plans([event_card(r) for r in (a,b,c)],window_end=a.end_at+timedelta(hours=5),limit=50)
    assert options
    for option in options:
        path=option["performances"]
        assert len(path)<=3
        assert all(card["end_known"] for card in path[:-1])
        assert all(gap["minutes"]>=30 for gap in option["gaps"])
        assert not option["checks"]["travel_feasibility_verified"]
    assert options==enumerate_plans([event_card(r) for r in (a,b,c)],window_end=a.end_at+timedelta(hours=5),limit=50)[0]


def test_total_budget_and_unknown_budget_are_separate():
    a=observation("a")
    b=observation("b",start_at=a.start_at+timedelta(hours=2),end_at=a.end_at+timedelta(hours=2))
    c=observation("c",offers=[])
    options,unknown=enumerate_plans([event_card(r) for r in (a,b,c)],window_end=b.end_at,max_price_try=150,limit=50)
    assert all(o["known_minimum_total_try"]<=150 for o in options)
    assert all(o["total_price_known"] for o in options)
    assert unknown and all(o["budget_status"]=="unknown" for o in unknown)


@pytest.mark.asyncio
async def test_selected_event_planning_does_not_search_again(service,monkeypatch):
    async def fail(**kwargs):
        pytest.fail("selected IDs must not repeat search")
    monkeypatch.setattr(service,"search",fail)
    # Avoid live detail: this test verifies composition of already verified data.
    async def detail(identifier):
        return {"ok":True,"data":[{"performances":[event_card(observation())]}]}
    monkeypatch.setattr(service,"detail",detail)
    result=await EventPlanService(service.settings,events=service).plan(date="2030-11-08",event_ids=[observation().event_id])
    assert result["ok"] and result["data"][0]["options"]
    ResponseEnvelope.model_validate(result)


@pytest.mark.asyncio
async def test_event_tools_are_gated_callable_and_structured(monkeypatch):
    disabled=create_mcp_server(Settings())
    assert set(EVENT_TOOL_NAMES)<=disabled.callable_tool_names()
    assert not set(EVENT_TOOL_NAMES)&{tool.name for tool in await disabled.list_tools()}
    async with Client(disabled) as client:
        result=await client.call_tool("istanbul_events_search",{})
        assert result.structured_content["error"]["code"]=="feature_disabled"
    enabled=create_mcp_server(Settings(events_enabled=True))
    tools={t.name:t for t in await enabled.list_tools()}
    assert set(EVENT_TOOL_NAMES)<=tools.keys()
    for name in EVENT_TOOL_NAMES:
        assert tools[name].output_schema==ResponseEnvelope.model_json_schema()


def test_catalogue_refresh_preserves_recent_verified_details_and_retires_missing_series(tmp_path):
    repo=EventRepository(tmp_path/"events.sqlite3")
    detail=observation("101",series_key="ornek-oyun")
    repo.publish("biletinial",[detail],{})
    provisional=observation("listing",series_key="ornek-oyun",detail_checked=False,offers=[])
    repo.publish("biletinial",[provisional],{})
    retained=repo.detail(detail.event_id)
    assert len(retained)==1 and retained[0].source_id=="101" and retained[0].detail_checked
    repo.publish("biletinial",[],{})
    assert not repo.detail(detail.event_id)


def test_expired_offers_become_unknown_without_losing_verified_venue():
    row=observation(observed_at=datetime.now(timezone.utc)-timedelta(hours=1))
    current=current_observation(row,Settings(events_detail_ttl_seconds=900))
    assert not current.offers and current.venue==row.venue
    assert availability(current)=="unknown" and "expired" in current.warnings[-1]


def test_footer_sold_out_text_does_not_change_session_availability():
    html=(FIXTURES/"biletinial-detail.html").read_text()
    # The last session has no explicit stock state; a page-level JS dictionary
    # after the session must not mark it sold out.
    html=html.replace('<span>TÜKENDİ</span>','<span>BİLETİNİ AL</span>')+'<script>const messages={soldOut:"TÜKENDİ"};</script>'
    starts=[datetime(2030,11,8,h,tzinfo=ISTANBUL) for h in (18,20)]
    rows,_=parse_biletinial_detail(html,"https://biletinial.com/tr-tr/tiyatro/ornek-oyun",starts)
    assert availability(rows[1])=="unknown"


@pytest.mark.asyncio
async def test_stale_and_failed_source_preserves_snapshot_and_reports_uncertainty(service):
    from app.storage.db import connect
    old=(datetime.now(timezone.utc)-timedelta(hours=2)).isoformat()
    with connect(service.settings.database_path) as conn:
        conn.execute("UPDATE event_source_snapshots SET refreshed_at=?,last_error='TimeoutError'",(old,))
    result=await service.search(date_from="2030-11-08",date_to="2030-11-08")
    assert result["ok"] and result["data"]
    assert result["freshness"]["status"]=="stale"
    assert result["sources"][0]["coverage_status"]=="unavailable"
    assert any("failed" in w for w in result["warnings"])


@pytest.mark.asyncio
async def test_overage_source_is_not_presented_as_checked_empty(service):
    from app.storage.db import connect
    old=(datetime.now(timezone.utc)-timedelta(days=5)).isoformat()
    with connect(service.settings.database_path) as conn:
        conn.execute("UPDATE event_source_snapshots SET refreshed_at=?",(old,))
    result=await service.search(date_from="2030-11-08",date_to="2030-11-08")
    assert not result["ok"] and result["error"]["code"]=="source_unavailable"


@pytest.mark.asyncio
async def test_http_logs_redact_ticketmaster_key(caplog):
    import logging
    secret="private-fixture-key"
    with caplog.at_level(logging.INFO,logger="httpx"):
        logging.getLogger("httpx").info('HTTP Request: GET https://app.ticketmaster.com/test?apikey=%s&countryCode=TR',secret)
    assert secret not in caplog.text and "[redacted]" in caplog.text


def test_calendar_escape_folding_and_stable_uids():
    from app.services.event_plan import calendar_output
    row=observation(title='Uzun Türkçe başlık, noktalama; '+('ş'*100)+'\nBEGIN:VEVENT')
    first=calendar_output([event_card(row)])
    second=calendar_output([event_card(row)])
    assert first==second
    assert all(len(line.encode())<=75 for line in first["ics"].split('\r\n'))
    assert first["ics"].count('\r\nBEGIN:VEVENT\r\n')==1
    assert '\\nBEGIN:VEVENT' in first["ics"]
    assert 'DTSTART:20301108T150000Z' in first["ics"]
    unknown=calendar_output([event_card(row.model_copy(update={"end_at":None}))])
    assert 'DTEND:' not in unknown["ics"] and not unknown["google_calendar_links"]


def test_exact_title_does_not_merge_conflicting_venue_coordinates():
    a=observation("a")
    b=observation("b",source="ticketmaster",venue=EventVenue(name=a.venue.name,lat=41.1,lon=29.1))
    assert len(deduplicate([a,b]))==2


def test_one_seller_sold_out_does_not_mean_every_seller_sold_out():
    a=observation("a",offers=[EventOffer(availability="sold_out",price=100,currency="TRY")])
    b=observation("b",source="ticketmaster",offers=[],sales_status="on_sale")
    card=event_card(a,[a,b])
    assert card["availability"]=="unknown" and card["sales_status"]=="on_sale"
    assert len(card["ticket_links"])==2


@pytest.mark.asyncio
async def test_429_cooldown_prevents_another_upstream_request():
    from app.core.rate_limit import SourceRateLimitExceeded
    calls=[]
    def handler(request):
        calls.append(request)
        return httpx.Response(429,headers={"Retry-After":"60"})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        with pytest.raises(EventSourceError,match="429"):
            await read_event_body(client,"https://biletinial.com/example")
        with pytest.raises(SourceRateLimitExceeded):
            await read_event_body(client,"https://biletinial.com/example")
    assert len(calls)==1


def test_event_tools_work_over_streamable_http_with_feature_enabled(tmp_path,monkeypatch):
    from starlette.testclient import TestClient
    from app.main import create_app
    import app.main as main
    path=tmp_path/"http-events.sqlite3"
    EventRepository(path).publish("biletinial",[observation(description="Bir ailenin şehirde yeniden buluşma hikâyesi.")],{})
    monkeypatch.setenv("DATABASE_PATH",str(path))
    monkeypatch.setenv("EVENTS_ENABLED","true")
    monkeypatch.setenv("EVENTS_BILETINIAL_ENABLED","true")
    from app.core.settings import get_settings
    get_settings.cache_clear()
    async def no_background(settings):
        await asyncio.Event().wait()
    monkeypatch.setattr(main,"keep_events_fresh",no_background)
    with TestClient(create_app()) as client:
        headers={"accept":"application/json, text/event-stream"}
        listed=client.post('/mcp/',headers=headers,json={"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}).json()
        assert set(EVENT_TOOL_NAMES)<={t["name"] for t in listed["result"]["tools"]}
        response=client.post('/mcp/',headers=headers,json={"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
            "name":"istanbul_events_search","arguments":{"date_from":"2030-11-08","date_to":"2030-11-08"}}})
        result=response.json()["result"]
        assert result["structuredContent"]["ok"] and result["structuredContent"]["data"]
        assert result["structuredContent"]["data"][0]["about"]["text"] == "Bir ailenin şehirde yeniden buluşma hikâyesi."
        assert json.loads(result["content"][0]["text"])==result["structuredContent"]


@pytest.mark.asyncio
async def test_enabled_event_workflow_prompt_is_local():
    server=create_mcp_server(Settings(events_enabled=True))
    async with Client(server) as client:
        prompts=await client.list_prompts()
        assert "etkinlik_plani" in {p.name for p in prompts.prompts}
        rendered=await client.get_prompt("etkinlik_plani",{"date":"tomorrow","interests":"theatre"})
        assert "istanbul_events_search" in rendered.messages[0].content.text
        rendered=await client.get_prompt("etkinlik_plani",{"date":"tomorrow","child_age":"5","end_time":"18:00"})
        text=rendered.messages[0].content.text
        assert '"child_age": "5"' in text and '"end_time": "18:00"' in text
        assert "require_known_end=true" in text and "performance_id" in text
