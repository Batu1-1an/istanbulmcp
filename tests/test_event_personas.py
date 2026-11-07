"""User-intent regressions found by the live persona UAT, without live sources."""
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.connectors.biletinial import BiletinialClient, parse_biletinial_detail
from app.core.events import EventObservation, EventVenue, EventOffer, ISTANBUL, age_suitability
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.events import EventService
from app.services.event_plan import EventPlanService, choose_candidates
from app.storage.events import EventRepository


def show(identity, hour=18, category="theatre", **values):
    row = EventObservation(source="biletinial", source_id=identity, series_key=identity,
        title="Oyun " + identity, category=category, start_at=datetime(2030,11,8,hour,tzinfo=ISTANBUL),
        end_at=datetime(2030,11,8,hour+1,tzinfo=ISTANBUL),
        venue=EventVenue(name="Moda Sahnesi",district="Kadıköy",lat=40.98,lon=29.02,side="asia"),
        offers=[EventOffer(price=100,currency="TRY",availability="in_stock")],
        observed_at=datetime.now(timezone.utc),detail_checked=True,
        ticket_url=f"https://biletinial.com/tr-tr/tiyatro/{identity}")
    return row.model_copy(update=values)


def service_for(tmp_path, rows):
    settings=Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/"personas.sqlite3")
    repo=EventRepository(settings.database_path)
    repo.publish("biletinial",rows,{"accepted":len(rows)})
    return EventService(settings,repository=repo)


@pytest.fixture(autouse=True)
def clear_cache():
    clear_source_cache()
    yield
    clear_source_cache()


@pytest.mark.asyncio
async def test_parent_plan_does_not_fall_back_to_adult_theatre_when_family_is_missing(tmp_path):
    events=service_for(tmp_path,[show("adult")])
    result=await EventPlanService(events.settings,events=events).plan(date="2030-11-08",interests=["family"])
    assert result["ok"] and not result["data"][0]["options"]


@pytest.mark.asyncio
async def test_family_after_first_fifty_general_results_is_still_considered(tmp_path):
    rows=[show(f"adult-{i}",hour=10) for i in range(60)]
    rows.append(show("child",hour=15,category="family",age_limit="3-10"))
    events=service_for(tmp_path,rows)
    result=await EventPlanService(events.settings,events=events).plan(date="2030-11-08",start_time="09:00",end_time="18:00",interests=["family"])
    assert result["data"][0]["options"]
    assert all(c["category"]=="family" for option in result["data"][0]["options"] for c in option["performances"])


@pytest.mark.asyncio
async def test_parent_age_filter_uses_published_range_not_title_guess(tmp_path):
    rows=[show("child",category="family",age_limit="3-10"),show("missing-age",category="family")]
    events=service_for(tmp_path,rows)
    result=await events.search(date_from="2030-11-08",date_to="2030-11-08",child_age=5)
    assert [c["title"] for c in result["data"]]==["Oyun child"]
    assert not (await events.search(date_from="2030-11-08",date_to="2030-11-08",child_age=12))["data"]


@pytest.mark.parametrize("label,age,status",[("3-10",5,"within"),("3-10",12,"outside"),("7+",6,"outside"),("7 yaş ve üzeri",8,"within"),(None,5,"unknown")])
def test_age_limits_remain_explicit(label,age,status):
    assert age_suitability(label,age)==status


def test_child_genre_duration_and_age_come_from_source_facts():
    html=(Path(__file__).parent/"fixtures/events/biletinial-detail.html").read_text()
    html+='<dl><dt>Etkinlik Türü</dt><dd>Çocuk Oyunu</dd><dt>Yaş Sınırı</dt><dd>3-10</dd><dt>Süre</dt><dd>50 dakika</dd></dl>'
    rows,_=parse_biletinial_detail(html,"https://biletinial.com/tr-tr/tiyatro/ornek-oyun",[datetime(2030,11,8,20,tzinfo=ISTANBUL)])
    assert all(row.category=="family" and row.age_limit=="3-10" for row in rows)
    assert rows[1].end_source=="published_duration"
    assert rows[1].end_at-rows[1].start_at==timedelta(minutes=50)


def test_catalogue_price_hint_never_becomes_a_verified_session_price():
    import json
    from app.connectors.biletinial import parse_biletinial_list
    from app.services.events import event_card
    payload=json.loads((Path(__file__).parent/"fixtures/events/biletinial-list.json").read_text())
    rows,_=parse_biletinial_list(payload,"tiyatro")
    assert rows[0].catalogue_min_price_try==100
    assert event_card(rows[0])["price"]["status"]=="unknown"


@pytest.mark.asyncio
async def test_turkish_category_aliases_are_accepted(tmp_path):
    events=service_for(tmp_path,[show("adult")])
    result=await events.search(date_from="2030-11-08",date_to="2030-11-08",category="tiyatro")
    assert result["ok"] and result["data"][0]["category"]=="theatre"


@pytest.mark.asyncio
async def test_title_query_does_not_match_only_a_venue_name(tmp_path):
    events=service_for(tmp_path,[show("one",title="Benimle Oynar Mısın",venue=EventVenue(name="Sultanbeyli Sahnesi"))])
    assert not (await events.search(query="su",date_from="2030-11-08",date_to="2030-11-08"))["data"]
    assert (await events.search(query="su",query_scope="all",match_mode="prefix",date_from="2030-11-08",date_to="2030-11-08"))["data"]


@pytest.mark.asyncio
async def test_budget_question_refreshes_only_three_relevant_series_and_can_exclude_unknown_prices(tmp_path,monkeypatch):
    rows=[show(f"play-{i}",offers=[],detail_checked=False,observed_at=datetime.now(timezone.utc)-timedelta(hours=1)) for i in range(5)]
    events=service_for(tmp_path,rows)
    indexed={r.series_key:r for r in rows}
    checked=[]
    async def detail(self,url,known_starts):
        identity=url.rsplit('/',1)[-1];checked.append(identity)
        return [indexed[identity].model_copy(update={"offers":[EventOffer(price=100,currency="TRY",availability="in_stock")],"detail_checked":True,"observed_at":datetime.now(timezone.utc)})],{}
    monkeypatch.setattr(BiletinialClient,"detail",detail)
    result=await events.search(date_from="2030-11-08",date_to="2030-11-08",max_price_try=300,include_unknown_prices=False)
    assert len(checked)==3 and len(result["data"])==3
    assert all(card["price"]["status"]=="known" and card["budget_status"]=="within" for card in result["data"])


@pytest.mark.asyncio
async def test_selected_performance_does_not_turn_into_a_different_series_session(tmp_path):
    a=show("early",source="ticketmaster",series_key="same")
    b=show("late",source="ticketmaster",series_key="same",start_at=a.start_at+timedelta(hours=2),end_at=a.end_at+timedelta(hours=2))
    settings=Settings(events_enabled=True,ticketmaster_api_key="fixture-only",database_path=tmp_path/"selection.sqlite3")
    repo=EventRepository(settings.database_path);repo.publish("ticketmaster",[a,b],{})
    events=EventService(settings,repository=repo)
    result=await EventPlanService(settings,events=events).plan(date="2030-11-08",event_ids=[b.performance_id])
    assert result["data"][0]["options"]
    assert all(c["performance_id"]==b.performance_id for option in result["data"][0]["options"] for c in option["performances"])


@pytest.mark.asyncio
async def test_strict_finish_deadline_excludes_unknown_end(tmp_path):
    events=service_for(tmp_path,[show("unknown",end_at=None)])
    result=await EventPlanService(events.settings,events=events).plan(date="2030-11-08",end_time="22:00",require_known_end=True)
    assert not result["data"][0]["options"]
    assert result["data"][0]["rejected"][0]["reason"]=="end_time_unknown"


@pytest.mark.asyncio
async def test_attendance_search_excludes_explicit_sold_out_unless_requested(tmp_path):
    sold=show("sold",offers=[EventOffer(price=100,currency="TRY",availability="sold_out")])
    events=service_for(tmp_path,[sold])
    assert not (await events.search(date_from="2030-11-08",date_to="2030-11-08"))["data"]
    result=await events.search(date_from="2030-11-08",date_to="2030-11-08",include_sold_out=True)
    assert result["data"][0]["availability"]=="sold_out"


@pytest.mark.asyncio
async def test_ambiguous_provisional_session_requires_reselection(tmp_path,monkeypatch):
    original=show("listing",series_key="same",detail_checked=False,venue=EventVenue())
    events=service_for(tmp_path,[original])
    async def detail(self,url,known_starts):
        return [show("a",series_key="same",venue=EventVenue(name="A")),show("b",series_key="same",venue=EventVenue(name="B"))],{}
    monkeypatch.setattr(BiletinialClient,"detail",detail)
    result=await EventPlanService(events.settings,events=events).plan(date="2030-11-08",event_ids=[original.performance_id])
    assert not result["ok"] and result["error"]["code"]=="selection_changed"


def test_candidate_budget_does_not_drop_later_hours_due_to_early_crowding():
    from app.services.events import event_card
    cards=[event_card(show(f"early-{i}",hour=10)) for i in range(60)]
    cards.append(event_card(show("evening",hour=21)))
    chosen=choose_candidates(cards)
    assert len(chosen)==20 and any(c["title"]=="Oyun evening" for c in chosen)


def test_hour_sampling_keeps_both_ends_of_a_full_day():
    from app.services.events import event_card
    base=show("base",hour=0)
    cards=[event_card(base.model_copy(update={"source_id":str(i),"series_key":str(i),
        "start_at":base.start_at+timedelta(hours=i),"end_at":base.end_at+timedelta(hours=i)})) for i in range(24)]
    selected=choose_candidates(cards,limit=3)
    assert selected[0]["start_at"]==cards[0]["start_at"] and selected[-1]["start_at"]==cards[-1]["start_at"]


@pytest.mark.asyncio
async def test_interests_limit_is_checked_before_duplicate_normalization(tmp_path):
    events=service_for(tmp_path,[show("one")])
    result=await EventPlanService(events.settings,events=events).plan(date="2030-11-08",interests=["tiyatro"]*6)
    assert not result["ok"] and result["error"]["code"]=="validation_error"


def test_failed_and_past_details_do_not_starve_upcoming_series(tmp_path):
    now=datetime.now(timezone.utc)
    a=show("failed",start_at=now+timedelta(hours=1),end_at=None,detail_checked=False)
    b=show("good",start_at=now+timedelta(hours=2),end_at=None,detail_checked=False)
    past=show("past",start_at=now-timedelta(days=1),end_at=None,detail_checked=False)
    events=service_for(tmp_path,[a,b,past])
    events.repository.detail_checked(a.event_id,succeeded=False,retry_seconds=300,error_type="fixture_failure")
    assert events.repository.pending_details(limit=10,ttl_seconds=900)==[b.event_id]


@pytest.mark.asyncio
async def test_first_schema_initialization_is_safe_for_concurrent_readers(tmp_path):
    path=tmp_path/"concurrent.sqlite3"
    await asyncio.gather(*(asyncio.to_thread(EventRepository(path).snapshots) for _ in range(10)))
