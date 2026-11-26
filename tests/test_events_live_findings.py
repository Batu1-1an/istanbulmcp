"""Regression tests for live production event-quality findings."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import time

import pytest

from app.connectors.biletinial import parse_biletinial_detail
from app.core.events import ISTANBUL, EventObservation, EventOffer, venue_from
from app.core.settings import Settings
from app.services.event_plan import EventPlanService
from app.services.event_pricing import party_quote
from app.services.events import EventService, event_about
from app.storage.events import EventRepository

SV2_HTML = """<!doctype html><html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Event","name":"Canlı Karaoke","startDate":"2030-11-26T19:00:00+03:00",
"location":{"@type":"Place","name":"JJ Pub Kanyon","address":{"streetAddress":"Levent","addressLocality":"İstanbul Avrupa"}},
"offers":{"@type":"Offer","price":285,"priceCurrency":"TRY","availability":"https://schema.org/InStock"}}
</script></head><body>
<div class="event-card-v2__description"><p>6–12 yaş arasındaki katılımcılar için eğlenceli bir akşam.</p></div>
<div class="row sv2-row" id="seans-18606750" data-seance-id="18606750"
     data-start="2030-11-26T19:00:00+03:00" data-city-name="İstanbul Avrupa"
     data-lat="41.078037" data-lng="29.010413" data-status="onsale">
  <div class="dl"><span class="d">Perşembe</span><span class="tm">19:00</span></div>
  <div class="vl"><a href="/tr-tr/mekan/jj-pub-kanyon">JJ Pub Kanyon</a></div>
  <div class="td">Organizasyon: İBB Şehir Tiyatroları</div>
  <div class="price-list extra-panel" id="sv2-18606750-prices" hidden>
    <div class="price-item"><span>Ka&#231;maz Cuma - Genel Giriş Bileti</span><strong>285 ₺</strong></div>
    <div class="price-item"><span>Genel Giriş Bileti</span><strong>856 ₺</strong></div>
  </div>
</div>
</body></html>"""


def test_venue_from_extracts_district_from_name_and_side_from_generic_address():
    v1 = venue_from("HOP Sahne - Bakırköy", "")
    assert v1.district == "Bakırköy" and v1.side == "europe"

    v2 = venue_from("Corner Kadıköy", "İstanbul Anadolu")
    assert v2.district == "Kadıköy" and v2.side == "asia"

    v3 = venue_from("Madera İstanbul", "İstanbul Avrupa")
    assert v3.district is None and v3.side == "europe"

    v4 = venue_from("Örnek Mekan", "İstanbul Anadolu")
    assert v4.district is None and v4.side == "asia"


def test_biletinial_sv2_row_parses_real_ticket_labels_organizer_coords_and_description_age():
    url = "https://biletinial.com/tr-tr/muzik/canli-karaoke"
    obs, meta = parse_biletinial_detail(SV2_HTML, url)
    assert meta["complete"] is True and meta["skipped"] == 0 and len(obs) == 1
    row = obs[0]
    assert row.start_time_basis == "html_session"
    assert row.organizer == "İBB Şehir Tiyatroları"
    assert row.venue.side == "europe"
    assert row.venue.lat == pytest.approx(41.078037)
    assert row.age_limit == "6-12"
    assert [(o.name, o.price, o.availability) for o in row.offers] == [
        ("Kaçmaz Cuma - Genel Giriş Bileti", 285.0, "in_stock"),
        ("Genel Giriş Bileti", 856.0, "in_stock"),
    ]
    quote = party_quote(row.offers, {"adult": 2})
    assert quote["status"] == "observed_subtotal"
    assert quote["observed_ticket_subtotal_try"] == 1712.0


def test_event_about_strips_punctuation_variant_titles_and_leading_genre_labels():
    now = datetime.now(timezone.utc)
    def obs(title: str, desc: str) -> EventObservation:
        return EventObservation(
            source="biletinial", source_id="s1", series_key="k1", title=title,
            start_at=datetime(2030, 11, 26, 20, 0, tzinfo=ISTANBUL),
            venue=venue_from("Sahne", "Kadıköy"), observed_at=now,
            detail_checked=True, description=desc,
        )

    assert event_about(obs("Clarte", "Clarte Konseri 2024 yılında İstanbul'da kurulmuştur."))["text"].startswith("2024 yılında")
    assert event_about(obs("Küçük Kara Balık", "Tiyatro Oyunu Samed Behrengi'nin eseri."))["text"].startswith("Samed Behrengi")
    assert event_about(obs("Hedypatheia", "Etkinliği Hedypatheia: tarihin ilk gastronomi eseri."))["text"].startswith("Hedypatheia:")
    assert event_about(
        obs("ARANIZDA EN CESUR KİM? - Canlı Karaoke", "ARANIZDA EN CESUR KİM? Canlı Karaoke Ofiste mikrofonu bırakmayanlar için.")
    )["text"].startswith("Ofiste mikrofonu")


def test_pricing_accepts_explicit_tam_and_ucretsiz_while_keeping_bare_or_discounted_categories_unknown():
    from app.services.event_pricing import offer_terms

    for label in ("1. Kategori Tam", "Salon Tam", "Balkon Tam", "Ücretsiz", "Ücretsiz Giriş", "Genel Giriş - Ayakta"):
        terms = offer_terms(EventOffer(name=label, price=100.0, currency="TRY"))
        assert terms["profile"] == "general" and terms["admissions_per_ticket"] == 1, label

    for label in ("Standard", "1. Kategori", "1. Kategori İndirimli", "Kaçmaz Cuma - Genel Giriş Bileti", "VIP Masa Tam"):
        terms = offer_terms(EventOffer(name=label, price=100.0, currency="TRY"))
        assert terms["profile"] == "unknown", label


def test_known_venue_directory_fills_missing_district_without_overriding_explicit_district():
    from app.services.event_locations import enrich_verified_venues

    now = datetime.now(timezone.utc)
    start = datetime(2030, 11, 26, 20, 0, tzinfo=ISTANBUL)
    baris = EventObservation(
        source="ticketmaster", source_id="tm-1", series_key="k1", title="Oyun",
        start_at=start, venue=venue_from("Barış Manço Kültür Merkezi", ""), observed_at=now,
    )
    baksm = EventObservation(
        source="ticketmaster", source_id="tm-2", series_key="k2", title="Oyun 2",
        start_at=start, venue=venue_from("Beylikdüzü Atatürk Kültür ve Sanat Merkezi (BAKSM)", ""), observed_at=now,
    )
    enriched, filled = enrich_verified_venues([baris, baksm])
    assert enriched[0].venue.district == "Kadıköy"
    assert enriched[0].venue.side == "asia"
    assert enriched[0].venue.field_evidence["district"]["basis"] == "verified_venue_directory"
    assert enriched[1].venue.district == "Beylikdüzü"
    assert filled >= 2


def test_pending_details_prioritizes_unverified_series_before_stale_refresh(tmp_path):
    repo = EventRepository(tmp_path / "pending.sqlite3")
    soon = datetime.now(ISTANBUL).replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
    later = soon + timedelta(days=2)
    stale_verified = EventObservation(
        source="biletinial", source_id="s-stale", series_key="stale-series", title="Stale",
        start_at=soon, venue=venue_from("Sahne", "Kadıköy"),
        detail_checked=True, observed_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    never_checked = EventObservation(
        source="biletinial", source_id="s-new", series_key="new-series", title="New",
        start_at=later, venue=venue_from("Unknown venue"),
        detail_checked=False, observed_at=datetime.now(timezone.utc),
    )
    repo.publish("biletinial", [stale_verified, never_checked], {"complete": True})
    order = repo.pending_details(limit=10, ttl_seconds=900)
    assert order == [never_checked.event_id, stale_verified.event_id]


@pytest.mark.asyncio
async def test_organizer_search_and_next_queries_hints(tmp_path):
    db = tmp_path / "events.sqlite3"
    repo = EventRepository(db)
    start = datetime.now(ISTANBUL).replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    row = EventObservation(
        source="biletinial", source_id="s-org-1", series_key="fosforlu",
        title="Fosforlu Cevriye", category="theatre", start_at=start,
        venue=venue_from("Ümraniye Sahnesi", "Ümraniye, İstanbul"),
        organizer="İBB Şehir Tiyatroları", detail_checked=True,
        offers=[EventOffer(name="Genel Giriş Bileti", price=160.0, currency="TRY", availability="in_stock")],
        observed_at=datetime.now(timezone.utc),
    )
    repo.publish("biletinial", [row], {"complete": True})
    service = EventService(Settings(database_path=db, events_enabled=True, events_biletinial_enabled=True))

    title_only = await service.search(query="Şehir Tiyatroları", query_scope="title")
    assert title_only["data"] == []
    assert any("query_scope='all'" in hint for hint in title_only["next_queries"])

    all_scope = await service.search(query="Şehir Tiyatroları", query_scope="all")
    assert len(all_scope["data"]) == 1 and all_scope["data"][0]["title"] == "Fosforlu Cevriye"

    caz = await service.search(query="caz")
    assert any("jazz" in hint for hint in caz["next_queries"])


@pytest.mark.asyncio
async def test_on_demand_detail_checks_run_concurrently(tmp_path, monkeypatch):
    db = tmp_path / "concurrent.sqlite3"
    repo = EventRepository(db)
    start = datetime.now(ISTANBUL).replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    rows = [
        EventObservation(
            source="biletinial", source_id=f"c-{i}", series_key=f"series-{i}",
            title=f"Konser {i}", category="concert", start_at=start + timedelta(minutes=i),
            venue=venue_from("Unknown venue"), detail_checked=False,
            ticket_url=f"https://biletinial.com/tr-tr/muzik/series-{i}",
            observed_at=datetime.now(timezone.utc),
        )
        for i in range(3)
    ]
    repo.publish("biletinial", rows, {"complete": True})
    service = EventService(Settings(database_path=db, events_enabled=True, events_biletinial_enabled=True))

    async def slow_detail(_event_id: str, **_kwargs):
        await asyncio.sleep(0.15)
        return {"ok": True, "data": [{}]}

    monkeypatch.setattr(service, "detail", slow_detail)
    started = time.perf_counter()
    res = await service.search(category="concert")
    elapsed = time.perf_counter() - started
    assert res["result_info"]["filter_counts"]["detail_checks_attempted"] == 3
    assert elapsed < 0.38, f"expected concurrent detail checks, took {elapsed:.2f}s"


@pytest.mark.asyncio
async def test_complete_plan_omits_redundant_partial_options(tmp_path):
    db = tmp_path / "plan.sqlite3"
    repo = EventRepository(db)
    day = (datetime.now(ISTANBUL) + timedelta(days=1)).date()
    rows = [
        EventObservation(
            source="biletinial", source_id=f"p-{i}", series_key=f"play-{i}",
            title=f"Oyun {i}", category="theatre",
            start_at=datetime(day.year, day.month, day.day, 18 + i * 2, 0, tzinfo=ISTANBUL),
            end_at=datetime(day.year, day.month, day.day, 19 + i * 2, 0, tzinfo=ISTANBUL),
            end_source="source_end",
            venue=venue_from("Kadıköy Sahne", "Kadıköy, İstanbul"),
            detail_checked=True,
            offers=[EventOffer(name="Genel Giriş Bileti", price=200.0, currency="TRY", availability="in_stock")],
            observed_at=datetime.now(timezone.utc),
        )
        for i in range(2)
    ]
    repo.publish("biletinial", rows, {"complete": True})
    planner = EventPlanService(Settings(database_path=db, events_enabled=True, events_biletinial_enabled=True))
    res = await planner.plan(date=day.isoformat(), district="Kadıköy", min_events=2, max_events=2)
    plan = res["data"][0]
    assert plan["fulfillment"]["status"] == "complete"
    assert len(plan["options"]) == 1
    assert plan["partial_options"] == []
    assert plan["fulfillment"]["partial_option_count"] == 0


def test_biletinial_free_session_labels_zero_offer_as_ucretsiz_for_party_quote():
    free_html = """<!doctype html><html><head>
    <script type="application/ld+json">
    {"@context":"https://schema.org","@type":"Event","name":"Ücretsiz Oyun","startDate":"2030-11-26T20:00:00+03:00",
    "location":{"@type":"Place","name":"İBB Kültür Merkezi","address":{"addressLocality":"İstanbul Avrupa"}},
    "offers":{"@type":"Offer","price":0,"priceCurrency":"TRY","availability":"https://schema.org/InStock"}}
    </script></head><body>
    <div class="row sv2-row" id="seans-999" data-start="2030-11-26T20:00:00+03:00"
         data-city-name="İstanbul Avrupa" data-status="onsale">
      <div class="dl"><span class="d">Perşembe</span><span class="tm">20:00</span></div>
      <div class="vl"><a href="/tr-tr/mekan/ibb-km">İBB Kültür Merkezi</a></div>
      <div class="price"><b>Ücretsiz</b></div>
    </div></body></html>"""
    obs, _ = parse_biletinial_detail(free_html, "https://biletinial.com/tr-tr/tiyatro/ucretsiz-oyun")
    assert obs[0].offers[0].name == "Ücretsiz"
    quote = party_quote(obs[0].offers, {"general": 2})
    assert quote["status"] == "observed_subtotal" and quote["observed_ticket_subtotal_try"] == 0.0


def test_deduplicate_merges_cross_provider_apostrophe_title_variants():
    from app.services.events import deduplicate

    now = datetime.now(timezone.utc)
    start = datetime(2030, 11, 28, 20, 0, tzinfo=ISTANBUL)
    a = EventObservation(
        source="biletinial", source_id="b1", series_key="olun", title="Ölün Bizi Ayırana Dek",
        start_at=start, venue=venue_from("Sefaköy Kültür Sanat Merkezi", "Küçükçekmece"), observed_at=now,
    )
    b = EventObservation(
        source="ticketmaster", source_id="t1", series_key="olun-tm", title="Ölü'n Bizi Ayırana Dek",
        start_at=start, venue=venue_from("Sefaköy Kültür Sanat Merkezi", "Küçükçekmece"), observed_at=now,
    )
    groups = deduplicate([a, b])
    assert len(groups) == 1 and len(groups[0][1]) == 2


@pytest.mark.asyncio
async def test_detail_deduplicates_identical_conditions_and_about_across_sessions(tmp_path):
    from app.core.events import PublishedEventCondition

    db = tmp_path / "dedup_detail.sqlite3"
    repo = EventRepository(db)
    now = datetime.now(timezone.utc)
    start = datetime.now(ISTANBUL).replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    conds = [
        PublishedEventCondition(
            topic="refund_exchange",
            statement="Bilet iadesi yapılmaz.",
            source_url="https://biletinial.com/tr-tr/tiyatro/ornek",
            source_section="rules",
        )
    ]
    rows = [
        EventObservation(
            source="biletinial", source_id=f"s-{i}", series_key="ornek", title="Örnek Oyun",
            category="theatre", start_at=start + timedelta(days=i),
            venue=venue_from("Moda Sahnesi", "Kadıköy"), observed_at=now,
            detail_checked=True, description="İki kardeşin İstanbul'da kesişen hikâyesi.",
            conditions=conds, conditions_checked=True,
            offers=[EventOffer(name="Genel Giriş Bileti", price=200.0, currency="TRY", availability="in_stock")],
        )
        for i in range(3)
    ]
    repo.publish("biletinial", rows, {"complete": True})
    service = EventService(Settings(database_path=db, events_enabled=True, events_biletinial_enabled=True))
    # Prevent live HTTP fetch by setting detail_checked TTL as fresh via monkeypatch or using ticketmaster
    rows_tm = [r.model_copy(update={"source": "ticketmaster", "source_id": f"tm-{i}"}) for i, r in enumerate(rows)]
    repo.publish("ticketmaster", rows_tm, {"complete": True})
    service = EventService(Settings(database_path=db, events_enabled=True, ticketmaster_api_key="fixture-key"))
    det = await service.detail(rows_tm[0].event_id)
    assert det["ok"], det
    d0 = det["data"][0]
    assert d0["participation_conditions"]["statements"]
    assert d0["about"]["text"]
    assert d0["performances"][0]["participation_conditions"]["statements"]
    assert d0["performances"][1]["participation_conditions"] == {"same_as_event": True, "status": "inspected", "statement_count": 1}
    assert d0["performances"][1]["about"] == {"same_as_event": True, "status": "available"}


@pytest.mark.asyncio
async def test_search_skips_on_demand_detail_checks_when_enough_fresh_verified_matches_exist(tmp_path, monkeypatch):
    db = tmp_path / "skip_refresh.sqlite3"
    repo = EventRepository(db)
    now = datetime.now(timezone.utc)
    start = datetime.now(ISTANBUL).replace(hour=20, minute=0, second=0, microsecond=0) + timedelta(days=1)
    verified_rows = [
        EventObservation(
            source="biletinial", source_id=f"v-{i}", series_key=f"verified-{i}", title=f"Konser {i}",
            category="concert", start_at=start + timedelta(minutes=i),
            venue=venue_from("Moda Sahnesi", "Kadıköy"), observed_at=now,
            detail_checked=True,
            offers=[EventOffer(name="Genel Giriş Bileti", price=200.0, currency="TRY", availability="in_stock")],
        )
        for i in range(3)
    ]
    unchecked = EventObservation(
        source="biletinial", source_id="u-1", series_key="unchecked-1", title="Konser Unchecked",
        category="concert", start_at=start + timedelta(hours=1),
        venue=venue_from("Unknown venue"), observed_at=now,
        detail_checked=False, ticket_url="https://biletinial.com/tr-tr/muzik/unchecked-1",
    )
    repo.publish("biletinial", [*verified_rows, unchecked], {"complete": True})
    service = EventService(Settings(database_path=db, events_enabled=True, events_biletinial_enabled=True))
    called = []
    async def spy_detail(eid, **_kw):
        called.append(eid)
        return {"ok": True, "data": [{}]}
    monkeypatch.setattr(service, "detail", spy_detail)

    res = await service.search(category="concert", limit=3)
    assert res["ok"] and len(res["data"]) == 3
    assert res["result_info"]["filter_counts"]["detail_checks_attempted"] == 0
    assert called == []
