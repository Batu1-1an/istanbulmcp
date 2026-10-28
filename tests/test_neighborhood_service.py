import asyncio

import pytest

from app.core.settings import Settings
from app.core.source_cache import clear_source_cache
from app.services.neighborhood import (
    BUILDING_STOCK_RESOURCE_ID,
    EARTHQUAKE_SCENARIO_RESOURCE_ID,
    ISTANBUL_DISTRICTS,
    SOCIAL_ASSISTANCE_RESOURCE_ID,
    NeighborhoodService,
    neighborhood_match_key,
    normalize_neighborhood_text,
    repair_neighborhood_name,
    source_district_filter,
)


def ckan_filter(rows, filters):
    for field, wanted in (filters or {}).items():
        allowed = wanted if isinstance(wanted, list) else [wanted]
        rows = [row for row in rows if row.get(field) in allowed]
    return rows


class FakeCkan:
    def __init__(self):
        self.calls_by_resource: dict[str, int] = {}
        self.filters_by_resource: dict[str, dict] = {}

    async def datastore_search(self, *, resource_id, limit, filters=None, offset=0):
        self.calls_by_resource[resource_id] = self.calls_by_resource.get(resource_id, 0) + 1
        self.filters_by_resource[resource_id] = filters
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
        source_rows = ckan_filter(records.get(resource_id, []) + self.extra_rows(resource_id), filters)
        return {"records": source_rows[:limit], "total": len(source_rows)}

    def extra_rows(self, resource_id):
        return []


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
    assert profile["source_names"]["building_stock"] == "CAFERAĞA"
    assert profile["raw_source_names"]["building_stock"] == "CAFERAÐA"
    assert profile["indicators"]["social_assistance_households_2023"] == 13
    assert profile["indicators"]["buildings_by_age"]["before_1980"] == 100
    assert profile["indicators"]["earthquake_scenario"]["loss_of_life"] == 5
    assert profile["source_record_ids"]["building_stock_uavt"] == "12345"
    assert result["sources"][0]["resource_id"] == SOCIAL_ASSISTANCE_RESOURCE_ID


@pytest.mark.parametrize(("raw", "expected"), [
    ("CAFERAÐA", "CAFERAĞA"),
    ("HEYBELÝADA", "HEYBELİADA"),
    ("PAÞABAHÇE", "PAŞABAHÇE"),
    ("caferaða", "caferağa"),
    ("ýþ", "ış"),
    ("Caferağa", "Caferağa"),
    ("19.May", "19.May"),
])
def test_repair_neighborhood_name_preserves_turkish_display_and_source_abbreviations(raw, expected):
    assert repair_neighborhood_name(raw) == expected


@pytest.mark.asyncio
async def test_neighborhood_display_is_repaired_without_social_source(tmp_path):
    class BuildingOnlyCkan(FakeCkan):
        async def datastore_search(self, *, resource_id, **kwargs):
            if resource_id != BUILDING_STOCK_RESOURCE_ID:
                return {"records": [], "total": 0}
            return await super().datastore_search(resource_id=resource_id, **kwargs)

    svc = service(tmp_path)
    svc.ckan = BuildingOnlyCkan()
    profile = (await svc.profile(district="Kadıköy", neighborhood="Caferağa"))["data"][0]
    district = await svc.profile(district="Kadıköy")

    assert profile["neighborhood"] == "CAFERAĞA"
    assert profile["source_names"]["building_stock"] == "CAFERAĞA"
    assert profile["raw_source_names"]["building_stock"] == "CAFERAÐA"
    assert profile["raw_source_names"]["social_assistance"] is None
    assert "CAFERAĞA" in [row["neighborhood"] for row in district["data"]]


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


@pytest.mark.asyncio
async def test_neighborhood_profile_cache_collapses_concurrent_source_prefetch(tmp_path):
    clear_source_cache()
    fake = FakeCkan()
    svc = NeighborhoodService(settings=Settings(database_path=tmp_path / "neighborhood.sqlite3"), ckan_client=fake)

    results = await asyncio.gather(*(svc.profile(district="Kadıköy", neighborhood="Caferağa") for _ in range(20)))

    assert all(result["ok"] is True for result in results)
    assert fake.calls_by_resource == {
        SOCIAL_ASSISTANCE_RESOURCE_ID: 1,
        BUILDING_STOCK_RESOURCE_ID: 1,
        EARTHQUAKE_SCENARIO_RESOURCE_ID: 1,
    }


class IstanbulCkan(FakeCkan):
    def extra_rows(self, resource_id):
        return {
            SOCIAL_ASSISTANCE_RESOURCE_ID: [
                {"_id": 301, "ILCE": "ŞİŞLİ", "MAHALLE": "GÜLBAHAR", "HANE SAYISI": "153"},
                {"_id": 302, "ILCE": "EYÜPSULTAN", "MAHALLE": "ALİBEYKÖY", "HANE SAYISI": "40"},
                {"_id": 303, "ILCE": "SARIYER", "MAHALLE": "RUMELİHİSARI", "HANE SAYISI": "9"},
                {"_id": 304, "ILCE": "SARIYER", "MAHALLE": "0.0", "HANE SAYISI": "1"},
            ],
            BUILDING_STOCK_RESOURCE_ID: [
                {"_id": 501, "ilce_adi": "ÞÝÞLÝ", "mahalle_adi": "GÜLBAHAR", "mahalle_uavt": "40695", "1980_oncesi": "300"},
                {"_id": 502, "ilce_adi": "EYÜP", "mahalle_adi": "ALÝBEYKÖY", "mahalle_uavt": "40100"},
                {"_id": 503, "ilce_adi": "SARIYER", "mahalle_adi": "RUMELÝ HÝSARI", "mahalle_uavt": "40200"},
            ],
            EARTHQUAKE_SCENARIO_RESOURCE_ID: [
                {
                    "_id": 846, "ilce_adi": "ÞÝÞLÝ", "mahalle_adi": "GÜLBAHAR", "mahalle_koy_uavt": 40695,
                    "cok_agir_hasarli_bina_sayisi": 2, "agir_hasarli_bina_sayisi": 7,
                    "orta_hasarli_bina_sayisi": 37, "hafif_hasarli_bina_sayisi": 176,
                    "can_kaybi_sayisi": 3, "gecici_barinma": 313,
                },
                {"_id": 847, "ilce_adi": "EYÜP", "mahalle_adi": "ALÝBEYKÖY", "mahalle_koy_uavt": 40100, "can_kaybi_sayisi": 4},
                {"_id": 848, "ilce_adi": "SARIYER", "mahalle_adi": "BAHÇEKÖY", "mahalle_koy_uavt": 40300},
            ],
        }.get(resource_id, [])


def istanbul_service(tmp_path, ckan=None):
    clear_source_cache()
    return NeighborhoodService(
        settings=Settings(database_path=tmp_path / "neighborhood.sqlite3"), ckan_client=ckan or IstanbulCkan(),
    )


@pytest.mark.asyncio
async def test_neighborhood_profile_matches_legacy_encoded_district_rows_for_sisli_gulbahar(tmp_path):
    ckan = IstanbulCkan()
    result = await istanbul_service(tmp_path, ckan).profile(district="Şişli", neighborhood="Gülbahar", limit=10)

    assert result["ok"] is True
    profile = result["data"][0]
    assert profile["district"] == "ŞİŞLİ"
    assert profile["coverage"] == {"social_assistance": True, "building_stock": True, "earthquake_scenario": True}
    assert profile["indicators"]["social_assistance_households_2023"] == 153
    assert profile["indicators"]["earthquake_scenario"] == {
        "very_heavy_damaged_buildings": 2, "heavy_damaged_buildings": 7, "moderate_damaged_buildings": 37,
        "light_damaged_buildings": 176, "loss_of_life": 3, "temporary_shelter": 313,
    }
    assert profile["source_record_ids"]["earthquake_scenario"] == 846
    assert profile["source_record_ids"]["earthquake_uavt"] == 40695
    assert ckan.filters_by_resource[EARTHQUAKE_SCENARIO_RESOURCE_ID] == {"ilce_adi": ["ŞİŞLİ", "ÞÝÞLÝ"]}
    assert not any("returned no rows" in w or "matched this neighborhood" in w for w in result["warnings"])


@pytest.mark.asyncio
@pytest.mark.parametrize("neighborhood", ["Gülbahar Mahallesi", "gulbahar mah.", "GÜLBAHAR MH"])
async def test_neighborhood_profile_accepts_mahalle_suffixes(tmp_path, neighborhood):
    result = await istanbul_service(tmp_path).profile(district="Sisli", neighborhood=neighborhood)

    assert result["ok"] is True
    assert result["data"][0]["coverage"]["earthquake_scenario"] is True


@pytest.mark.asyncio
async def test_neighborhood_profile_queries_eyup_alias_for_eyupsultan(tmp_path):
    ckan = IstanbulCkan()
    result = await istanbul_service(tmp_path, ckan).profile(district="Eyüpsultan", neighborhood="Alibeyköy")

    profile = result["data"][0]
    assert profile["district"] == "EYÜPSULTAN"
    assert profile["coverage"] == {"social_assistance": True, "building_stock": True, "earthquake_scenario": True}
    assert profile["indicators"]["earthquake_scenario"]["loss_of_life"] == 4
    assert "EYÜP" in ckan.filters_by_resource[BUILDING_STOCK_RESOURCE_ID]["ilce_adi"]


@pytest.mark.asyncio
async def test_neighborhood_profile_joins_spacing_variants_and_warns_about_unmatched_source(tmp_path):
    svc = istanbul_service(tmp_path)
    result = await svc.profile(district="Sarıyer", neighborhood="Rumeli Hisarı")
    listing = await svc.profile(district="Sarıyer")

    profile = result["data"][0]
    assert profile["coverage"] == {"social_assistance": True, "building_stock": True, "earthquake_scenario": False}
    assert profile["indicators"]["earthquake_scenario"]["loss_of_life"] is None
    unmatched = [w for w in result["warnings"] if "No earthquake scenario record matched" in w]
    assert len(unmatched) == 1
    assert "does not prove the source lacks it" in unmatched[0] and EARTHQUAKE_SCENARIO_RESOURCE_ID in unmatched[0]
    assert [row["neighborhood"] for row in listing["data"]] == ["BAHÇEKÖY", "RUMELİHİSARI"]


@pytest.mark.asyncio
async def test_neighborhood_profile_reports_empty_district_source_as_unchecked(tmp_path):
    class NoEarthquakeCkan(FakeCkan):
        async def datastore_search(self, *, resource_id, **kwargs):
            if resource_id == EARTHQUAKE_SCENARIO_RESOURCE_ID:
                return {"records": [], "total": 0}
            return await super().datastore_search(resource_id=resource_id, **kwargs)

    for neighborhood in ("Caferağa", None):
        result = await istanbul_service(tmp_path, NoEarthquakeCkan()).profile(district="Kadıköy", neighborhood=neighborhood)
        assert result["ok"] is True
        assert any("earthquake scenario source returned no rows for KADIKÖY" in w and "unchecked" in w
                   for w in result["warnings"])


@pytest.mark.parametrize("district", ISTANBUL_DISTRICTS)
def test_district_filter_includes_legacy_encoding_for_every_district(district):
    value = source_district_filter(district)
    values = value if isinstance(value, list) else [value]

    assert district in values
    assert district.encode("iso-8859-9").decode("latin-1") in values
    assert isinstance(value, str) is (district.encode("iso-8859-9").decode("latin-1") == district and district != "EYÜPSULTAN")


@pytest.mark.parametrize(("left", "right"), [
    ("ORTA", "ORTAMAHALLE"),
    ("RUMELİHİSARI", "RUMELÝ HÝSARI"),
    ("KÜÇÜK ÇAMLICA", "KÜÇÜKÇAMLICA"),
    ("Gülbahar Mah.", "GÜLBAHAR"),
])
def test_neighborhood_match_key_joins_source_spelling_variants(left, right):
    assert neighborhood_match_key(normalize_neighborhood_text(left)) == neighborhood_match_key(normalize_neighborhood_text(right))
