"""Reproduce the actionable findings from the 100-scenario QA report."""
import asyncio
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from app.connectors.biletinial import parse_biletinial_detail, parse_biletinial_list
from app.connectors.ticketmaster import TicketmasterClient
from app.core.envelope import ResponseEnvelope
from app.core.events import EventObservation, EventOffer, EventVenue, ISTANBUL
from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.event_plan import EventPlanService, diverse_options, enumerate_plans
from app.services.events import EventService, event_card
from app.storage.db import connect
from app.storage.events import EventRepository

FIXTURES = Path(__file__).parent / "fixtures/events"


def occurrence(identity="one", hour=11, **updates):
    row = EventObservation(source="ticketmaster", source_id=identity, series_key=identity,
        title="Örnek " + identity, category="theatre",
        start_at=datetime(2030, 11, 8, hour, tzinfo=ISTANBUL),
        end_at=datetime(2030, 11, 8, hour + 1, tzinfo=ISTANBUL),
        venue=EventVenue(name="Örnek Sahne", district="Kadıköy"),
        offers=[EventOffer(price=100, currency="TRY", availability="in_stock")],
        observed_at=datetime.now(timezone.utc), ticket_url="https://www.biletix.com/performance/ABC12/001/TURKIYE/tr")
    return row.model_copy(update=updates)


@pytest.fixture
def events(tmp_path):
    clear_source_cache()
    settings = Settings(events_enabled=True, ticketmaster_api_key="fixture-only",
        database_path=tmp_path / "qa.sqlite3")
    repository = EventRepository(settings.database_path)
    repository.publish("ticketmaster", [occurrence()], {"accepted": 1})
    yield EventService(settings, repository=repository)
    clear_source_cache()


@pytest.mark.parametrize("genre,expected", [("Atölye", "workshop"), ("Sergi", "exhibition"),
    ("Spor", "sport"), ("Söyleşi", "seminar"), ("Müzik Festivali", "festival")])
def test_dedicated_source_genres_are_mapped_outside_the_broad_event_bucket(genre, expected):
    html = (FIXTURES / "biletinial-detail.html").read_text()
    html += f'<dl class="event-card-v2__facts"><dt>Etkinlik Türü</dt><dd>{genre}</dd></dl>'
    rows, _ = parse_biletinial_detail(html, "https://biletinial.com/tr-tr/etkinlik/ornek-oyun")
    assert all(row.category == expected and row.category_source == "provider" for row in rows)


def test_generic_event_title_markers_have_explicit_evidence_and_survive_detail():
    payload = json.loads((FIXTURES / "biletinial-list.json").read_text())
    payload["items"][0].update(name="Parfüm Atölyesi", categoryName="Etkinlik")
    listed, _ = parse_biletinial_list(payload, "etkinlik")
    assert all(row.category == "workshop" and row.category_source == "title_marker" for row in listed)
    html = (FIXTURES / "biletinial-detail.html").read_text().replace("Örnek Oyun", "Parfüm Atölyesi")
    rows, _ = parse_biletinial_detail(html, "https://biletinial.com/tr-tr/etkinlik/ornek-oyun")
    assert all(event_card(row)["category_source"] == "title_marker" for row in rows)
    payload["items"][0]["name"] = "Kırmızı Başlıklı Kız"
    assert all(row.category == "other" for row in parse_biletinial_list(payload, "etkinlik")[0])


@pytest.mark.asyncio
async def test_missing_category_observations_are_not_claimed_as_zero_city_coverage(events):
    result = await events.search(date_from="2030-11-08", category="sport")
    assert result["ok"] and not result["data"]
    assert any("category_coverage=not_observed" in limit for limit in result["limits"])
    assert any("does not establish" in warning for warning in result["warnings"])


@pytest.mark.asyncio
async def test_failed_refresh_keeps_last_success_and_marks_even_recent_data_stale(events, monkeypatch):
    async def fail(self):
        raise TimeoutError("fixture source failure")
    monkeypatch.setattr(TicketmasterClient, "catalogue", fail)
    with pytest.raises(TimeoutError):
        await events.refresh_source("ticketmaster", force=True)
    result = await events.search(date_from="2030-11-08")
    ResponseEnvelope.model_validate(result)
    assert result["ok"] and len(result["data"]) == 1
    assert result["freshness"]["status"] == "stale"
    assert result["sources"][0]["refresh_status"] == "failed"
    assert result["sources"][0]["serving_stale"] is True


@pytest.mark.asyncio
async def test_search_can_read_whole_previous_snapshot_while_refresh_is_running(events, monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    async def delayed(self):
        started.set()
        await release.wait()
        return [occurrence("replacement")], {"accepted": 1}
    monkeypatch.setattr(TicketmasterClient, "catalogue", delayed)
    task = asyncio.create_task(events.refresh_source("ticketmaster", force=True))
    try:
        await asyncio.wait_for(started.wait(), 2)
        result = await asyncio.wait_for(events.search(date_from="2030-11-08"), 2)
        assert [card["title"] for card in result["data"]] == ["Örnek one"]
        assert result["sources"][0]["refresh_status"] == "refreshing"
        assert any("refresh is in progress" in note for note in result["warnings"])
    finally:
        release.set()
        await task
    result = await events.search(date_from="2030-11-08")
    assert [card["title"] for card in result["data"]] == ["Örnek replacement"]
    assert result["sources"][0]["refresh_status"] == "idle"


@pytest.mark.asyncio
async def test_expired_snapshot_is_not_served_beyond_the_fallback_age(events):
    age = events.settings.events_cache_ttl_seconds + events.settings.events_stale_if_error_seconds + 60
    timestamp = (datetime.now(timezone.utc) - timedelta(seconds=age)).isoformat()
    with connect(events.settings.database_path) as conn:
        conn.execute("UPDATE event_source_snapshots SET refreshed_at=?,last_error='TimeoutError'", (timestamp,))
    result = await events.search(date_from="2030-11-08")
    assert not result["ok"] and result["error"]["code"] == "source_unavailable"
    assert result["sources"][0]["serving_stale"] is False


@pytest.mark.asyncio
async def test_selected_daytime_session_explains_the_window_and_how_to_repair_it(events):
    planner = EventPlanService(events.settings, events=events)
    result = await planner.plan(date="2030-11-08", event_ids=[occurrence().performance_id])
    assert not result["data"][0]["options"]
    assert "18:00–23:59" in result["result_info"]["next_step"]
    assert "start_time/end_time" in result["result_info"]["next_step"]
    repaired = await planner.plan(date="2030-11-08", event_ids=[occurrence().performance_id],
        start_time="09:00", end_time="18:00")
    assert repaired["data"][0]["options"][0]["performances"][0]["performance_id"] == occurrence().performance_id


@pytest.mark.asyncio
async def test_artist_query_does_not_silently_match_a_longer_word(events):
    events.repository.publish("ticketmaster", [occurrence(title="Silahşör Kızı Rabia Hanım")], {})
    assert not (await events.search(query="sıla", date_from="2030-11-08"))["data"]
    related = await events.search(query="sila", match_mode="prefix", date_from="2030-11-08")
    assert related["data"][0]["query_match"] == "prefix_or_venue"
    assert any("not a verified artist" in note for note in related["warnings"])


@pytest.mark.asyncio
async def test_quoted_title_word_matches_without_test_tokenizer_false_alarm(events):
    events.repository.publish("ticketmaster", [occurrence(title="Pinokyo ''Çocuk Tiyatrosu''")], {})
    assert (await events.search(query="çocuk", date_from="2030-11-08"))["data"]


@pytest.mark.asyncio
@pytest.mark.parametrize("identifier", ["event_" + "0" * 24, "perf_" + "0" * 24])
async def test_well_formed_missing_id_is_not_found(events, identifier):
    result = await events.detail(identifier)
    assert not result["ok"] and result["error"]["code"] == "not_found"


@pytest.mark.asyncio
async def test_malformed_id_is_distinct_from_missing_id_and_valid_id_can_be_trimmed(events):
    assert (await events.detail("event_doesnotexist000000"))["error"]["code"] == "validation_error"
    assert (await events.detail("  " + occurrence().performance_id + "  "))["ok"]


@pytest.mark.asyncio
async def test_trimmed_selected_performance_does_not_expand_to_all_series_sessions(events):
    a, b = occurrence("early", hour=10, series_key="same"), occurrence("late", hour=12, series_key="same")
    events.repository.publish("ticketmaster", [a, b], {})
    result = await EventPlanService(events.settings, events=events).plan(date="2030-11-08",
        start_time="09:00", end_time="18:00", event_ids=["  " + b.performance_id + "  "])
    assert result["data"][0]["options"]
    assert all(card["performance_id"] == b.performance_id for option in result["data"][0]["options"] for card in option["performances"])


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["", "   ", "\t"])
async def test_empty_optional_query_behaves_like_an_omitted_filter(events, query):
    result = await events.search(query=query, date_from="2030-11-08")
    omitted = await events.search(date_from="2030-11-08")
    assert result["data"] == omitted["data"]


@pytest.mark.asyncio
async def test_zero_budget_can_be_strict_without_claiming_unknown_prices_are_free(events):
    events.repository.publish("ticketmaster", [occurrence("free", offers=[EventOffer(price=0, currency="TRY")]),
        occurrence("unknown", offers=[])], {})
    normal = await events.search(date_from="2030-11-08", max_price_try=0)
    assert normal["data"][1]["budget_status"] == "unknown"
    strict = await events.search(date_from="2030-11-08", max_price_try=0, include_unknown_prices=False)
    assert len(strict["data"]) == 1 and strict["data"][0]["price"]["minimum_observed_try"] == 0


def test_plan_alternatives_prefer_a_different_anchor_over_same_anchor_variations():
    def option(names, score):
        return {"performances": [event_card(occurrence(name)) for name in names], "score": score, "total_price_known": True}
    a, variation, alternative = option("abc", 250), option("abd", 250), option("efg", 245)
    assert diverse_options([a, variation, alternative], 2) == [a, alternative]


def test_unknown_plan_subtotal_never_becomes_a_full_observed_total():
    a, b = occurrence("known", hour=18), occurrence("unknown", hour=20, offers=[])
    options, _ = enumerate_plans([event_card(a), event_card(b)], window_end=b.end_at, limit=5)
    assert options[0]["total_price_known"]
    partial = next(option for option in options if len(option["performances"]) == 2)
    assert partial["known_minimum_total_try"] == 100
    assert partial["total_observed_minimum_try"] is None and partial["budget_status"] == "unknown"


def test_known_price_session_variant_is_preserved_before_event_set_deduplication():
    unknown = {"performances": [event_card(occurrence("unknown", series_key="same"))],
               "score": 100, "total_price_known": False}
    known = {"performances": [event_card(occurrence("known", series_key="same"))],
             "score": 90, "total_price_known": True}
    assert diverse_options([unknown, known], 1) == [known]


def test_uat_reports_plan_options_instead_of_the_single_enclosing_data_object():
    from scripts.events_100_uat import inspect_case
    a = occurrence(hour=18)
    options, _ = enumerate_plans([event_card(a)], window_end=a.end_at)
    payload = {"ok": True, "data": [{"date": "2030-11-08", "window": {"start": "18:00", "end": "23:59"},
        "options": options, "unverified_budget": [], "rejected": []}]}
    failures, observations = inspect_case({"expect": "ok", "tool": "plan"}, {}, payload)
    assert not failures and observations["returned"] == len(options)
    payload["data"][0]["options"] = []
    assert inspect_case({"expect": "ok", "tool": "plan"}, {}, payload)[1]["returned"] == 0


def test_uat_checks_quoted_words_without_the_original_false_positive():
    from scripts.events_100_uat import inspect_case
    payload = {"ok": True, "data": [event_card(occurrence(title="Pinokyo ''Çocuk Tiyatrosu''"))],
        "result_info": {"matched": 1}}
    failures, _ = inspect_case({"expect": "ok", "tool": "search"}, {"query": "çocuk", "date_from": "2030-11-08"}, payload)
    assert not failures


def test_uat_does_not_accept_an_unexpected_source_error_as_an_expected_validation_error():
    from scripts.events_100_uat import inspect_case
    case = {"expect": "error", "expected_error": "validation_error", "tool": "search"}
    failures, _ = inspect_case(case, {}, {"ok": False, "error": {"code": "source_unavailable"}})
    assert failures == ["unexpected_error:source_unavailable"]
