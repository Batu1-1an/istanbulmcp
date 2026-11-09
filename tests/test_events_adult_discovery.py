"""Adult discovery must filter known child-only ranges before the plan candidate cap."""
from datetime import datetime,timedelta
import pytest
from app.core.events import EventObservation,EventVenue,EventOffer,ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.storage.events import EventRepository
from app.services.events import EventService
from app.services.event_plan import EventPlanService


@pytest.fixture
def audience_events(tmp_path):
    clear_source_cache()
    settings=Settings(events_enabled=True,ticketmaster_api_key='fixture-only',database_path=tmp_path/'events.sqlite3')
    repo=EventRepository(settings.database_path)
    def row(identity,age,hour=12):
        start=datetime(2030,11,10,hour,tzinfo=ISTANBUL)
        return EventObservation(source='ticketmaster',source_id=identity,series_key=identity,title=identity,
            category='workshop',start_at=start,end_at=start+timedelta(hours=1),age_limit=age,
            venue=EventVenue(name='Sahne'),observed_at=datetime.now(ISTANBUL),
            offers=[EventOffer(price=100,currency='TRY')])
    rows=[row('child','6-9'),row('teen','7-17'),row('adult','18+'),row('open','6+'),row('unknown',None)]
    repo.publish('ticketmaster',rows,{})
    yield EventService(settings,repository=repo),row,rows
    clear_source_cache()


@pytest.mark.asyncio
async def test_adult_discovery_excludes_only_explicit_child_only_ranges(audience_events):
    events,_,_=audience_events
    result=await events.search(date_from='2030-11-10',date_to='2030-11-10',exclude_child_only=True)
    assert {c['title'] for c in result['data']}=={'adult','open','unknown'}
    assert result['result_info']['filter_counts']['excluded_child_only']==2
    assert any('not verified' in w.lower() for w in result['warnings'])


@pytest.mark.asyncio
async def test_default_discovery_keeps_the_published_behavior(audience_events):
    events,_,_=audience_events
    result=await events.search(date_from='2030-11-10',date_to='2030-11-10')
    assert len(result['data'])==5


@pytest.mark.asyncio
async def test_selected_child_only_session_has_explicit_rejection(audience_events):
    events,_,rows=audience_events
    plan=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',event_ids=[rows[0].performance_id],exclude_child_only=True)
    assert plan['ok'] and not plan['data'][0]['options']
    assert plan['data'][0]['rejected']==[{'performance_id':rows[0].performance_id,'reason':'child_only_age_range'}]


@pytest.mark.asyncio
async def test_child_only_rows_cannot_fill_the_twenty_candidate_plan_pool(audience_events):
    events,row,_=audience_events
    rows=[row(f'child-{i}','4-7') for i in range(25)]+[row('adult-evening','18+',18)]
    events.repository.publish('ticketmaster',rows,{})
    result=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='22:00',exclude_child_only=True,max_events=1)
    assert result['ok'] and result['data'][0]['candidate_count']==1
    assert result['data'][0]['evaluated_candidates']==1
    assert result['data'][0]['options'][0]['performances'][0]['title']=='adult-evening'
