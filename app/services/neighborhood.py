from __future__ import annotations

import asyncio
import re
import unicodedata
from collections import defaultdict
from typing import Any

from app.connectors.ckan import CkanClient
from app.core.envelope import Freshness, Pagination, Source, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, validate_limit

SOCIAL_ASSISTANCE_DATASET_ID = "1f92165c-d8f4-4020-a858-3fd9cf6d00b7"
SOCIAL_ASSISTANCE_RESOURCE_ID = "af59d08d-7e7d-4404-98be-4adc7d2857f9"
BUILDING_STOCK_DATASET_ID = "be3582eb-09d7-42f8-84d3-b3817dc9ab0a"
BUILDING_STOCK_RESOURCE_ID = "cef193d5-0bd2-4e8d-8a69-275c50288875"
EARTHQUAKE_SCENARIO_DATASET_ID = "c13514d9-86b1-4b83-a9b9-1a15cb5f254c"
EARTHQUAKE_SCENARIO_RESOURCE_ID = "9c3ac492-de4b-4245-b418-7ad3df67a193"

NEIGHBORHOOD_PREFETCH_LIMIT = 2000
NEIGHBORHOOD_CACHE_TTL_SECONDS = 60 * 60 * 24

NEIGHBORHOOD_SOURCES = [
    Source(
        name="IBB Open Data Portal - Social assistance households 2023",
        dataset_id=SOCIAL_ASSISTANCE_DATASET_ID,
        resource_id=SOCIAL_ASSISTANCE_RESOURCE_ID,
        url="https://data.ibb.gov.tr",
    ),
    Source(
        name="IBB Open Data Portal - Neighborhood building stock",
        dataset_id=BUILDING_STOCK_DATASET_ID,
        resource_id=BUILDING_STOCK_RESOURCE_ID,
        url="https://data.ibb.gov.tr",
    ),
    Source(
        name="IBB Open Data Portal - Earthquake scenario by neighborhood",
        dataset_id=EARTHQUAKE_SCENARIO_DATASET_ID,
        resource_id=EARTHQUAKE_SCENARIO_RESOURCE_ID,
        url="https://data.ibb.gov.tr",
    ),
]


class NeighborhoodService:
    def __init__(self, *, settings: Settings, ckan_client: CkanClient | None = None):
        self.settings = settings
        self.ckan = ckan_client or CkanClient(timeout=settings.request_timeout_seconds)

    async def profile(self, *, district: str, neighborhood: str | None = None, limit: int | None = None) -> dict[str, Any]:
        try:
            if not district or not district.strip():
                raise InputValidationError("district is required", field="district")
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
            rows = await self._all_source_rows()
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=NEIGHBORHOOD_SOURCES)
        except Exception as exc:
            return source_error_envelope(
                summary="Neighborhood profile sources are unavailable.",
                warning=f"CKAN neighborhood source request failed: {type(exc).__name__}",
                sources=NEIGHBORHOOD_SOURCES,
                exception=exc,
            )

        district_key = normalize_neighborhood_text(district)
        index = self._index_rows(rows)
        district_entries = index.get(district_key)
        if not district_entries:
            return validation_error_envelope(
                InputValidationError(
                    f"Unknown district for neighborhood profile. Known examples: {', '.join(self._district_examples(index))}",
                    field="district",
                ),
                sources=NEIGHBORHOOD_SOURCES,
            )

        if neighborhood and neighborhood.strip():
            return self._single_profile(
                district_query=district,
                neighborhood_query=neighborhood,
                district_entries=district_entries,
            )
        return self._district_list(district_query=district, district_entries=district_entries, limit=safe_limit)

    async def _all_source_rows(self) -> dict[str, list[dict[str, Any]]]:
        async def load_social() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=SOCIAL_ASSISTANCE_RESOURCE_ID, limit=NEIGHBORHOOD_PREFETCH_LIMIT)
            return result.get("records", [])

        async def load_buildings() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=BUILDING_STOCK_RESOURCE_ID, limit=NEIGHBORHOOD_PREFETCH_LIMIT)
            return result.get("records", [])

        async def load_earthquake() -> list[dict[str, Any]]:
            result = await self.ckan.datastore_search(resource_id=EARTHQUAKE_SCENARIO_RESOURCE_ID, limit=NEIGHBORHOOD_PREFETCH_LIMIT)
            return result.get("records", [])

        social_assistance, building_stock, earthquake_scenario = await asyncio.gather(
            cached_source_data(
                "ckan.neighborhood.social_assistance",
                ttl_seconds=NEIGHBORHOOD_CACHE_TTL_SECONDS,
                loader=load_social,
            ),
            cached_source_data(
                "ckan.neighborhood.building_stock",
                ttl_seconds=NEIGHBORHOOD_CACHE_TTL_SECONDS,
                loader=load_buildings,
            ),
            cached_source_data(
                "ckan.neighborhood.earthquake_scenario",
                ttl_seconds=NEIGHBORHOOD_CACHE_TTL_SECONDS,
                loader=load_earthquake,
            ),
        )

        return {
            "social_assistance": social_assistance,
            "building_stock": building_stock,
            "earthquake_scenario": earthquake_scenario,
        }

    def _index_rows(self, rows: dict[str, list[dict[str, Any]]]) -> dict[str, dict[str, dict[str, dict[str, Any]]]]:
        index: dict[str, dict[str, dict[str, dict[str, Any]]]] = defaultdict(lambda: defaultdict(dict))
        for row in rows["social_assistance"]:
            district_key = normalize_neighborhood_text(row.get("ILCE"))
            neighborhood_key = normalize_neighborhood_text(row.get("MAHALLE"))
            if district_key and neighborhood_key:
                index[district_key][neighborhood_key]["social_assistance"] = row
        for row in rows["building_stock"]:
            district_key = normalize_neighborhood_text(row.get("ilce_adi"))
            neighborhood_key = normalize_neighborhood_text(row.get("mahalle_adi"))
            if district_key and neighborhood_key:
                index[district_key][neighborhood_key]["building_stock"] = row
        for row in rows["earthquake_scenario"]:
            district_key = normalize_neighborhood_text(row.get("ilce_adi"))
            neighborhood_key = normalize_neighborhood_text(row.get("mahalle_adi"))
            if district_key and neighborhood_key:
                index[district_key][neighborhood_key]["earthquake_scenario"] = row
        return index

    def _single_profile(
        self,
        *,
        district_query: str,
        neighborhood_query: str,
        district_entries: dict[str, dict[str, dict[str, Any]]],
    ) -> dict[str, Any]:
        neighborhood_key = normalize_neighborhood_text(neighborhood_query)
        rows = district_entries.get(neighborhood_key)
        if not rows:
            examples = ", ".join(self._neighborhood_examples(district_entries))
            return validation_error_envelope(
                InputValidationError(
                    f"Unknown neighborhood for this district. Known examples: {examples}",
                    field="neighborhood",
                ),
                sources=NEIGHBORHOOD_SOURCES,
            )

        profile = self._profile_payload(
            district_query=district_query,
            neighborhood_query=neighborhood_query,
            neighborhood_key=neighborhood_key,
            rows=rows,
        )
        return success_envelope(
            summary=f"Neighborhood profile found for {profile['district']} / {profile['neighborhood']}.",
            data=[profile],
            sources=NEIGHBORHOOD_SOURCES,
            freshness=Freshness(status="fresh", ttl_seconds=NEIGHBORHOOD_CACHE_TTL_SECONDS),
            limits=[
                "source=CKAN datastore_search",
                f"prefetch_limit_per_resource={NEIGHBORHOOD_PREFETCH_LIMIT}",
                "read_only=true",
            ],
            warnings=self._warnings(),
            next_queries=[
                "Omit neighborhood to list covered neighborhoods for a district.",
                "Use istanbul_query_resource for raw source rows when exact field-level inspection is needed.",
            ],
        )

    def _district_list(
        self,
        *,
        district_query: str,
        district_entries: dict[str, dict[str, dict[str, Any]]],
        limit: int,
    ) -> dict[str, Any]:
        profiles = [
            self._district_row(neighborhood_key=neighborhood_key, rows=rows)
            for neighborhood_key, rows in district_entries.items()
        ]
        profiles.sort(key=lambda row: row["neighborhood"])
        district_name = self._display_district(district_entries) or district_query.strip()
        data = profiles[:limit]
        return success_envelope(
            summary=f"{len(data)} neighborhood profile candidate(s) returned for {district_name}.",
            data=data,
            sources=NEIGHBORHOOD_SOURCES,
            freshness=Freshness(status="fresh", ttl_seconds=NEIGHBORHOOD_CACHE_TTL_SECONDS),
            pagination=Pagination(limit=limit, total_estimate=len(profiles)),
            limits=[
                f"limit={limit}",
                "source=CKAN datastore_search",
                f"prefetch_limit_per_resource={NEIGHBORHOOD_PREFETCH_LIMIT}",
            ],
            warnings=self._warnings(),
            next_queries=["Pass one returned neighborhood name to get the joined profile."],
        )

    def _profile_payload(
        self,
        *,
        district_query: str,
        neighborhood_query: str,
        neighborhood_key: str,
        rows: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        social = rows.get("social_assistance")
        building = rows.get("building_stock")
        earthquake = rows.get("earthquake_scenario")
        return {
            "query": {
                "district": district_query,
                "neighborhood": neighborhood_query,
                "normalized_district": normalize_neighborhood_text(district_query),
                "normalized_neighborhood": neighborhood_key,
            },
            "district": self._first_present(
                social,
                "ILCE",
                building,
                "ilce_adi",
                earthquake,
                "ilce_adi",
                fallback=district_query.strip(),
            ),
            "neighborhood": self._first_present(
                social,
                "MAHALLE",
                earthquake,
                "mahalle_adi",
                building,
                "mahalle_adi",
                fallback=neighborhood_query.strip(),
            ),
            "coverage": {
                "social_assistance": social is not None,
                "building_stock": building is not None,
                "earthquake_scenario": earthquake is not None,
            },
            "source_names": {
                "social_assistance": self._row_name(social, "MAHALLE"),
                "building_stock": self._row_name(building, "mahalle_adi"),
                "earthquake_scenario": self._row_name(earthquake, "mahalle_adi"),
            },
            "indicators": {
                "social_assistance_households_2023": _int_or_none(social.get("HANE SAYISI") if social else None),
                "buildings_by_age": {
                    "before_1980": _int_or_none(building.get("1980_oncesi") if building else None),
                    "between_1980_2000": _int_or_none(building.get("1980-2000_arasi") if building else None),
                    "after_2000": _int_or_none(building.get("2000_sonrasi") if building else None),
                },
                "buildings_by_floor_count": {
                    "1_4_floors": _int_or_none(building.get("1-4 kat_arasi") if building else None),
                    "5_9_floors": _int_or_none(building.get("5-9 kat_arasi") if building else None),
                    "9_19_floors": _int_or_none(building.get("9-19 kat_arasi") if building else None),
                },
                "earthquake_scenario": {
                    "very_heavy_damaged_buildings": _int_or_none(earthquake.get("cok_agir_hasarli_bina_sayisi") if earthquake else None),
                    "heavy_damaged_buildings": _int_or_none(earthquake.get("agir_hasarli_bina_sayisi") if earthquake else None),
                    "moderate_damaged_buildings": _int_or_none(earthquake.get("orta_hasarli_bina_sayisi") if earthquake else None),
                    "light_damaged_buildings": _int_or_none(earthquake.get("hafif_hasarli_bina_sayisi") if earthquake else None),
                    "loss_of_life": _int_or_none(earthquake.get("can_kaybi_sayisi") if earthquake else None),
                    "temporary_shelter": _int_or_none(earthquake.get("gecici_barinma") if earthquake else None),
                },
            },
            "source_record_ids": {
                "social_assistance": social.get("_id") if social else None,
                "building_stock": building.get("_id") if building else None,
                "earthquake_scenario": earthquake.get("_id") if earthquake else None,
                "building_stock_uavt": building.get("mahalle_uavt") if building else None,
                "earthquake_uavt": earthquake.get("mahalle_koy_uavt") if earthquake else None,
            },
        }

    def _district_row(self, *, neighborhood_key: str, rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        social = rows.get("social_assistance")
        building = rows.get("building_stock")
        earthquake = rows.get("earthquake_scenario")
        district = self._first_present(social, "ILCE", building, "ilce_adi", earthquake, "ilce_adi", fallback="")
        neighborhood = self._first_present(social, "MAHALLE", earthquake, "mahalle_adi", building, "mahalle_adi", fallback=neighborhood_key)
        return {
            "district": district,
            "neighborhood": neighborhood,
            "normalized_neighborhood": neighborhood_key,
            "coverage": {
                "social_assistance": social is not None,
                "building_stock": building is not None,
                "earthquake_scenario": earthquake is not None,
            },
            "social_assistance_households_2023": _int_or_none(social.get("HANE SAYISI") if social else None),
            "building_stock_uavt": building.get("mahalle_uavt") if building else None,
            "earthquake_uavt": earthquake.get("mahalle_koy_uavt") if earthquake else None,
        }

    def _display_district(self, district_entries: dict[str, dict[str, dict[str, Any]]]) -> str | None:
        for rows in district_entries.values():
            value = self._first_present(rows.get("social_assistance"), "ILCE", rows.get("building_stock"), "ilce_adi", rows.get("earthquake_scenario"), "ilce_adi")
            if value:
                return value
        return None

    def _district_examples(self, index: dict[str, dict[str, dict[str, dict[str, Any]]]]) -> list[str]:
        names = []
        for entries in index.values():
            display = self._display_district(entries)
            if display and display not in names:
                names.append(display)
            if len(names) >= 8:
                break
        return names

    def _neighborhood_examples(self, district_entries: dict[str, dict[str, dict[str, Any]]]) -> list[str]:
        return [self._district_row(neighborhood_key=key, rows=rows)["neighborhood"] for key, rows in sorted(district_entries.items())[:8]]

    def _first_present(self, *args: Any, fallback: str | None = None) -> str | None:
        for row, key in zip(args[0::2], args[1::2], strict=False):
            if isinstance(row, dict):
                value = row.get(key)
                if value not in (None, ""):
                    return str(value)
        return fallback

    def _row_name(self, row: dict[str, Any] | None, key: str) -> str | None:
        if not row:
            return None
        value = row.get(key)
        return str(value) if value not in (None, "") else None

    def _warnings(self) -> list[str]:
        return [
            "Neighborhood names are normalized across Turkish and source-encoding variants.",
            "Earthquake scenario values are source scenario records, not real-time risk, incident, or guidance data.",
        ]


def normalize_neighborhood_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold()
    text = text.translate(
        str.maketrans(
            {
                "ı": "i",
                "ö": "o",
                "ü": "u",
                "ş": "s",
                "ğ": "g",
                "ç": "c",
                "ý": "i",
                "ð": "g",
                "þ": "s",
                "Ð": "g",
                "Ý": "i",
                "Þ": "s",
            }
        )
    )
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    text = re.sub(r"[^0-9a-z]+", " ", text)
    text = " ".join(text.split())
    if text.endswith(" may"):
        text = f"{text}is"
    return text


def _int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return None
