"""Observed ticket baskets, never live inventory or an invented checkout total."""
from __future__ import annotations
from decimal import Decimal
import re
from app.core.events import EventOffer
from app.services.places import normalize_place

PROFILES = {'any', 'general', 'adult', 'student', 'child', 'senior'}


def offer_terms(offer: EventOffer) -> dict:
    text = normalize_place(offer.name)
    profiles=[value for pattern,value in (
        (r'\bogrenci\b|\bstudent\b','student'),
        (r'\bcocuk\b|\bchild\b','child'),
        (r'\bemekli\b|65 yas|\bsenior\b','senior'),
        (r'\byetiskin\b|\badult\b','adult'),
    ) if re.search(pattern,text)]
    profile=profiles[0] if len(profiles)==1 else None
    ambiguous_profile=len(profiles)>1
    count = None
    match = re.search(r'\b(\d{1,2})\s*kisilik\b',text)
    if match and 1 <= int(match[1]) <= 50:
        count = int(match[1])
    elif re.search(r'\bcift kisilik\b|\biki kisilik\b',text):
        count = 2
    elif re.search(r'\btek kisilik\b|\bkisi basi\b|\bper person\b',text):
        count = 1
    if profile or re.fullmatch(r'(?:tam|genel|normal|genel giris)(?: bilet(?:i)?)?',text) or text in {'standart bilet','standard ticket'}:
        count = count or 1
        profile = profile or 'general'
    elif count and not ambiguous_profile and not re.search(r'indirim|kampanya|uye|promosyon|grup|aile',text):
        profile = 'general'
    # Provider fallback name "Standard", an unnamed price category, or a
    # duration package does not prove a per-person general admission unit.
    return {'ticket_name':offer.name,'profile':profile or 'unknown',
            'admissions_per_ticket':count,'unit_status':'published_label' if count else 'unknown',
            'eligibility_requires_confirmation':profile not in (None,'general') or profile is None,
            'availability_is_live':False}


def _cover_states(eligible, target):
    if not eligible:return {0:(Decimal(0),())}
    bound=target
    dp={0:(Decimal(0),())}
    for n in range(bound+1):
        if n not in dp:continue
        for index,offer,terms in eligible:
            nxt=n+terms['admissions_per_ticket']
            if nxt>bound:continue
            cost,path=dp[n];candidate=(cost+Decimal(str(offer.price)),path+(index,))
            if nxt not in dp or (candidate[0],len(candidate[1]),candidate[1])<(dp[nxt][0],len(dp[nxt][1]),dp[nxt][1]):dp[nxt]=candidate
    return dp


def party_quote(offers, party, *, fees_required=False):
    size=sum(party.values());eligible=[]
    for i,offer in enumerate(offers):
        terms=offer_terms(offer)
        if offer.price is not None and offer.currency=='TRY' and offer.availability!='sold_out' and terms['admissions_per_ticket'] and terms['profile']!='unknown' and (not fees_required or offer.fees_included is True):
            eligible.append((i,offer,terms))
    base={'party':party,'party_size':size,'status':'unknown','observed_ticket_subtotal_try':None,
          'observed_fee_inclusive_total_try':None,'checkout_total_try':None,'checkout_total_verified':False,
          'fees_status':'unknown','quantity_available_verified':False,'adjacent_seats_verified':False,
          'admissions_purchased':None,'unused_admissions':None,'basket':[],'components':[],
          'reason':'some_ticket_units_or_profiles_unverified'}
    # Profile-specific discounted packages cannot be assigned to another profile.
    # General tickets may cover any remaining participant, including across profiles.
    states={0:(Decimal(0),(),{})}
    for profile,count in party.items():
        if profile=='general':continue
        specific=[x for x in eligible if x[2]['profile']!='general' and (profile=='any' or x[2]['profile']==profile)]
        raw=_cover_states(specific,count);choices={}
        for actual,(cost,path) in raw.items():
            covered=min(count,actual)
            if covered not in choices or (cost,len(path),path)<(choices[covered][0],len(choices[covered][1]),choices[covered][1]):choices[covered]=(cost,path)
        new={}
        for previous,(cost,path,alloc) in states.items():
            for covered,(extra,tickets) in choices.items():
                n=previous+covered;candidate=(cost+extra,path+tickets,{**alloc,profile:covered})
                if n not in new or (candidate[0],len(candidate[1]),candidate[1])<(new[n][0],len(new[n][1]),new[n][1]):new[n]=candidate
        states=new
    general=_cover_states([x for x in eligible if x[2]['profile']=='general'],size)
    choices=[]
    for covered,(cost,path,allocation) in states.items():
        remaining=size-covered
        for actual,(extra,tickets) in general.items():
            if actual==remaining:choices.append((cost+extra,len(path+tickets),path+tickets,allocation))
    if not choices:return base
    cost,_,path,allocation=min(choices,key=lambda x:(x[0],x[1],x[2]))
    counts={i:path.count(i) for i in sorted(set(path))};purchased=sum(offer_terms(offers[i])['admissions_per_ticket']*n for i,n in counts.items())
    basket=[{'offer_index':i,**offer_terms(offers[i]),'quantity':n,'observed_unit_price_try':offers[i].price,
             'observed_line_subtotal_try':float(Decimal(str(offers[i].price))*n),
             'fees_included':offers[i].fees_included,'observed_availability':offers[i].availability} for i,n in counts.items()]
    fees='included_in_observed_price' if all(offers[i].fees_included is True for i in counts) else 'not_included_amount_unknown' if any(offers[i].fees_included is False for i in counts) else 'unknown'
    base.update(status='observed_subtotal',observed_ticket_subtotal_try=float(cost),
                observed_fee_inclusive_total_try=float(cost) if fees=='included_in_observed_price' else None,
                fees_status=fees,admissions_purchased=purchased,unused_admissions=purchased-size,basket=basket,
                components=[{'ticket_profile':p,'participants':n,'covered_by_profile_specific_tickets':allocation.get(p,0)} for p,n in party.items()],reason=None)
    return base


def ticket_quote(offers, party_size, profile='general'):
    result=party_quote(offers,{profile:party_size});result['ticket_profile']=profile
    return result


def resolve_party(party_size=None, ticket_profile=None, party=None):
    from app.core.validation import InputValidationError
    if ticket_profile is not None and ticket_profile not in PROFILES:
        raise InputValidationError('Unsupported ticket_profile',field='ticket_profile')
    if party_size is not None and (isinstance(party_size,bool) or not isinstance(party_size,int) or not 1<=party_size<=50):
        raise InputValidationError('party_size must be 1–50',field='party_size')
    if party is not None:
        if not isinstance(party,dict) or not 1<=len(party)<=5 or any(k not in PROFILES for k in party) or ('any' in party and len(party)>1):
            raise InputValidationError('party must map general/adult/student/child/senior to counts',field='party')
        if any(isinstance(v,bool) or not isinstance(v,int) or not 1<=v<=50 for v in party.values()) or sum(party.values())>50:
            raise InputValidationError('party must contain 1–50 total participants',field='party')
        if ticket_profile is not None or party_size is not None and party_size!=sum(party.values()):
            raise InputValidationError('Use party or matching party_size without ticket_profile',field='party')
        return dict(party)
    if party_size is None and ticket_profile is None:return None
    return {ticket_profile or 'general':party_size or 1}


def apply_party_quote(card, offers, party, *, budget=None, includes_fees=False):
    quote=party_quote(offers,party)
    if includes_fees:
        fee_quote=party_quote(offers,party,fees_required=True)
        if fee_quote['status']=='observed_subtotal':
            fee_quote['ticket_only_minimum_subtotal_try']=quote['observed_ticket_subtotal_try']
            quote=fee_quote
    value=quote['observed_fee_inclusive_total_try'] if includes_fees else quote['observed_ticket_subtotal_try']
    quote['budget_includes_fees']=includes_fees
    quote['budget_status']='unknown' if value is None else 'over' if budget is not None and value>budget else 'within_observed_amount' if budget is not None else 'not_requested'
    card['price_quote']=quote
    card['budget_price_try']=value
    card['budget_price_basis']='observed_fee_inclusive_party_total' if includes_fees else 'observed_party_ticket_subtotal'
    card['budget_status']='unknown' if value is None else 'over' if budget is not None and value>budget else 'within' if budget is not None else 'not_requested'
    return card
