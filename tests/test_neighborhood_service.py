import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.neighborhood import (
    BUILDING_STOCK_RESOURCE_ID,
    EARTHQUAKE_SCENARIO_RESOURCE_ID,
    SOCIAL_ASSISTANCE_RESOURCE_ID,
    NeighborhoodService,
    normalize_neighborhood_text,
)


class FakeCkan:
    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        records = {
            SOCIAL_ASSISTANCE_RESOURCE_ID: [
                {"_id": 1, "ILCE": "KADIKÖY", "MAHALLE": "CAFERAĞA", "HANE SAYISI": "13"},
                {"_id": 2, "ILCE": "KADIKÖY", "MAHALLE": "19 MAYIS", "HANE SAYISI": "18"},
            ],
            BUILDING_STOCK_RESOURCE_ID: [
                {
                    "_id": 11,
                    "ilce_adi": "KADIKÖY",
                    "mahalle_adi": "CAFERAÐA",
                    "mahalle_uavt": "12345",
                    "1980_oncesi": "100",
                    "1980-2000_arasi": "120",
                    "2000_sonrasi": "90",
                    "1-4 kat_arasi": "80",
                    "5-9 kat_arasi": "200",
                    "9-19 kat_arasi": "30",
                },
                {
                    "_id": 12,
                    "ilce_adi": "KADIKÖY",
                    "mahalle_adi": "19.May",
                    "mahalle_uavt": "19000",
                    "1980_oncesi": "50",
                    "1980-2000_arasi": "60",
                    "2000_sonrasi": "70",
                    "1-4 kat_arasi": "40",
                    "5-9 kat_arasi": "80",
                    "9-19 kat_arasi": "15",
                },
            ],
            EARTHQUAKE_SCENARIO_RESOURCE_ID: [
                {
                    "_id": 21,
                    "ilce_adi": "KADIKÖY",
                    "mahalle_adi": "CAFERAĞA",
                    "mahalle_koy_uavt": "12345",
                    "cok_agir_hasarli_bina_sayisi": "1",
                    "agir_hasarli_bina_sayisi": "2",
                    "orta_hasarli_bina_sayisi": "3",
                    "hafif_hasarli_bina_sayisi": "4",
                    "can_kaybi_sayisi": "5",
                    "gecici_barinma": "6",
                },
                {
                    "_id": 22,
                    "ilce_adi": "KADIKÖY",
                    "mahalle_adi": "19 MAYIS",
                    "mahalle_koy_uavt": "19000",
                    "cok_agir_hasarli_bina_sayisi": "0",
                    "agir_hasarli_bina_sayisi": "1",
                    "orta_hasarli_bina_sayisi": "2",
                    "hafif_hasarli_bina_sayisi": "3",
                    "can_kaybi_sayisi": "4",
                    "gecici_barinma": "5",
                },
            ],
        }
        source_rows = records.get(resource_id, [])
        return {"records": source_rows[:limit], "total": len(source_rows)}


def service(tmp_path):
    clear_source_cache()
    return NeighborhoodService(settings=Settings(database_path=tmp_path / "neighborhood.sqlite3"), ckan_client=FakeCkan())


def test_normalize_neighborhood_text_handles_turkish_mojibake_and_abbreviations():
    assert normalize_neighborhood_text("CAFERAÐA") == normalize_neighborhood_text("Caferağa")
    assert normalize_neighborhood_text("HEYBELÝADA") == normalize_neighborhood_text("Heybeliada")
    assert normalize_neighborhood_text("19.May") == normalize_neighborhood_text("19 MAYIS")


@pytest.mark.asyncio
async def test_neighborhood_profile_joins_sources_with_encoding_variants(tmp_path):
    result = await service(tmp_path).profile(district="Kadikoy", neighborhood="Caferağa")

    assert result["ok"] is True
    profile = result["data"][0]
    assert profile["district"] == "KADIKÖY"
    assert profile["neighborhood"] == "CAFERAĞA"
    assert profile["coverage"] == {
        "social_assistance": True,
        "building_stock": True,
        "earthquake_scenario": True,
    }
    assert profile["source_names"]["building_stock"] == "CAFERAÐA"
    assert profile["indicators"]["social_assistance_households_2023"] == 13
    assert profile["indicators"]["buildings_by_age"]["before_1980"] == 100
    assert profile["indicators"]["earthquake_scenario"]["loss_of_life"] == 5
    assert profile["source_record_ids"]["building_stock_uavt"] == "12345"
    assert result["sources"][0]["resource_id"] == SOCIAL_ASSISTANCE_RESOURCE_ID


@pytest.mark.asyncio
async def test_neighborhood_profile_handles_19_may_source_abbreviation(tmp_path):
    result = await service(tmp_path).profile(district="KADIKÖY", neighborhood="19 Mayıs")

    assert result["ok"] is True
    profile = result["data"][0]
    assert profile["neighborhood"] == "19 MAYIS"
    assert profile["coverage"]["building_stock"] is True
    assert profile["source_names"]["building_stock"] == "19.May"


@pytest.mark.asyncio
async def test_neighborhood_profile_lists_district_candidates(tmp_path):
    result = await service(tmp_path).profile(district="Kadıköy", limit=1)

    assert result["ok"] is True
    assert len(result["data"]) == 1
    assert result["pagination"]["limit"] == 1
    assert result["pagination"]["total_estimate"] == 2
    assert result["data"][0]["coverage"]["earthquake_scenario"] is True


@pytest.mark.asyncio
async def test_neighborhood_profile_unknown_neighborhood_returns_validation_envelope(tmp_path):
    result = await service(tmp_path).profile(district="Kadıköy", neighborhood="Yok Mahallesi")

    assert result["ok"] is False
    assert result["data"][0]["field"] == "neighborhood"
    assert "Known examples" in result["summary"]
