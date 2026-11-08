"""Free-price consistency at a frozen clock and retained catalogue lifecycle."""
from datetime import datetime,timedelta,timezone
import pytest
from app.core.events import EventObservation,EventOffer,EventVenue,ISTANBUL
from app.core.settings import Settings
from app.core.envelope import ResponseEnvelope
from app.services.events import EventService
from app.storage.events import EventRepository
from app.storage.db import connect


@pytest.fixture
def sample(tmp_path,monkeypatch):
    import app.services.events as module
    now=datetime(2026,11,8,15,26,tzinfo=ISTANBUL)
    class Clock(datetime):
        @classmethod
        def now(cls,tz=None):return now.astimezone(tz) if tz else now.replace(tzinfo=None)
    monkeypatch.setattr(module,"datetime",Clock)
    settings=Settings(events_enabled=True,ticketmaster_api_key="fixture-only",database_path=tmp_path/"free.sqlite3")
    def row(identity,hour=18,price=0,stock="in_stock",day=8):
        return EventObservation(source="ticketmaster",source_id=identity,series_key=identity,
            title=identity,category="family",start_at=datetime(2026,11,day,hour,tzinfo=ISTANBUL),
            venue=EventVenue(name="Sahne"),observed_at=now,
            offers=[] if price is None else [EventOffer(price=price,currency="TRY",availability=stock)])
    repo=EventRepository(settings.database_path)
    rows=[row("past",13),row("free"),row("paid",price=100),row("unknown",price=None),
          row("sold",stock="sold_out"),row("tomorrow",day=9)]
    repo.publish("ticketmaster",rows,{})
    return EventService(settings,repository=repo),row


@pytest.mark.asyncio
async def test_same_snapshot_free_is_exactly_the_eligible_zero_price_subset(sample):
    events,_=sample
    args=dict(date_from="2026-11-08",date_to="2026-11-08",limit=50)
    normal=await events.search(**args)
    free=await events.search(**args,free_only=True)
    expected={x["performance_id"] for x in normal["data"] if x["price"]["status"]=="known" and x["price"]["minimum_observed_try"]==0}
    assert {x["performance_id"] for x in free["data"]}==expected
    assert [x["title"] for x in free["data"]]==["free"]
    counts=free["result_info"]["filter_counts"]
    assert counts["excluded_started"]==1 and counts["excluded_sold_out"]==1
    assert counts["excluded_unknown_price"]==1 and counts["verified_free"]==1
    assert any("already started" in note for note in free["warnings"])
    ResponseEnvelope.model_validate(free)


@pytest.mark.asyncio
async def test_include_past_exposes_retained_started_sessions_without_becoming_an_archive(sample):
    events,_=sample
    args=dict(date_from="2026-11-08",date_to="2026-11-08",free_only=True,include_past=True)
    result=await events.search(**args)
    assert {x["title"] for x in result["data"]}=={"past","free"}
    # A multi-day window must not silently bypass the same default clock rule.
    default=await events.search(date_from="2026-11-07",date_to="2026-11-08")
    assert "past" not in {x["title"] for x in default["data"]}


@pytest.mark.asyncio
async def test_sold_out_free_session_is_visible_only_with_explicit_stock_opt_in(sample):
    events,_=sample
    result=await events.search(date_from="2026-11-08",date_to="2026-11-08",free_only=True,include_sold_out=True)
    sold=next(x for x in result["data"] if x["title"]=="sold")
    assert sold["availability"]=="sold_out" and sold["price"]["minimum_observed_try"]==0


@pytest.mark.asyncio
async def test_expired_zero_price_is_unknown_even_when_past_sessions_are_included(sample):
    events,row=sample
    expired=row("expired",13).model_copy(update={"observed_at":datetime(2026,11,8,2,13,tzinfo=ISTANBUL)})
    events.repository.publish("ticketmaster",[expired],{})
    result=await events.search(date_from="2026-11-08",date_to="2026-11-08",include_past=True,free_only=True)
    assert not result["data"]
    assert result["result_info"]["filter_counts"]["expired_offer_observations"]==1
    assert any("expired" in note for note in result["warnings"])


@pytest.mark.asyncio
async def test_past_inspection_does_not_refresh_or_revalidate_old_prices(sample,monkeypatch):
    from dataclasses import replace
    events,row=sample
    settings=replace(events.settings,ticketmaster_api_key=None,events_biletinial_enabled=True)
    expired=row("expired",13).model_copy(update={"source":"biletinial","observed_at":datetime(2026,11,8,2,13,tzinfo=ISTANBUL)})
    events.repository.publish("biletinial",[expired],{})
    events=EventService(settings,repository=events.repository)
    async def unexpected(*args):pytest.fail("Past observations must not be refreshed into current prices")
    monkeypatch.setattr(events,"detail",unexpected)
    result=await events.search(date_from="2026-11-08",date_to="2026-11-08",include_past=True,free_only=True)
    assert not result["data"] and result["result_info"]["filter_counts"]["detail_checks_attempted"]==0


@pytest.mark.asyncio
async def test_free_result_beyond_first_fifty_candidates_is_not_missed(sample):
    events,row=sample
    events.repository.publish("ticketmaster",[row(f"paid-{i}",16,100) for i in range(60)]+[row("free",18)],{})
    result=await events.search(date_from="2026-11-08",date_to="2026-11-08",free_only=True,limit=1)
    assert result["data"][0]["title"]=="free"
    assert result["result_info"]["filter_counts"]["indexed_candidates"]==61


@pytest.mark.asyncio
async def test_started_session_can_still_be_resolved_by_detail(sample):
    events,row=sample
    result=await events.detail(row("past",13).event_id)
    assert result["ok"] and result["data"][0]["performances"][0]["title"]=="past"


@pytest.mark.asyncio
async def test_archive_inspection_does_not_recommend_a_past_day_as_a_plan(sample,monkeypatch):
    import app.services.event_plan as module
    import app.services.events as event_module
    from app.services.event_plan import EventPlanService
    monkeypatch.setattr(module,"datetime",event_module.datetime)
    events,row=sample
    past=row("yesterday",13,day=7)
    events.repository.publish("ticketmaster",[past],{})
    result=await EventPlanService(events.settings,events=events).plan(date="2026-11-07",
        start_time="09:00",end_time="18:00",event_ids=[past.performance_id])
    assert not result["data"][0]["options"]
    assert result["data"][0]["rejected"][0]["reason"]=="session_already_started"


@pytest.mark.asyncio
async def test_retired_id_and_unknown_history_are_distinct(sample):
    events,row=sample
    old=row("past",13)
    events.repository.publish("ticketmaster",[row("replacement")],{})
    retired=await events.detail(old.event_id)
    assert retired["error"]["code"]=="catalogue_retired"
    assert retired["data"][0]["catalogue_state"]["retained_sessions"]==1
    missing=await events.detail("event_"+"0"*24)
    assert missing["error"]["code"]=="not_found"
    assert "exact reason is unknown" in missing["warnings"][0]


@pytest.mark.asyncio
async def test_active_id_with_expired_source_is_not_reported_as_unknown(sample):
    events,row=sample
    with connect(events.settings.database_path) as conn:
        conn.execute("UPDATE event_source_snapshots SET refreshed_at='2000-01-01T00:00:00+00:00'")
    result=await events.detail(row("free").event_id)
    assert result["error"]["code"]=="source_unavailable" and result["error"]["temporary"]
