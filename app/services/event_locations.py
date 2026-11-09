"""Reuse only non-conflicting, explicitly verified facts for the same named venue."""
from collections import defaultdict
from app.core.events import search_text
from app.core.geo import haversine_m
from app.services.places import normalize_place

GENERIC={'istanbul','istanbul avrupa','istanbul anadolu'}


def enrich_verified_venues(rows, usable_sources=None):
    groups=defaultdict(list)
    for row in rows:
        if row.detail_checked and row.venue.name!='Unknown venue' and (usable_sources is None or row.source in usable_sources):groups[search_text(row.venue.name)].append(row)
    result=[];filled=0
    for row in rows:
        peers=groups.get(search_text(row.venue.name),[]) if row.detail_checked else []
        districts={p.venue.district for p in peers if p.venue.district}
        addresses={normalize_place(p.venue.address) for p in peers if p.venue.address and normalize_place(p.venue.address) not in GENERIC}
        coords={(p.venue.lat,p.venue.lon) for p in peers if p.venue.lat is not None and p.venue.lon is not None}
        if len(districts)>1 or len(addresses)>1 or len(coords)>1:
            result.append(row);continue
        reference=next((p for p in peers if p.venue.district),None)
        if reference is None:result.append(row);continue
        a,b=row.venue,reference.venue
        if a.address and normalize_place(a.address) not in GENERIC and b.address and normalize_place(a.address)!=normalize_place(b.address):
            result.append(row);continue
        if all(v is not None for v in (a.lat,a.lon,b.lat,b.lon)) and haversine_m(a.lat,a.lon,b.lat,b.lon)>25:
            result.append(row);continue
        changes={k:getattr(b,k) for k in ['district','side','lat','lon'] if getattr(a,k) is None and getattr(b,k) is not None}
        if changes:
            evidence={**a.field_evidence,**{k:{'basis':'same_verified_venue','source_url':reference.ticket_url or '',
                        'observed_at':reference.observed_at.isoformat()} for k in changes}}
            result.append(row.model_copy(update={'venue':a.model_copy(update={**changes,'field_evidence':evidence})}));filled+=len(changes)
        else:result.append(row)
    return result,filled
