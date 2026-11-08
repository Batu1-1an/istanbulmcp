from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.connectors.biletinial import parse_biletinial_detail
from app.core.events import ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.events import EventService,event_card
from app.services.event_plan import EventPlanService,enumerate_plans,calendar_output
from app.storage.events import EventRepository

FIXTURES=Path(__file__).parent/'fixtures/events'
URL='https://biletinial.com/tr-tr/etkinlik/ornek-giris'


def test_visible_session_date_supplies_year_and_unconfirmed_json_time_is_not_added():
    rows,meta=parse_biletinial_detail((FIXTURES/'biletinial-unconfirmed-time.html').read_text(),URL)
    assert len(rows)==1 and rows[0].source_id=='9101'
    assert rows[0].start_at==datetime(2030,11,14,16,tzinfo=ISTANBUL)
    assert rows[0].end_at==datetime(2030,11,14,16,50,tzinfo=ISTANBUL)
    assert [o.price for o in rows[0].offers]==[750]
    assert rows[0].source_time_conflict
    assert meta['unconfirmed_json_sessions']==1 and not meta['complete']
    assert any('unconfirmed' in w.lower() for w in meta['warnings'])


def test_json_only_different_day_or_venue_remains_available():
    html=(FIXTURES/'biletinial-unconfirmed-time.html').read_text()
    html=html.replace('2030-11-14T19:', '2030-11-15T19:')
    rows,meta=parse_biletinial_detail(html,URL,[datetime(2030,11,14,16,tzinfo=ISTANBUL)])
    assert len(rows)==2 and meta['unconfirmed_json_sessions']==0
    assert any(r.start_at==datetime(2030,11,15,19,tzinfo=ISTANBUL) for r in rows)


def test_flexible_entry_uses_html_identity_and_has_no_public_visit_start():
    rows,meta=parse_biletinial_detail((FIXTURES/'biletinial-flexible-entry.html').read_text(),URL)
    assert len(rows)==2 and meta['complete']
    row=rows[0];card=event_card(row)
    assert row.source_id=='9201' and row.timing_kind=='flexible_entry'
    assert card['start_at'] is None and card['end_at'] is None and not card['end_known']
    assert card['event_date']=='2030-11-08'
    assert card['source_start_at']=='2030-11-08T23:59:00+03:00'
    assert card['start_time_basis']=='html_date'
    assert card['price']['minimum_observed_try']==699 and card['price']['ticket_type']=='15 Dakikalık Bilet'
    assert card['ticket_url']==URL
    assert any('flexible' in w.lower() for w in card['warnings'])


def test_flexible_entry_never_becomes_a_timed_option_or_calendar_event():
    rows,_=parse_biletinial_detail((FIXTURES/'biletinial-flexible-entry.html').read_text(),URL)
    card=event_card(rows[0])
    options,unverified=enumerate_plans([card],window_end=datetime(2030,11,8,23,59,tzinfo=ISTANBUL))
    assert not options and not unverified
    calendar=calendar_output([card])
    assert 'BEGIN:VEVENT' not in calendar['ics'] and not calendar['google_calendar_links']
    assert any('flexible' in w.lower() for w in calendar['warnings'])


@pytest.fixture
def flexible_service(tmp_path):
    clear_source_cache()
    rows,_=parse_biletinial_detail((FIXTURES/'biletinial-flexible-entry.html').read_text(),URL)
    # Only fixture observations: no source network calls.
    rows=[r.model_copy(update={'source':'ticketmaster'}) for r in rows]
    settings=Settings(events_enabled=True,ticketmaster_api_key='fixture-only',database_path=tmp_path/'events.sqlite3')
    repo=EventRepository(settings.database_path);repo.publish('ticketmaster',rows,{})
    yield EventService(settings,repository=repo),rows
    clear_source_cache()


@pytest.mark.asyncio
async def test_date_search_keeps_flexible_entry_but_clock_search_cannot_claim_a_slot(flexible_service):
    service,rows=flexible_service
    normal=await service.search(date_from='2030-11-08',date_to='2030-11-08')
    assert normal['ok'] and len(normal['data'])==1 and normal['data'][0]['start_at'] is None
    clock=await service.search(date_from='2030-11-08',date_to='2030-11-08',time_from='18:00',time_to='23:59')
    assert clock['ok'] and not clock['data']
    assert clock['result_info']['filter_counts']['excluded_unverified_time']==1


@pytest.mark.asyncio
async def test_discovery_plan_returns_flexible_tickets_separately_with_a_repair(flexible_service):
    service,rows=flexible_service
    result=await EventPlanService(service.settings,events=service).plan(date='2030-11-08')
    data=result['data'][0]
    assert not data['options'] and not data['unverified_budget']
    assert len(data['flexible_entries'])==1 and data['flexible_entries'][0]['start_at'] is None
    assert data['rejected'][0]['reason']=='flexible_entry_requires_visit_time'
    assert any('visit time' in w.lower() for w in result['warnings'])


@pytest.mark.asyncio
async def test_selected_flexible_ticket_is_never_silently_scheduled(flexible_service):
    service,rows=flexible_service
    result=await EventPlanService(service.settings,events=service).plan(date='2030-11-08',event_ids=[rows[0].performance_id])
    assert result['ok'] and not result['data'][0]['options']
    assert result['data'][0]['rejected'][0]['reason']=='flexible_entry_requires_visit_time'
    assert len(result['data'][0]['flexible_entries'])==1


def test_json_only_explicit_flexible_rule_is_not_a_scheduled_session():
    html=(FIXTURES/'biletinial-flexible-entry.html').read_text().split('</head>')[0]+'</head><body></body></html>'
    rows,_=parse_biletinial_detail(html,URL)
    assert rows[0].timing_kind=='flexible_entry'
    assert event_card(rows[0])['start_at'] is None


@pytest.mark.asyncio
async def test_today_flexible_date_anchor_is_not_mistaken_for_a_started_session(flexible_service):
    service,rows=flexible_service
    now=datetime.now(ISTANBUL)
    row=rows[0].model_copy(update={'start_at':now.replace(hour=0,minute=0,second=0,microsecond=0),
                                  'source_start_at':now.replace(hour=23,minute=59,second=0,microsecond=0)})
    service.repository.publish('ticketmaster',[row],{})
    result=await service.search(date_from='today',date_to='today')
    assert result['ok'] and len(result['data'])==1
    assert result['data'][0]['start_at'] is None
    assert result['result_info']['filter_counts']['excluded_started']==0


def test_real_midnight_and_flexible_date_anchor_are_not_cross_provider_duplicates():
    from app.services.events import deduplicate
    rows,_=parse_biletinial_detail((FIXTURES/'biletinial-flexible-entry.html').read_text(),URL)
    scheduled=rows[0].model_copy(update={'source':'ticketmaster','source_id':'real-midnight',
                                       'timing_kind':'scheduled','source_start_at':None})
    assert len(deduplicate([rows[0],scheduled]))==2


@pytest.mark.asyncio
async def test_catalogue_only_biletinial_cannot_be_timed_before_detail_verifies_entry_kind(tmp_path):
    from app.core.events import EventObservation,EventVenue
    clear_source_cache()
    row=EventObservation(source='biletinial',source_id='provisional',series_key='provisional',title='Örnek giriş',
                         start_at=datetime(2030,11,8,23,59,tzinfo=ISTANBUL),venue=EventVenue(name='Unknown venue'),
                         observed_at=datetime.now(ISTANBUL),detail_checked=False)
    settings=Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/'cold.sqlite3')
    repo=EventRepository(settings.database_path);repo.publish('biletinial',[row],{})
    service=EventService(settings,repository=repo)
    result=await EventPlanService(settings,events=service).plan(date='2030-11-08')
    assert not result['data'][0]['options']
    assert result['data'][0]['rejected'][0]['reason']=='session_detail_required'
    assert any('istanbul_event_detail' in w for w in result['warnings'])
    card=event_card(row)
    assert not enumerate_plans([card],window_end=row.start_at)[0]
    assert 'BEGIN:VEVENT' not in calendar_output([card])['ics']
    clear_source_cache()
