from __future__ import annotations

import json
from typing import Any

from app.connectors.ckan import CkanClient
from app.core.envelope import Freshness, Pagination, Source, error_envelope, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import cached_source_data
from app.core.validation import InputValidationError, validate_limit
from app.storage.catalog import CatalogRepository

IBB_SOURCE = Source(
    name="IBB Open Data Portal",
    publisher="Istanbul Metropolitan Municipality",
    url="https://data.ibb.gov.tr",
)


class CatalogService:
    def __init__(
        self,
        *,
        settings: Settings,
        client: CkanClient | None = None,
        repository: CatalogRepository | None = None,
    ):
        self.settings = settings
        self.client = client or CkanClient(timeout=settings.request_timeout_seconds)
        self.repository = repository or CatalogRepository(settings.database_path)

    async def search_datasets(
        self,
        *,
        query: str,
        formats: list[str] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IBB_SOURCE])
        try:
            result = await self._cached_package_search(query=query, rows=safe_limit, formats=formats)
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("CKAN package_search", exc)
        except Exception as exc:
            return self._source_error("CKAN package search is unavailable.", exc)
        datasets = result.get("results", [])
        for dataset in datasets:
            self.repository.upsert_dataset(dataset)
        data = sorted(
            [self._dataset_summary(dataset, query=query) for dataset in datasets],
            key=lambda item: item["relevance"]["score"],
            reverse=True,
        )
        return success_envelope(
            summary=f"{len(data)} dataset result(s) found for '{query}'.",
            data=data,
            sources=[IBB_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            pagination=Pagination(limit=safe_limit, total_estimate=result.get("count")),
            limits=[f"limit={safe_limit}", "source=CKAN package_search"],
        )

    async def get_dataset(self, dataset_id: str) -> dict[str, Any]:
        try:
            dataset = await self._cached_package_show(dataset_id)
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("CKAN package_show", exc)
        except Exception as exc:
            return self._source_error(f"CKAN dataset metadata is unavailable for {dataset_id}.", exc)
        self.repository.upsert_dataset(dataset)
        return success_envelope(
            summary=f"Dataset '{dataset.get('title') or dataset_id}' metadata retrieved.",
            data=[self._dataset_detail(dataset)],
            sources=[IBB_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["source=CKAN package_show"],
        )

    async def get_resource_schema(self, resource_id: str) -> dict[str, Any]:
        try:
            result = await self._cached_datastore_search(resource_id=resource_id, limit=0)
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("CKAN datastore_search", exc)
        except Exception as exc:
            return self._source_error(f"CKAN resource schema is unavailable for {resource_id}.", exc)
        fields = result.get("fields", [])
        return success_envelope(
            summary=f"Resource '{resource_id}' schema has {len(fields)} field(s).",
            data=[{"resource_id": resource_id, "fields": fields}],
            sources=[IBB_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            limits=["source=CKAN datastore_search", "limit=0"],
        )

    async def query_resource(
        self,
        *,
        resource_id: str,
        filters: dict[str, Any] | None = None,
        limit: int | None = None,
    ) -> dict[str, Any]:
        try:
            safe_limit = validate_limit(limit or self.settings.default_limit, self.settings.max_limit)
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[IBB_SOURCE])
        try:
            result = await self._cached_datastore_search(
                resource_id=resource_id,
                filters=filters,
                limit=safe_limit,
            )
        except SourceRateLimitExceeded as exc:
            return self._rate_limited("CKAN datastore_search", exc)
        except Exception as exc:
            return self._source_error(f"CKAN resource query is unavailable for {resource_id}.", exc)
        records = result.get("records", [])
        return success_envelope(
            summary=f"{len(records)} record(s) returned from resource '{resource_id}'.",
            data=records,
            sources=[IBB_SOURCE],
            freshness=Freshness(status="fresh", ttl_seconds=60 * 60 * 6),
            pagination=Pagination(limit=safe_limit, total_estimate=result.get("total")),
            limits=[f"limit={safe_limit}", "source=CKAN datastore_search", "filters only"],
        )

    async def _cached_package_search(self, *, query: str, rows: int, formats: list[str] | None) -> dict[str, Any]:
        normalized_formats = sorted({fmt.upper() for fmt in formats or []})
        key = _cache_key("ckan.package_search", {"query": query.strip(), "rows": rows, "formats": normalized_formats})
        return await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds,
            loader=lambda: self.client.package_search(query=query, rows=rows, formats=normalized_formats or None),
        )

    async def _cached_package_show(self, dataset_id: str) -> dict[str, Any]:
        key = _cache_key("ckan.package_show", {"dataset_id": dataset_id.strip()})
        return await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_catalog_cache_ttl_seconds,
            loader=lambda: self.client.package_show(dataset_id),
        )

    async def _cached_datastore_search(
        self,
        *,
        resource_id: str,
        limit: int,
        filters: dict[str, Any] | None = None,
        offset: int = 0,
    ) -> dict[str, Any]:
        key = _cache_key(
            "ckan.datastore_search",
            {
                "resource_id": resource_id.strip(),
                "limit": limit,
                "filters": filters or {},
                "offset": offset,
            },
        )
        return await cached_source_data(
            key,
            ttl_seconds=self.settings.ckan_resource_cache_ttl_seconds,
            loader=lambda: self.client.datastore_search(resource_id=resource_id, limit=limit, filters=filters, offset=offset),
        )

    def _dataset_summary(self, dataset: dict[str, Any], *, query: str | None = None) -> dict[str, Any]:
        resources = dataset.get("resources") or []
        datastore_resources = [resource for resource in resources if resource.get("datastore_active")]
        return {
            "id": dataset.get("id"),
            "slug": dataset.get("name"),
            "title": dataset.get("title"),
            "notes": dataset.get("notes"),
            "license": dataset.get("license_title") or dataset.get("license_id"),
            "metadata_modified": dataset.get("metadata_modified"),
            "formats": sorted({(r.get("format") or "").upper() for r in resources if r.get("format")}),
            "resource_count": len(resources),
            "datastore_active_count": len(datastore_resources),
            "preferred_resources": [
                {
                    "id": resource.get("id"),
                    "name": resource.get("name") or resource.get("description"),
                    "format": (resource.get("format") or "").upper(),
                    "datastore_active": bool(resource.get("datastore_active")),
                }
                for resource in datastore_resources[:3]
            ],
            "relevance": self._relevance(dataset, query),
        }

    def _dataset_detail(self, dataset: dict[str, Any]) -> dict[str, Any]:
        detail = self._dataset_summary(dataset)
        detail["resources"] = [
            {
                "id": resource.get("id"),
                "name": resource.get("name") or resource.get("description"),
                "format": (resource.get("format") or "").upper(),
                "url": resource.get("url"),
                "datastore_active": bool(resource.get("datastore_active")),
            }
            for resource in dataset.get("resources", [])
        ]
        return detail

    def _relevance(self, dataset: dict[str, Any], query: str | None) -> dict[str, Any]:
        terms = [term.casefold() for term in (query or "").split() if term.strip()]
        haystack_parts = [
            dataset.get("title") or "",
            dataset.get("name") or "",
            dataset.get("notes") or "",
            " ".join(tag.get("name", "") for tag in dataset.get("tags", []) if isinstance(tag, dict)),
        ]
        haystack = " ".join(haystack_parts).casefold()
        matched_terms = [term for term in terms if term in haystack]
        datastore_bonus = 2 if any(resource.get("datastore_active") for resource in dataset.get("resources", [])) else 0
        score = len(matched_terms) + datastore_bonus
        return {
            "score": score,
            "matched_query_terms": matched_terms,
            "has_datastore": datastore_bonus > 0,
        }

    def _rate_limited(self, action: str, exc: SourceRateLimitExceeded) -> dict[str, Any]:
        retry_after = round(exc.retry_after_seconds, 3)
        return error_envelope(
            summary=f"{action} is temporarily rate limited.",
            warning=f"Local back-pressure is active for {exc.source}; retry after {retry_after} seconds.",
            sources=[IBB_SOURCE],
            freshness_status="stale",
            data=[{"source": exc.source, "retry_after_seconds": retry_after}],
            limits=[f"rate_limited_source={exc.source}", f"retry_after_seconds={retry_after}"],
        )

    def _source_error(self, summary: str, exc: Exception) -> dict[str, Any]:
        return source_error_envelope(
            summary=summary,
            warning=f"CKAN source request failed: {type(exc).__name__}",
            sources=[IBB_SOURCE],
            exception=exc,
        )


def _cache_key(prefix: str, payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"{prefix}.{encoded}"
