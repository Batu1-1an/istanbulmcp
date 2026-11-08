from datetime import datetime,timedelta
from pathlib import Path
import pytest
from app.connectors.biletinial import parse_biletinial_detail
from app.core.events import EventObservation,EventVenue,EventOffer,ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.storage.events import EventRepository
from app.services.events import EventService,event_card
from app.services.event_plan import EventPlanService,enumerate_plans,calendar_output
FIXTURES=Path(__file__).parent/'fixtures/events'
URL='https://biletinial.com/tr-tr/etkinlik/ornek-giris'


def test_admission_range_is_flexible_and_last_entry_is_not_a_visit_start():
    rows,_=parse_biletinial_detail((FIXTURES/'biletinial-admission-window.html').read_text(),URL)
    assert len(rows)==1 and rows[0].source_id=='9301'
    card=event_card(rows[0])
    assert card['timing_kind']=='flexible_entry' and card['start_at'] is None
    assert card['admission_window']['opens_at']=='11:00'
    assert card['admission_window']['last_entry_at']=='19:00'
    assert card['admission_window']['closes_at']=='20:00'
    assert not enumerate_plans([card],window_end=datetime(2030,11,10,23,59,tzinfo=ISTANBUL))[0]
    assert 'BEGIN:VEVENT' not in calendar_output([card])['ics']


def restricted_rows():
    html=(FIXTURES/'biletinial-flexible-entry.html').read_text().replace('Biletler ilgili tarihteki istenilen saatte kullanılabilir.', 'Biletler ilgili tarihteki istenilen saatte kullanılabilir. Biletler pazar günleri geçerli değildir.')
    rows,_=parse_biletinial_detail(html,URL)
    return [r.model_copy(update={'start_at':datetime(2030,11,10,0,tzinfo=ISTANBUL),
                                 'source_start_at':datetime(2030,11,10,23,59,tzinfo=ISTANBUL)}) for r in rows[:1]]


def test_explicit_weekday_exclusion_is_preserved_in_detail_card():
    row=restricted_rows()[0];card=event_card(row)
    assert row.excluded_weekdays==[6]
    assert card['excluded_weekdays']==[6] and card['entry_date_restricted']
    assert any('weekday' in w.lower() for w in card['warnings'])


@pytest.mark.asyncio
async def test_restricted_date_is_not_discovered_or_kept_as_a_plan_alternative(tmp_path):
    clear_source_cache();rows=[r.model_copy(update={'source':'ticketmaster'}) for r in restricted_rows()]
    settings=Settings(events_enabled=True,ticketmaster_api_key='fixture-only',database_path=tmp_path/'events.sqlite3')
    repo=EventRepository(settings.database_path);repo.publish('ticketmaster',rows,{})
    events=EventService(settings,repository=repo)
    result=await events.search(date_from='2030-11-10',date_to='2030-11-10',include_sold_out=True,include_past=True)
    assert result['ok'] and not result['data']
    assert result['result_info']['filter_counts']['excluded_entry_date']==1
    detail=await events.detail(rows[0].performance_id)
    assert detail['ok'] and detail['data'][0]['performances'][0]['entry_date_restricted']
    plan=await EventPlanService(settings,events=events).plan(date='2030-11-10',event_ids=[rows[0].performance_id])
    assert not plan['data'][0]['options'] and not plan['data'][0]['flexible_entries']
    assert plan['data'][0]['rejected'][0]['reason']=='entry_date_restricted'
    assert 'BEGIN:VEVENT' not in calendar_output([event_card(rows[0])])['ics']
    clear_source_cache()


def age_cards(ages):
    out=[]
    for i,age in enumerate(ages):
        start=datetime(2030,11,10,10+i*3,tzinfo=ISTANBUL)
        row=EventObservation(source='ticketmaster',source_id=str(i),series_key=str(i),title=str(i),
                             start_at=start,end_at=start+timedelta(hours=1),age_limit=age,
                             venue=EventVenue(name='Sahne'),observed_at=datetime.now(ISTANBUL),
                             offers=[EventOffer(price=100,currency='TRY')])
        out.append(event_card(row))
    return out


def test_mutually_exclusive_age_ranges_never_share_one_option():
    cards=age_cards(['6-9','4-7','12+']);diagnostics={}
    options,_=enumerate_plans(cards,window_end=datetime(2030,11,10,23,59,tzinfo=ISTANBUL),limit=5,diagnostics=diagnostics)
    assert options and not any(len(o['performances'])==3 for o in options)
    pair=next(o for o in options if len(o['performances'])==2)
    assert pair['checks']['common_published_age_range']=={'minimum':6,'maximum':7}
    assert diagnostics['age_incompatible_combinations']>=3


def test_unknown_age_does_not_hide_incompatible_known_ranges():
    cards=age_cards(['6-9',None,'12+'])
    options,_=enumerate_plans(cards,window_end=datetime(2030,11,10,23,59,tzinfo=ISTANBUL),limit=20)
    assert not any({'0','2'} <= {c['title'] for c in o['performances']} for o in options)
    assert any(o['checks']['age_compatibility']=='partially_known' for o in options)


def test_unknown_ages_are_not_claimed_verified_or_assigned_an_invented_age():
    options,_=enumerate_plans(age_cards([None,None]),window_end=datetime(2030,11,10,23,59,tzinfo=ISTANBUL))
    assert options
    assert all(o['checks']['age_compatibility']=='unknown' and o['checks']['common_published_age_range'] is None for o in options)


@pytest.mark.parametrize('rule,expected',[
    ('Biletler pazartesi günleri geçerli değildir.',[0]),
    ('Biletler pazar günleri geçerlidir.',[]),
    ('Öğrenci biletleri pazar günleri geçerli değildir.',[]),
])
def test_only_explicit_general_weekday_exclusion_is_applied(rule,expected):
    from app.connectors.biletinial import _excluded_weekdays
    assert _excluded_weekdays(rule)==expected


def test_unknown_closing_time_is_not_invented_from_last_admission():
    html=(FIXTURES/'biletinial-admission-window.html').read_text().replace('Sergi kapanış saati: 20:00.','')
    rows,_=parse_biletinial_detail(html,URL)
    card=event_card(rows[0]);assert card['admission_window']['last_entry_at']=='19:00'
    assert card['admission_window']['closes_at'] is None
    assert card['end_at'] is None


def test_open_ended_age_ranges_keep_an_unbounded_maximum():
    options,_=enumerate_plans(age_cards(['12+','18+']),window_end=datetime(2030,11,10,23,59,tzinfo=ISTANBUL))
    both=next(o for o in options if len(o['performances'])==2)
    assert both['checks']['common_published_age_range']=={'minimum':18,'maximum':None}


def test_opening_hours_are_read_from_description_but_not_unrelated_footer():
    html=(FIXTURES/'biletinial-admission-window.html').read_text()
    html=html.replace('Her gün 11:00\'de açılış. Son ziyaretçi girişi: 19:00. Sergi kapanış saati: 20:00.','Örnek sergi açıklaması.')
    rows,_=parse_biletinial_detail(html,URL)
    assert event_card(rows[0])['admission_window']['closes_at']=='20:00'
    scheduled=(FIXTURES/'biletinial-detail.html').read_text()+'<footer>11:00 - 19:00 saatleri arasında katılım sağlayabilirsiniz.</footer>'
    rows,_=parse_biletinial_detail(scheduled,'https://biletinial.com/tr-tr/tiyatro/ornek-oyun')
    assert all(r.timing_kind=='scheduled' and r.admission_window is None for r in rows)


@pytest.mark.asyncio
async def test_named_search_checks_cold_catalogue_admission_rules_before_recommending(tmp_path,monkeypatch):
    clear_source_cache()
    row=restricted_rows()[0]
    provisional=row.model_copy(update={'detail_checked':False,'timing_kind':'scheduled',
        'start_at':datetime(2030,11,10,23,59,tzinfo=ISTANBUL),'excluded_weekdays':[],
        'offers':[],'venue':EventVenue(name='Unknown venue')})
    settings=Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/'cold.sqlite3')
    repo=EventRepository(settings.database_path);repo.publish('biletinial',[provisional],{})
    events=EventService(settings,repository=repo);calls=[]
    async def detail(identifier):
        calls.append(identifier)
        repo.publish('biletinial',[row],{},series_key=row.series_key)
        return {'ok':True}
    monkeypatch.setattr(events,'detail',detail)
    result=await events.search(query=row.title,date_from='2030-11-10',date_to='2030-11-10')
    assert calls==[row.event_id]
    assert result['ok'] and not result['data']
    assert result['result_info']['filter_counts']['excluded_entry_date']==1
    assert result['result_info']['filter_counts']['detail_checks_succeeded']==1
    clear_source_cache()
