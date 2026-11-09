from datetime import datetime,timedelta
from pathlib import Path
import pytest
from app.core.events import EventOffer,EventObservation,EventVenue,ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.event_pricing import ticket_quote,party_quote
from app.services.events import EventService,event_card
from app.services.event_plan import EventPlanService
from app.storage.events import EventRepository
from app.connectors.biletinial import parse_biletinial_list,parse_biletinial_detail


def offer(name,price,**kw):return EventOffer(name=name,price=price,currency='TRY',**kw)


def test_general_group_uses_package_quantities_not_student_minimum_times_people():
    q=ticket_quote([offer('Öğrenci',50),offer('Tam',400),offer('Çift Kişilik Bilet',600)],6,'general')
    assert q['observed_ticket_subtotal_try']==1800
    assert q['basket'][0]['quantity']==3 and q['admissions_purchased']==6
    assert q['checkout_total_try'] is None and not q['checkout_total_verified']
    assert not q['quantity_available_verified']


def test_mixed_party_uses_matching_ticket_types_and_keeps_fees_unknown():
    q=party_quote([offer('Tam',400),offer('Çocuk',150),offer('Öğrenci',20)],{'general':1,'child':1})
    assert q['observed_ticket_subtotal_try']==550
    assert q['fees_status']=='unknown' and q['observed_fee_inclusive_total_try'] is None


def test_unknown_ticket_unit_does_not_become_a_general_per_person_price():
    assert ticket_quote([offer('Standard',100),offer('1. Kategori',200)],2)['observed_ticket_subtotal_try'] is None


def test_sold_out_cheap_package_is_not_used_in_group_basket():
    q=ticket_quote([offer('Çift Kişilik Bilet',10,availability='sold_out'),offer('Tam',200)],2)
    assert q['observed_ticket_subtotal_try']==400


def test_fees_inclusive_observation_still_does_not_claim_live_checkout_or_seats():
    q=ticket_quote([offer('Tam',100,fees_included=True)],2)
    assert q['fees_status']=='included_in_observed_price'
    assert not q['checkout_total_verified'] and not q['adjacent_seats_verified']


@pytest.fixture
def catalogue(tmp_path):
    clear_source_cache()
    settings=Settings(events_enabled=True,ticketmaster_api_key='fixture-only',database_path=tmp_path/'e.sqlite3')
    repo=EventRepository(settings.database_path)
    def row(name,hour=12,**updates):
        start=datetime(2030,11,10,hour,tzinfo=ISTANBUL)
        return EventObservation(source='ticketmaster',source_id=name,series_key=name,title=name,
            category='theatre',start_at=start,end_at=start+timedelta(hours=1),
            venue=EventVenue(name='Sahne',district='Kadıköy'),observed_at=datetime.now(ISTANBUL),
            offers=[offer('Tam',200)],**updates)
    yield EventService(settings,repository=repo),row
    clear_source_cache()


@pytest.mark.asyncio
async def test_group_budget_uses_full_party_subtotal_and_preserves_ticket_minimum(catalogue):
    events,row=catalogue
    sample=row('one');sample.offers=[offer('Öğrenci',10),offer('Tam',200)]
    events.repository.publish('ticketmaster',[sample],{})
    result=await events.search(date_from='2030-11-10',date_to='2030-11-10',party_size=2,max_price_try=300,include_unknown_prices=False)
    assert result['ok'] and not result['data']
    result=await events.search(date_from='2030-11-10',date_to='2030-11-10',party_size=2,max_price_try=400,include_unknown_prices=False)
    c=result['data'][0];assert c['price']['minimum_observed_try']==10
    assert c['price_quote']['observed_ticket_subtotal_try']==400


@pytest.mark.asyncio
async def test_unknown_and_actual_outside_district_are_separate(catalogue):
    events,row=catalogue
    a,b=row('unknown'),row('outside');a.venue=EventVenue(name='Unknown venue');b.venue=EventVenue(name='Başka',district='Beşiktaş')
    events.repository.publish('ticketmaster',[a,b],{})
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',district='Kadıköy')
    counts=p['result_info']['filter_counts']
    assert counts['excluded_unknown_location']==1 and counts['excluded_outside_location']==1
    assert 'location_unverified' in p['result_info']['empty_reasons']


@pytest.mark.asyncio
async def test_minimum_two_stops_keeps_one_stop_out_of_complete_options(catalogue):
    events,row=catalogue;events.repository.publish('ticketmaster',[row('only')],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',min_events=2,max_events=2)
    d=p['data'][0];assert not d['options'] and d['partial_options']
    assert d['partial_options'][0]['fulfillment']['missing_events']==1
    assert d['fulfillment']['status']=='partial'


@pytest.mark.asyncio
async def test_required_categories_cannot_be_fulfilled_by_two_of_the_same_type(catalogue):
    events,row=catalogue;events.repository.publish('ticketmaster',[row('one',12),row('two',16)],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',min_events=2,max_events=2,required_categories=['theatre','concert'])
    d=p['data'][0];assert not d['options']
    assert any('concert' in o['fulfillment']['missing_categories'] for o in d['partial_options'])


def test_condition_sections_are_published_with_provenance_and_footer_is_ignored():
    original=(Path('tests/fixtures/events')/'biletinial-detail.html').read_text()
    html=original+'''<div class="event-rules-v2__content"><ul>
      <li>Oyun İngilizce sahnelenecektir; Türkçe üstyazı vardır.</li>
      <li>Tekerlekli sandalye girişi için rezervasyon gereklidir.</li>
      <li>Bilet iadesi yapılmaz; iptal halinde kaynakla iletişime geçiniz.</li>
      <li>Atölye malzemeleri fiyata dahildir.</li></ul></div>
      <footer>Ücretsiz sertifika verilir. Fotoğraf çekimi serbesttir.</footer>'''
    rows,_=parse_biletinial_detail(html,'https://biletinial.com/tr-tr/tiyatro/ornek-oyun')
    c=event_card(rows[0]);p=c['participation_conditions'];topics={x['topic'] for x in p['statements']}
    assert {'language','accessibility','reservation','refund_exchange','materials'}<=topics
    assert 'certificate' not in topics and 'photography' not in topics
    assert all(x['source_section']=='rules' for x in p['statements'])
    assert not p['personal_eligibility_verified']


def test_catalogue_venue_hint_is_not_assigned_as_session_venue():
    import json
    rows,_=parse_biletinial_list(json.loads(Path('tests/fixtures/events/biletinial-list.json').read_text()),'tiyatro')
    assert rows[0].catalogue_venue_hint=='Örnek Sahne'
    assert rows[0].venue.name=='Unknown venue' and not rows[0].detail_checked


def test_verified_venue_reuse_has_evidence_and_conflicts_remain_unknown(catalogue):
    from app.services.event_locations import enrich_verified_venues
    _,row=catalogue
    a,b=row('known'),row('missing')
    a.detail_checked=b.detail_checked=True
    a.ticket_url='https://biletinial.com/tr-tr/tiyatro/known'
    b.venue=b.venue.model_copy(update={'district':None})
    merged,n=enrich_verified_venues([a,b])
    assert n and merged[1].venue.district=='Kadıköy'
    assert merged[1].venue.field_evidence['district']['source_url']==a.ticket_url
    conflict=row('conflict');conflict.detail_checked=True;conflict.venue=conflict.venue.model_copy(update={'district':'Beşiktaş'})
    merged,n=enrich_verified_venues([a,b,conflict]);assert merged[1].venue.district is None


@pytest.mark.asyncio
async def test_named_venue_hint_is_checked_before_unrelated_cold_catalogue(tmp_path,monkeypatch):
    settings=Settings(events_enabled=True,events_biletinial_enabled=True,database_path=tmp_path/'cold.sqlite3')
    repo=EventRepository(settings.database_path);now=datetime.now(ISTANBUL)
    def row(i,hint):
        return EventObservation(source='biletinial',source_id=str(i),series_key=str(i),title=str(i),category='theatre',
            start_at=datetime(2030,11,10,18,tzinfo=ISTANBUL),venue=EventVenue(name='Unknown venue'),catalogue_venue_hint=hint,observed_at=now)
    rows=[row(i,'Başka') for i in range(4)]+[row(9,'Zorlu PSM')]
    repo.publish('biletinial',rows,{});events=EventService(settings,repository=repo);checks=[]
    async def detail(identifier):
        checks.append(identifier);r=next(r for r in rows if r.event_id==identifier)
        verified=r.model_copy(update={'detail_checked':True,'venue':EventVenue(name=r.catalogue_venue_hint,district='Beşiktaş')})
        repo.publish('biletinial',[verified],{},series_key=r.series_key)
        return {'ok':True}
    monkeypatch.setattr(events,'detail',detail)
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',venue='Zorlu')
    assert checks[0]==rows[-1].event_id and len(checks)<=3
    assert len(p['data'])==1 and p['data'][0]['venue']['name']=='Zorlu PSM'


@pytest.mark.asyncio
async def test_unknown_coordinates_and_verified_outside_radius_are_distinguished(catalogue):
    events,row=catalogue
    a,b=row('unknown'),row('outside');a.venue=EventVenue(name='Unknown venue');b.venue=EventVenue(name='Uzak',lat=41.2,lon=29.1)
    events.repository.publish('ticketmaster',[a,b],{})
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',lat=40.99,lon=29.02,radius_m=1000)
    counts=p['result_info']['filter_counts'];assert counts['excluded_unknown_location']==1 and counts['excluded_outside_location']==1


@pytest.mark.asyncio
async def test_fee_inclusive_budget_cannot_be_verified_from_unknown_fees(catalogue):
    events,row=catalogue;events.repository.publish('ticketmaster',[row('one')],{})
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',party_size=2,max_price_try=500,include_unknown_prices=False,budget_includes_fees=True)
    assert not p['data'] and p['result_info']['filter_counts']['excluded_unknown_fees']==1


@pytest.mark.asyncio
async def test_selected_group_plan_uses_matching_ticket_basket(catalogue):
    events,row=catalogue;r=row('one');r.offers=[offer('Öğrenci',1),offer('Tam',200)];events.repository.publish('ticketmaster',[r],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',event_ids=[r.performance_id],party_size=2,max_price_try=300)
    assert not p['data'][0]['options']


@pytest.mark.parametrize('count',[0,51,True])
@pytest.mark.asyncio
async def test_invalid_party_count_returns_validation_before_source_access(catalogue,count):
    events,_=catalogue
    p=await events.search(party_size=count)
    assert not p['ok'] and p['error']['code']=='validation_error'


def test_one_general_pair_package_can_cover_a_mixed_group_without_double_charging():
    q=party_quote([offer('Tam',400),offer('Öğrenci',200),offer('Çift Kişilik Bilet',250)],{'general':1,'student':1})
    assert q['observed_ticket_subtotal_try']==250
    assert q['basket'][0]['quantity']==1 and q['admissions_purchased']==2


def test_student_can_use_cheaper_unrestricted_ticket_without_claiming_discount():
    q=ticket_quote([offer('Tam',100),offer('Öğrenci',200)],1,'student')
    assert q['observed_ticket_subtotal_try']==100 and q['basket'][0]['profile']=='general'


@pytest.mark.parametrize('rule,expected',[
 ('Bilet fiyatlarına hizmet bedeli dahildir.',True),
 ('Bilet fiyatlarına hizmet bedeli dahil değildir.',False),
 ('Öğrenci bilet fiyatlarına hizmet bedeli dahildir.',None),
])
def test_fee_scope_is_only_derived_from_unambiguous_general_source_rule(rule,expected):
    from app.connectors.event_conditions import parse_event_conditions,published_fees_included
    c=parse_event_conditions([('rules',rule)],'https://biletinial.com/tr-tr/tiyatro/ornek')
    assert published_fees_included(c) is expected


def test_expired_condition_is_not_presented_as_current(catalogue):
    from app.services.events import current_observation
    from app.core.events import PublishedEventCondition
    events,row=catalogue;r=row('old');r.observed_at=datetime.now(ISTANBUL)-timedelta(days=2);r.conditions_checked=True
    r.conditions=[PublishedEventCondition(topic='reservation',statement='Rezervasyon gereklidir.',source_url='https://biletinial.com/tr-tr/tiyatro/old',source_section='rules')]
    c=event_card(current_observation(r,events.settings))
    assert c['participation_conditions']['status']=='expired'
    assert c['participation_conditions']['source_observed_at']==r.observed_at.isoformat()


def test_unusable_source_does_not_supply_missing_venue_facts(catalogue):
    from app.services.event_locations import enrich_verified_venues
    _,row=catalogue;a,b=row('known'),row('missing');a.source='biletinial';a.detail_checked=b.detail_checked=True
    b.venue=b.venue.model_copy(update={'district':None})
    rows,n=enrich_verified_venues([a,b],usable_sources={'ticketmaster'})
    assert rows[1].venue.district is None and n==0


@pytest.mark.asyncio
async def test_complete_plan_can_require_one_of_each_named_type(catalogue):
    events,row=catalogue;a,b=row('play',12),row('music',16);b.category='concert';events.repository.publish('ticketmaster',[a,b],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',min_events=2,max_events=2,required_categories=['theatre','concert'])
    assert p['data'][0]['fulfillment']['status']=='complete'
    assert all(o['fulfillment']['status']=='complete' and {c['category'] for c in o['performances']}=={'theatre','concert'} for o in p['data'][0]['options'])


def test_adult_only_ticket_cannot_be_assigned_to_a_child_profile():
    assert ticket_quote([offer('Yetişkin',100)],1,'child')['observed_ticket_subtotal_try'] is None
    assert ticket_quote([offer('Yetişkin',100)],1,'adult')['observed_ticket_subtotal_try']==100


def test_mixed_family_package_without_published_composition_is_not_guessed():
    assert ticket_quote([offer('Çocuk ve Yetişkin 2 Kişilik Bilet',100)],2,'general')['observed_ticket_subtotal_try'] is None


@pytest.mark.asyncio
async def test_plan_group_subtotals_do_not_fail_a_budget_due_to_binary_rounding(catalogue):
    events,row=catalogue;a,b=row('one',12),row('two',16);a.offers=[offer('Tam',0.1)];b.offers=[offer('Tam',0.2)]
    events.repository.publish('ticketmaster',[a,b],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',party_size=1,max_price_try=0.3,min_events=2,max_events=2)
    assert p['data'][0]['options'][0]['total_observed_minimum_try']==0.3


def test_explicit_language_fact_is_returned_without_footer_language_guess():
    html=Path('tests/fixtures/events/biletinial-detail.html').read_text()
    html+='<dl class="event-card-v2__facts"><dt>Dil</dt><dd>İngilizce</dd></dl><footer>Dil: Fransızca</footer>'
    rows,_=parse_biletinial_detail(html,'https://biletinial.com/tr-tr/tiyatro/ornek-oyun')
    conditions=[x for x in rows[0].conditions if x.topic=='language']
    assert len(conditions)==1 and conditions[0].source_section=='facts' and 'İngilizce' in conditions[0].statement


@pytest.mark.asyncio
async def test_detail_prices_the_same_selected_performance_for_the_requested_group(catalogue):
    events,row=catalogue;r=row('one');r.offers=[offer('Öğrenci',10),offer('Tam',200)];events.repository.publish('ticketmaster',[r],{})
    p=await events.detail(r.performance_id,party_size=2)
    assert p['data'][0]['selection_status']=='matched'
    c=p['data'][0]['performances'][0]
    assert c['price']['minimum_observed_try']==10 and c['price_quote']['observed_ticket_subtotal_try']==400


def test_legacy_rules_container_is_read_but_footer_is_not():
    html=Path('tests/fixtures/events/biletinial-detail.html').read_text()
    html+='<section id="kurallar_section"><div><p>Rezervasyon gereklidir.</p></div><div><p>Fotoğraf çekimi yasaktır.</p></div></section><footer>Sertifika verilir.</footer>'
    rows,_=parse_biletinial_detail(html,'https://biletinial.com/tr-tr/tiyatro/ornek-oyun')
    topics={c.topic for c in rows[0].conditions};assert {'reservation','photography'}<=topics and 'certificate' not in topics


def test_long_policy_is_not_cut_before_a_late_negation_and_truncation_is_explicit():
    html=Path('tests/fixtures/events/biletinial-detail.html').read_text()
    html+='<div class="event-rules-v2__content"><p>'+('İade hakkında bilgi '*40)+'iade mümkün değildir.</p></div>'
    rows,_=parse_biletinial_detail(html,'https://biletinial.com/tr-tr/tiyatro/ornek-oyun')
    c=event_card(rows[0]);assert c['participation_conditions']['truncated']
    assert not any(x.topic=='refund_exchange' for x in rows[0].conditions)


@pytest.mark.asyncio
async def test_conditional_any_profile_is_preserved_through_plan_discovery(catalogue):
    events,row=catalogue;events.repository.publish('ticketmaster',[row('one')],{})
    p=await EventPlanService(events.settings,events=events).plan(date='2030-11-10',start_time='10:00',end_time='20:00',ticket_profile='any',party_size=1)
    assert p['ok'] and p['data'][0]['options']


@pytest.mark.asyncio
async def test_bounded_query_limit_is_distinct_from_source_outage(catalogue,monkeypatch):
    events,row=catalogue;events.repository.publish('ticketmaster',[row('one')],{})
    def over_budget(*args,**kwargs):raise ValueError('Indexed query exceeds event row budget')
    monkeypatch.setattr(events.repository,'search',over_budget)
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10')
    assert not p['ok'] and p['error']['code']=='query_too_broad'


def test_package_is_not_assumed_partly_usable_by_an_odd_sized_group():
    q=ticket_quote([offer('Çift Kişilik Bilet',200),offer('Tam',300)],3)
    assert q['observed_ticket_subtotal_try']==500 and q['unused_admissions']==0
    assert ticket_quote([offer('Çift Kişilik Bilet',200)],3)['status']=='unknown'


@pytest.mark.asyncio
async def test_fee_inclusive_budget_can_choose_a_higher_but_verified_fee_inclusive_offer(catalogue):
    events,row=catalogue;r=row('one');r.offers=[offer('Tam',100),offer('Genel Giriş',110,fees_included=True)];events.repository.publish('ticketmaster',[r],{})
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',party_size=1,max_price_try=120,include_unknown_prices=False,budget_includes_fees=True)
    assert p['data'][0]['price_quote']['observed_fee_inclusive_total_try']==110
    assert not p['data'][0]['price_quote']['checkout_total_verified']


@pytest.mark.asyncio
async def test_search_diagnostics_survive_the_actual_response_envelope_serialization(catalogue):
    from app.core.envelope import ResponseEnvelope
    events,row=catalogue;r=row('unknown');r.venue=EventVenue(name='Unknown venue');events.repository.publish('ticketmaster',[r],{})
    p=await events.search(date_from='2030-11-10',date_to='2030-11-10',district='Kadıköy')
    wire=ResponseEnvelope.model_validate(p).model_dump(mode='json')
    assert 'location_unverified' in wire['result_info']['empty_reasons']
    assert wire['result_info']['coverage']['city_wide_absence_verified'] is False


def test_event_empty_reasons_and_coverage_survive_streamable_http(tmp_path,monkeypatch):
    import asyncio
    from starlette.testclient import TestClient
    import app.main as main
    from app.core.settings import get_settings
    path=tmp_path/'wire.sqlite3'
    row=EventObservation(source='ticketmaster',source_id='wire',series_key='wire',title='Wire',
        start_at=datetime(2030,11,10,18,tzinfo=ISTANBUL),venue=EventVenue(name='Unknown venue'),observed_at=datetime.now(ISTANBUL))
    EventRepository(path).publish('ticketmaster',[row],{})
    for name,value in [('DATABASE_PATH',str(path)),('EVENTS_ENABLED','true'),('EVENTS_BILETINIAL_ENABLED','false'),('TICKETMASTER_API_KEY','fixture-only'),('MCP_API_KEYS','')]:monkeypatch.setenv(name,value)
    async def idle(settings):await asyncio.Event().wait()
    monkeypatch.setattr(main,'keep_events_fresh',idle);get_settings.cache_clear()
    try:
        with TestClient(main.create_app()) as client:
            r=client.post('/mcp/',headers={'accept':'application/json,text/event-stream'},json={'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':'istanbul_events_search','arguments':{'date_from':'2030-11-10','date_to':'2030-11-10','district':'Kadıköy'}}})
        assert r.status_code==200
        import json
        result=r.json()['result'];p=result.get('structuredContent') or json.loads(result['content'][0]['text'])
        assert 'location_unverified' in p['result_info']['empty_reasons']
        assert not p['result_info']['coverage']['city_wide_absence_verified']
    finally:get_settings.cache_clear()
