"""Reuse only non-conflicting, explicitly verified facts for the same named venue."""
from collections import defaultdict
from app.core.events import search_text
from app.core.geo import haversine_m
from app.services.places import normalize_place

GENERIC = {"istanbul", "istanbul avrupa", "istanbul anadolu"}
ASIA_DISTRICTS = frozenset({
    "adalar", "atasehir", "beykoz", "cekmekoy", "kadikoy", "kartal", "maltepe",
    "pendik", "sancaktepe", "sultanbeyli", "sile", "tuzla", "umraniye", "uskudar",
})

# Canonical Istanbul arts/culture venues whose provider feeds frequently omit district.
# Matched by normalized venue name prefix/containment only when source district is missing.
KNOWN_VENUE_DISTRICTS: tuple[tuple[str, str], ...] = (
    ("baris manco kultur merkezi", "Kadıköy"),
    ("infiniti comedy club", "Kadıköy"),
    ("moda sahnesi", "Kadıköy"),
    ("baba sahne", "Kadıköy"),
    ("alan kadikoy", "Kadıköy"),
    ("sureyya operasi", "Kadıköy"),
    ("muze gazhane", "Kadıköy"),
    ("caddebostan kultur merkezi", "Kadıköy"),
    ("bostanci gosteri merkezi", "Kadıköy"),
    ("koma sahnesi", "Kadıköy"),
    ("tiyatro ak la kara", "Kadıköy"),
    ("sefakoy kultur sanat merkezi", "Küçükçekmece"),
    ("house of performance", "Bakırköy"),
    ("hop sahne", "Bakırköy"),
    ("leyla gencer opera", "Bakırköy"),
    ("cem karaca kultur merkezi", "Bakırköy"),
    ("zorlu psm", "Beşiktaş"),
    ("zorlu performans sanatlari merkezi", "Beşiktaş"),
    ("bkm mutfak", "Beşiktaş"),
    ("if performance hall besiktas", "Beşiktaş"),
    ("ataturk kultur merkezi", "Beyoğlu"),
    ("salon iksv", "Beyoğlu"),
    ("pera muzesi", "Beyoğlu"),
    ("istanbul modern", "Beyoğlu"),
    ("rahmi m koc muzesi", "Beyoğlu"),
    ("salt galata", "Beyoğlu"),
    ("salt beyoglu", "Beyoğlu"),
    ("nardis jazz club", "Beyoğlu"),
    ("yabangee base", "Beyoğlu"),
    ("arter", "Beyoğlu"),
    ("blind istanbul", "Beyoğlu"),
    ("cemal resit rey", "Şişli"),
    ("harbiye muhsin ertugrul", "Şişli"),
    ("harbiye cemil topuzlu", "Şişli"),
    ("kucukciftlik park", "Şişli"),
    ("madera istanbul", "Şişli"),
    ("trump sahne", "Şişli"),
    ("kenter tiyatrosu", "Şişli"),
    ("toy istanbul", "Şişli"),
    ("jj pub kanyon", "Şişli"),
    ("babylon", "Şişli"),
    ("maximum uniq", "Sarıyer"),
    ("volkswagen arena", "Sarıyer"),
    ("sakip sabanci muzesi", "Sarıyer"),
    ("borusan contemporary", "Sarıyer"),
    ("dasdas", "Ataşehir"),
    ("watergarden performans", "Ataşehir"),
    ("duru tiyatro", "Ataşehir"),
    ("fisekhane", "Zeytinburnu"),
    ("sahne khas", "Fatih"),
    ("ali emiri efendi kultur merkezi", "Fatih"),
    ("bulent ecevit kultur merkezi", "Kartal"),
    ("hoca ahmet yesevi kultur merkezi", "Sultangazi"),
    ("idris gulluce kultur merkezi", "Tuzla"),
    ("adem basturk kultur merkezi", "Esenler"),
    ("erdem bayazit kultur merkezi", "Güngören"),
    ("enver oren kultur merkezi", "Büyükçekmece"),
    ("moi sahne", "Başakşehir"),
    ("tekel sahnesi", "Üsküdar"),
    ("baglarbasi kongre", "Üsküdar"),
)


def _known_venue_district(venue_name: str) -> str | None:
    folded = search_text(venue_name)
    if not folded or folded == "unknown venue":
        return None
    for needle, district in KNOWN_VENUE_DISTRICTS:
        if needle == folded or f" {needle} " in f" {folded} ":
            return district
    return None


def enrich_verified_venues(rows, usable_sources=None):
    groups = defaultdict(list)
    for row in rows:
        if row.detail_checked and row.venue.name != "Unknown venue" and (usable_sources is None or row.source in usable_sources):
            groups[search_text(row.venue.name)].append(row)
    result = []
    filled = 0
    for row in rows:
        a = row.venue
        updated = row
        peers = groups.get(search_text(a.name), []) if row.detail_checked else []
        districts = {p.venue.district for p in peers if p.venue.district}
        addresses = {normalize_place(p.venue.address) for p in peers if p.venue.address and normalize_place(p.venue.address) not in GENERIC}
        coords = {(p.venue.lat, p.venue.lon) for p in peers if p.venue.lat is not None and p.venue.lon is not None}
        if len(districts) <= 1 and len(addresses) <= 1 and len(coords) <= 1:
            reference = next((p for p in peers if p.venue.district), None)
            if reference is not None:
                b = reference.venue
                address_ok = not (a.address and normalize_place(a.address) not in GENERIC and b.address and normalize_place(a.address) != normalize_place(b.address))
                coord_ok = not (all(v is not None for v in (a.lat, a.lon, b.lat, b.lon)) and haversine_m(a.lat, a.lon, b.lat, b.lon) > 25)
                if address_ok and coord_ok:
                    changes = {k: getattr(b, k) for k in ("district", "side", "lat", "lon") if getattr(a, k) is None and getattr(b, k) is not None}
                    if changes:
                        evidence = {**a.field_evidence, **{k: {"basis": "same_verified_venue", "source_url": reference.ticket_url or "",
                                                               "observed_at": reference.observed_at.isoformat()} for k in changes}}
                        a = a.model_copy(update={**changes, "field_evidence": evidence})
                        updated = updated.model_copy(update={"venue": a})
                        filled += len(changes)
        if a.district is None and a.name != "Unknown venue":
            known_district = _known_venue_district(a.name)
            if known_district is not None:
                side = "asia" if normalize_place(known_district) in ASIA_DISTRICTS else "europe"
                # Never contradict an explicitly published opposite side.
                if a.side is None or a.side == side:
                    changes = {"district": known_district}
                    if a.side is None:
                        changes["side"] = side
                    evidence = {**a.field_evidence, **{k: {"basis": "verified_venue_directory"} for k in changes}}
                    a = a.model_copy(update={**changes, "field_evidence": evidence})
                    updated = updated.model_copy(update={"venue": a})
                    filled += len(changes)
        result.append(updated)
    return result, filled
