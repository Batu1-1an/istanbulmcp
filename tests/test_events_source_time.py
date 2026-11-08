"""Source disagreement must not become an extra midnight session or a false plan."""
from datetime import datetime
from pathlib import Path

import pytest

from app.connectors.biletinial import parse_biletinial_detail
from app.core.events import ISTANBUL
from app.services.events import event_card
from app.services.event_plan import enumerate_plans
from app.connectors.events_http import EventSourceError
from app.core.settings import Settings
from app.services.events import EventService
from app.services.event_plan import EventPlanService
from app.storage.events import EventRepository

FIXTURE=Path(__file__).parent/'fixtures/events/biletinial-time-conflict.html'
URL='https://biletinial.com/tr-tr/etkinlik/ornek-ziyaret'
START=datetime(2030,11,8,21,15,tzinfo=ISTANBUL)


def test_html_time_wins_over_conflicting_json_offset_without_extra_midnight_session():
    rows,meta=parse_biletinial_detail(FIXTURE.read_text(),URL,[START])
    assert len(rows)==1
    row=rows[0]
    assert row.source_id=='9001' and row.start_at==START
    assert row.end_at is None  # The conflicting JSON end must not create a four-hour visit.
    assert row.start_time_basis=='html_session'
    assert row.source_time_conflict
    assert [o.price for o in row.offers]==[659,709]
    assert any('conflict' in w.lower() for w in row.warnings)
    assert meta['time_conflicts']==1
    card=event_card(row)
    assert card['source_time_conflict'] and card['start_time_basis']=='html_session'
    assert any('conflict' in w.lower() for w in card['warnings'])
    options,_=enumerate_plans([card],window_end=datetime(2030,11,8,23,59,tzinfo=ISTANBUL))
    assert options and options[0]['performances'][0]['start_at']==START.isoformat()
    assert any('conflict' in w.lower() for w in options[0]['warnings'])
    assert 'DTSTART:20301108T181500Z' in options[0]['calendar']['ics']


def test_conflicting_json_can_supply_year_but_never_an_invented_extra_session():
    rows,_=parse_biletinial_detail(FIXTURE.read_text(),URL)
    assert len(rows)==1 and rows[0].start_at==START
    assert rows[0].source_id=='9001'


def test_legitimate_utc_conversion_keeps_published_next_day_midnight_session():
    html=FIXTURE.read_text().replace('08 Kasım Cuma','09 Kasım Cumartesi').replace('class="tm">21:15','class="tm">00:15')
    rows,meta=parse_biletinial_detail(html,URL)
    assert len(rows)==1
    assert rows[0].start_at==datetime(2030,11,9,0,15,tzinfo=ISTANBUL)
    assert rows[0].end_at==datetime(2030,11,9,1,15,tzinfo=ISTANBUL)
    assert not rows[0].source_time_conflict
    assert meta['time_conflicts']==0


def test_exact_json_instant_does_not_get_reassigned_to_other_html_wall_clock():
    extra='<div id="seans-9002"><span class="d">09 Kasım Cumartesi</span><span class="tm">00:15</span><div class="vl"><a href="/tr-tr/mekan/ornek-akvaryum">Örnek Akvaryum</a> · İstanbul Anadolu</div></div>'
    html=FIXTURE.read_text().replace('</body>',extra+'</body>')
    rows,meta=parse_biletinial_detail(html,URL,[START])
    assert len(rows)==2
    assert {r.source_id for r in rows}=={'9001','9002'}
    assert not any(r.source_time_conflict for r in rows)
    assert meta['time_conflicts']==0


def test_json_only_utc_session_still_uses_real_instant():
    html=FIXTURE.read_text().split('</head>')[0]+'</head><body></body></html>'
    rows,meta=parse_biletinial_detail(html,URL)
    assert len(rows)==1 and rows[0].start_at==datetime(2030,11,9,0,15,tzinfo=ISTANBUL)
    assert rows[0].start_time_basis=='json_ld'
    assert not rows[0].source_time_conflict


def test_other_venue_wall_clock_cannot_reinterpret_a_json_instant():
    html=FIXTURE.read_text().replace('>Örnek Akvaryum</a>','>Başka Sahne</a>')
    rows,meta=parse_biletinial_detail(html,URL)
    assert len(rows)==1 and rows[0].start_time_basis=='json_ld'
    assert rows[0].start_at==datetime(2030,11,9,0,15,tzinfo=ISTANBUL)
    assert not rows[0].source_time_conflict


def test_ambiguous_source_years_do_not_leak_conflicting_json_fallback():
    with pytest.raises(EventSourceError,match='no verified Istanbul sessions'):
        parse_biletinial_detail(FIXTURE.read_text(),URL,[START,START.replace(year=2031)])


@pytest.mark.asyncio
async def test_refreshed_session_retires_phantom_and_preserves_warnings_in_search_and_plan(tmp_path,monkeypatch):
    from app.core.source_cache import clear_source_cache
    clear_source_cache()
    rows,meta=parse_biletinial_detail(FIXTURE.read_text(),URL,[START])
    fixed=rows[0]
    phantom=fixed.model_copy(update={'source_id':'json:2030-11-09T00:15:00+03:00:Örnek Akvaryum',
                                   'start_at':datetime(2030,11,9,0,15,tzinfo=ISTANBUL)})
    settings=Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/'events.sqlite3')
    repo=EventRepository(settings.database_path)
    repo.publish('biletinial',[fixed,phantom],{})
    service=EventService(settings,repository=repo)
    async def detail(*args,**kwargs):
        return rows,meta
    monkeypatch.setattr('app.services.events.BiletinialClient.detail',detail)
    result=await service.detail(fixed.event_id)
    assert len(result['data'][0]['performances'])==1
    result=await service.search(date_from='2030-11-08',date_to='2030-11-09')
    assert len(result['data'])==1 and result['data'][0]['start_at']==START.isoformat()
    assert any('Source time conflict' in w for w in result['warnings'])
    assert any('eligibility' in w for w in result['warnings'])
    planner=EventPlanService(settings,events=service)
    plan=await planner.plan(date='2030-11-08',event_ids=[fixed.performance_id])
    option=plan['data'][0]['options'][0]
    assert option['performances'][0]['performance_id']==fixed.performance_id
    assert any('Source time conflict' in w for w in option['warnings'])
    assert any('eligibility' in w for w in option['warnings'])
    stale=await planner.plan(date='2030-11-09',start_time='00:00',end_time='23:59',event_ids=[phantom.performance_id])
    assert not stale['ok'] and stale['error']['code']=='selection_changed'
    clear_source_cache()
