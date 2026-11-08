"""Independent filter combinations, offer semantics and concurrency checks."""
import asyncio
from datetime import datetime, timedelta, timezone
from itertools import product

import pytest

from app.core.events import EventObservation, EventVenue, EventOffer, ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.connectors.ticketmaster import TicketmasterClient
from app.services.events import EventService, event_card
from app.services.event_plan import EventPlanService
from app.storage.events import EventRepository


@pytest.fixture(scope="module")
def catalogue(tmp_path_factory):
    path = tmp_path_factory.mktemp("cross-checks") / "events.sqlite3"
    settings = Settings(events_enabled=True, ticketmaster_api_key="fixture-only", database_path=path)
    rows = []
    # Fixed independent coordinates: one at the origin and one several km away.
    for i, (category, price, district, hour) in enumerate(product(
        ("family", "theatre", "concert"), (0, 100, None), ("Kadıköy", "Beşiktaş"), (10, 18))):
        rows.append(EventObservation(source="ticketmaster", source_id=str(i), series_key=str(i),
            title=f"Gösteri {i}", category=category, age_limit="3-10" if category=="family" else None,
            start_at=datetime(2030, 11, 8, hour, tzinfo=ISTANBUL),
            end_at=datetime(2030, 11, 8, hour+1, tzinfo=ISTANBUL),
            venue=EventVenue(name=district+" Sahne", district=district, lat=40.99 if district=="Kadıköy" else 41.04,
                             lon=29.03 if district=="Kadıköy" else 29.00),
            offers=[] if price is None else [EventOffer(price=price, currency="TRY", availability="in_stock")],
            observed_at=datetime.now(timezone.utc), ticket_url="https://www.biletix.com/performance/ABC12/001/TURKIYE/tr"))
    repo = EventRepository(path); repo.publish("ticketmaster", rows, {"accepted":len(rows)})
    return EventService(settings, repository=repo), rows


@pytest.mark.asyncio
@pytest.mark.parametrize("category,budget,district,evening,near", list(product(
    (None,"family","concert"), (None,0,100), (None,"Kadıköy"), (False,True), (False,True))))
async def test_combined_filters_agree_with_independent_fixture_oracle(catalogue, category, budget, district, evening, near):
    events, rows = catalogue
    args={"date_from":"2030-11-08","date_to":"2030-11-08","limit":50,
          "category":category,"max_price_try":budget,"include_unknown_prices":False}
    if district: args["district"]=district
    if evening: args["time_from"]="17:00"
    if near: args.update(lat=40.99,lon=29.03,radius_m=100)
    expected=[]
    for row in rows:
        price=row.offers[0].price if row.offers else None
        if price is None or budget is not None and price>budget:continue
        if category and row.category!=category:continue
        if district and row.venue.district!=district:continue
        if evening and row.start_at.hour<17:continue
        if near and row.venue.district!="Kadıköy":continue
        expected.append(row.performance_id)
    result=await events.search(**args)
    assert result["ok"]
    assert {card["performance_id"] for card in result["data"]}==set(expected)
    assert result["result_info"]["matched"]==len(expected)


@pytest.mark.asyncio
async def test_small_limit_is_a_prefix_and_narrow_radius_a_subset(catalogue):
    events,_=catalogue
    args={"date_from":"2030-11-08","date_to":"2030-11-08"}
    small=await events.search(**args,limit=5)
    big=await events.search(**args,limit=50)
    assert small["data"]==big["data"][:5] and small["result_info"]["truncated"]
    near=await events.search(**args,limit=50,lat=40.99,lon=29.03,radius_m=100)
    far=await events.search(**args,limit=50,lat=40.99,lon=29.03,radius_m=20000)
    assert {x["performance_id"] for x in near["data"]} < {x["performance_id"] for x in far["data"]}


def test_sold_out_offer_cannot_supply_the_ticket_type_for_an_available_equal_price(catalogue):
    _,rows=catalogue
    row=rows[0].model_copy(update={"offers":[
        EventOffer(name="Öğrenci",price=100,currency="TRY",availability="sold_out"),
        EventOffer(name="Tam",price=100,currency="TRY",availability="in_stock")]})
    card=event_card(row)
    assert card["price"]["ticket_type"]=="Tam"
    assert card["price"]["eligibility_may_apply"] is False


@pytest.mark.asyncio
async def test_concurrent_refreshes_share_one_source_download(catalogue, monkeypatch):
    events,rows=catalogue
    clear_source_cache()
    calls=[]
    async def fetch(self):
        calls.append(True)
        await asyncio.sleep(0.02)
        return rows,{"accepted":len(rows)}
    monkeypatch.setattr(TicketmasterClient,"catalogue",fetch)
    # A fresh DB snapshot can be reused, so force its age beyond the source TTL.
    from app.storage.db import connect
    with connect(events.settings.database_path) as conn:
        conn.execute("UPDATE event_source_snapshots SET refreshed_at=?",((datetime.now(timezone.utc)-timedelta(hours=2)).isoformat(),))
    try:
        await asyncio.gather(*(events.refresh_source("ticketmaster") for _ in range(12)))
        assert len(calls)==1
    finally:
        clear_source_cache()


@pytest.mark.asyncio
async def test_planning_budgets_and_windows_hold_across_category_combinations(catalogue):
    events,_=catalogue
    planner=EventPlanService(events.settings,events=events)
    for interests,budget,strict_end in product((["family"],["theatre","concert"]),(0,100,200),(False,True)):
        result=await planner.plan(date="2030-11-08",start_time="09:00",end_time="20:00",
            interests=interests,max_price_try=budget,require_known_end=strict_end)
        assert result["ok"]
        for option in result["data"][0]["options"]:
            assert option["total_price_known"] and option["total_observed_minimum_try"]<=budget
            assert all(card["category"] in interests for card in option["performances"])
            assert all(card["end_at"][:16] <= "2030-11-08T20:00" for card in option["performances"])


@pytest.mark.asyncio
async def test_utc_late_evening_belongs_to_the_next_istanbul_day(catalogue,tmp_path):
    _,rows=catalogue
    settings=Settings(events_enabled=True,ticketmaster_api_key="fixture-only",database_path=tmp_path/"timezone.sqlite3")
    data=rows[0].model_dump()
    data.update(start_at=datetime(2030,11,7,21,30,tzinfo=timezone.utc),
                end_at=datetime(2030,11,7,22,30,tzinfo=timezone.utc))
    row=EventObservation.model_validate(data)
    repo=EventRepository(settings.database_path);repo.publish("ticketmaster",[row],{})
    events=EventService(settings,repository=repo)
    prior=await events.search(date_from="2030-11-07",date_to="2030-11-07")
    next_day=await events.search(date_from="2030-11-08",date_to="2030-11-08",time_to="01:00")
    assert not prior["data"] and len(next_day["data"])==1
    assert next_day["data"][0]["start_at"]=="2030-11-08T00:30:00+03:00"
    planned=await EventPlanService(settings,events=events).plan(date="2030-11-08",start_time="00:00",
        end_time="02:00",require_known_end=True,event_ids=[row.performance_id])
    ics=planned["data"][0]["options"][0]["calendar"]["ics"]
    assert "DTSTART:20301107T213000Z" in ics


@pytest.mark.asyncio
@pytest.mark.parametrize("date,valid",[("2028-02-29",True),("2026-02-29",False),("2030-04-31",False)])
async def test_calendar_boundary_dates(catalogue,date,valid):
    events,_=catalogue
    result=await events.search(date_from=date,date_to=date)
    assert result["ok"] is valid
    if not valid:assert result["error"]["code"]=="validation_error"


@pytest.mark.asyncio
@pytest.mark.parametrize("age,expected",[(0,False),(3,True),(10,True),(11,False),(17,False)])
async def test_child_age_range_includes_only_its_published_endpoints(catalogue,age,expected):
    events,_=catalogue
    result=await events.search(date_from="2030-11-08",date_to="2030-11-08",child_age=age,limit=50)
    assert bool(result["data"]) is expected


def test_foreign_currency_offer_does_not_set_try_minimum(catalogue):
    _,rows=catalogue
    row=rows[0].model_copy(update={"offers":[EventOffer(price=1,currency="EUR",name="Yabancı"),
        EventOffer(price=200,currency="TRY",name="Tam",availability="in_stock")]})
    card=event_card(row)
    assert card["price"]["minimum_observed_try"]==200 and card["price"]["ticket_type"]=="Tam"
