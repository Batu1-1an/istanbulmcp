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
    assert event_about(
        obs("ARANIZDA EN CESUR KİM? - Canlı Karaoke", "ARANIZDA EN CESUR KİM? Canlı Karaoke Ofiste mikrofonu bırakmayanlar için.")
    )["text"].startswith("Ofiste mikrofonu")


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
