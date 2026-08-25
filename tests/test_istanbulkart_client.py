import json
from pathlib import Path

import pytest

from app.connectors.istanbulkart import (
    IstanbulkartClient,
    IstanbulkartPayloadError,
    IstanbulkartPaginationError,
    IstanbulkartSchemaError,
)


FIXTURES = Path(__file__).parent / "fixtures" / "istanbulkart"


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


class FakeCkan:
    def __init__(self, package, pages):
        self.package = package
        self.pages = pages
        self.package_calls = []
        self.datastore_calls = []

    async def package_show(self, dataset_id):
        self.package_calls.append(dataset_id)
        return self.package

    async def datastore_search(self, *, resource_id, limit, offset=0, filters=None):
        self.datastore_calls.append((resource_id, limit, offset))
        return self.pages[offset]


@pytest.mark.asyncio
async def test_selects_newest_supported_resource_and_reads_pages():
    package = load_fixture("package_show.json")["result"]
    fake = FakeCkan(
        package,
        {
            0: load_fixture("datastore_page_1.json")["result"],
            2: load_fixture("datastore_page_2.json")["result"],
        },
    )
    client = IstanbulkartClient(ckan_client=fake, page_size=2)

    payload = await client.fetch()

    assert fake.package_calls == ["istanbulkart-dolum-merkezi-bilgileri"]
    assert [call[2] for call in fake.datastore_calls] == [0, 2]
    assert payload.resource_id == "a40d07e1-5464-4c0d-b4fd-ff37c40ba162"
    assert payload.resource_year == 2025
    assert payload.reported_total == 4
    assert len(payload.rows) == 4
    assert "latitude" in payload.schema_fields


@pytest.mark.asyncio
async def test_resource_override_is_honored():
    package = load_fixture("package_show.json")["result"]
    fake = FakeCkan(
        package,
        {0: load_fixture("datastore_page_1.json")["result"], 2: load_fixture("datastore_page_2.json")["result"]},
    )
    client = IstanbulkartClient(
        ckan_client=fake,
        resource_id="a40d07e1-5464-4c0d-b4fd-ff37c40ba162",
        page_size=2,
    )

    payload = await client.fetch()

    assert payload.resource_id == "a40d07e1-5464-4c0d-b4fd-ff37c40ba162"


@pytest.mark.asyncio
async def test_unsupported_schema_is_rejected():
    package = load_fixture("package_show.json")["result"]
    old_schema = {
        "total": 1,
        "fields": [{"id": "old_name", "type": "text"}],
        "records": [{"old_name": "legacy"}],
    }
    fake = FakeCkan(package, {0: old_schema})
    client = IstanbulkartClient(
        ckan_client=fake,
        resource_id="a40d07e1-5464-4c0d-b4fd-ff37c40ba162",
    )

    with pytest.raises(IstanbulkartSchemaError):
        await client.fetch()


@pytest.mark.asyncio
async def test_incomplete_page_raises_pagination_error():
    package = load_fixture("package_show.json")["result"]
    first = load_fixture("datastore_page_1.json")["result"]
    partial = dict(first)
    partial["total"] = 4
    partial["records"] = first["records"][:1]
    fake = FakeCkan(package, {0: partial, 1: {**partial, "records": []}})
    client = IstanbulkartClient(
        ckan_client=fake,
        resource_id="a40d07e1-5464-4c0d-b4fd-ff37c40ba162",
        page_size=2,
    )

    with pytest.raises(IstanbulkartPaginationError):
        await client.fetch()


@pytest.mark.asyncio
async def test_malformed_package_is_rejected():
    fake = FakeCkan(load_fixture("malformed_package.json")["result"], {})
    client = IstanbulkartClient(ckan_client=fake)

    with pytest.raises(IstanbulkartPayloadError):
        await client.fetch()
