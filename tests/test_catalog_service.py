import httpx
import pytest

from app.connectors.ckan import CkanClient
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.services.catalog import CatalogService
from app.storage.catalog import CatalogRepository


def _dataset():
    return {
        "id": "dataset-1",
        "name": "trafik-verisi",
        "title": "Trafik Verisi",
        "notes": "Saatlik trafik",
        "license_title": "IBB License",
        "metadata_modified": "2026-06-12T00:00:00",
        "tags": [{"name": "trafik"}],
        "resources": [
            {
                "id": "resource-1",
                "name": "Trafik CSV",
                "format": "CSV",
                "url": "https://example.test/trafik.csv",
                "datastore_active": True,
            }
        ],
    }


class RateLimitedCkan:
    async def package_search(self, **_kwargs):
        raise SourceRateLimitExceeded(source="ckan", retry_after_seconds=1.25)

    async def package_show(self, _dataset_id):
        raise SourceRateLimitExceeded(source="ckan", retry_after_seconds=1.25)

    async def datastore_search(self, **_kwargs):
        raise SourceRateLimitExceeded(source="ckan", retry_after_seconds=1.25)


@pytest.mark.asyncio
async def test_search_datasets_snapshots_results(tmp_path):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"success": True, "result": {"count": 1, "results": [_dataset()]}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        settings = Settings(database_path=tmp_path / "catalog.sqlite3")
        service = CatalogService(
            settings=settings,
            client=CkanClient(base_url="https://example.test/api/3/action", http_client=http_client),
            repository=CatalogRepository(settings.database_path),
        )
        result = await service.search_datasets(query="trafik", limit=5)

    assert result["ok"] is True
    assert result["data"][0]["title"] == "Trafik Verisi"
    assert result["data"][0]["relevance"]["matched_query_terms"] == ["trafik"]
    assert result["data"][0]["relevance"]["has_datastore"] is True
    assert result["data"][0]["preferred_resources"][0]["id"] == "resource-1"
    assert result["freshness"]["status"] == "fresh"


@pytest.mark.asyncio
async def test_query_resource_returns_records(tmp_path):
    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "success": True,
                "result": {
                    "total": 1,
                    "records": [{"ILCE": "Kadikoy"}],
                    "fields": [{"id": "ILCE", "type": "text"}],
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http_client:
        settings = Settings(database_path=tmp_path / "catalog.sqlite3")
        service = CatalogService(
            settings=settings,
            client=CkanClient(base_url="https://example.test/api/3/action", http_client=http_client),
            repository=CatalogRepository(settings.database_path),
        )
        result = await service.query_resource(resource_id="resource-1", filters={"ILCE": "Kadikoy"})

    assert result["data"] == [{"ILCE": "Kadikoy"}]
    assert result["pagination"]["total_estimate"] == 1


@pytest.mark.asyncio
async def test_search_datasets_rate_limit_returns_retry_after_envelope(tmp_path):
    settings = Settings(database_path=tmp_path / "catalog.sqlite3")
    service = CatalogService(
        settings=settings,
        client=RateLimitedCkan(),
        repository=CatalogRepository(settings.database_path),
    )

    result = await service.search_datasets(query="trafik", limit=5)

    assert result["ok"] is False
    assert result["freshness"]["status"] == "stale"
    assert result["data"][0]["source"] == "ckan"
    assert result["data"][0]["retry_after_seconds"] == 1.25


@pytest.mark.asyncio
async def test_search_datasets_limit_validation_returns_envelope(tmp_path):
    settings = Settings(database_path=tmp_path / "catalog.sqlite3", max_limit=10)
    service = CatalogService(
        settings=settings,
        client=RateLimitedCkan(),
        repository=CatalogRepository(settings.database_path),
    )

    result = await service.search_datasets(query="trafik", limit=11)

    assert result["ok"] is False
    assert result["data"][0]["error_code"] == "validation_error"
    assert result["data"][0]["field"] == "limit"
    assert result["data"][0]["allowed_max"] == 10
