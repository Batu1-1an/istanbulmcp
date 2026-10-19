import asyncio
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
from threading import Event

import pytest
from starlette.testclient import TestClient

from app.core.envelope import ResponseEnvelope
from app.core.settings import Settings, get_settings
from app.services.datastore_sql import DatastoreSqlService, snapshot_cache, validate_sql_settings
import app.services.datastore_sql as sql_module

FIXTURE = json.loads((Path(__file__).parent / "fixtures/datastore_sql.json").read_text())
RESOURCE = "fixture-sql-resource"
SQL = "SELECT district, COUNT(*) AS n, SUM(subscribers) AS total FROM records WHERE district IS NOT NULL GROUP BY district ORDER BY n DESC"


class FixtureCkan:
    base_url = "https://fixture.test/ckan"

    def __init__(self, mode=None):
        self.calls = []
        self.mode = mode

    async def datastore_search_bounded(self, **kwargs):
        self.calls.append(kwargs)
        limit, offset = kwargs["limit"], kwargs["offset"]
        result = {"total": len(FIXTURE["records"]), "fields": deepcopy(FIXTURE["fields"]),
                  "records": deepcopy(FIXTURE["records"][offset:offset + limit]) if limit else []}
        if self.mode == "short" and limit:
            result["records"] = []
        if self.mode == "estimated":
            result["total_was_estimated"] = True
        if self.mode == "missing_total":
            result.pop("total")
        if self.mode == "duplicate" and offset > 0 and limit:
            result["records"][0]["_id"] = 1
        if self.mode == "changed_schema" and limit:
            result["fields"][1]["id"] = "new_column"
        if self.mode == "changed_total" and len(self.calls) == 4:
            result["total"] += 1
        if self.mode == "oversize":
            return result, kwargs["max_bytes"] + 1
        return result, len(json.dumps(result).encode())


@pytest.fixture(autouse=True)
def empty_snapshot_cache():
    snapshot_cache.clear()
    yield
    snapshot_cache.clear()


def settings(**kwargs):
    return replace(Settings(ckan_sql_allowed_resource_ids=(RESOURCE,), ckan_sql_page_size=2), **kwargs)


@pytest.mark.asyncio
async def test_sql_uses_all_pages_and_preserves_aggregate_provenance():
    client = FixtureCkan()
    service = DatastoreSqlService(settings=settings(), client=client)
    result = await service.query(resource_id=RESOURCE, sql=SQL)
    ResponseEnvelope.model_validate(result)
    assert result["ok"] is True
    assert result["data"] == [
        {"district": "Kadıköy", "n": 2, "total": 10},
        {"district": "Beşiktaş", "n": 1, "total": 4},
    ]
    assert [(call["limit"], call["offset"]) for call in client.calls] == [(0, 0), (2, 0), (2, 2), (0, 0)]
    assert result["sources"][0]["reported_total"] == 4
    assert result["sources"][0]["accepted_total"] == 4
    assert result["sources"][0]["source_updated_at"] is None
    assert "no_partial_aggregates" in result["limits"]
    assert any("not transactionally" in text for text in result["warnings"])


@pytest.mark.asyncio
async def test_sql_reuses_complete_cache_with_original_retrieval_time():
    client = FixtureCkan()
    service = DatastoreSqlService(settings=settings(), client=client)
    first = await service.query(resource_id=RESOURCE, sql=SQL)
    second = await service.query(resource_id=RESOURCE, sql="SELECT COUNT(*) AS n FROM records")
    assert second["data"] == [{"n": 4}]
    assert first["freshness"]["retrieved_at"] == second["freshness"]["retrieved_at"]
    assert len(client.calls) == 4


@pytest.mark.parametrize("mode", ["short", "estimated", "missing_total", "duplicate", "changed_schema", "changed_total", "oversize"])
@pytest.mark.asyncio
async def test_sql_refuses_partial_or_changing_captures(mode):
    result = await DatastoreSqlService(settings=settings(), client=FixtureCkan(mode)).query(
        resource_id=RESOURCE, sql="SELECT COUNT(*) AS n FROM records"
    )
    assert result["ok"] is False
    assert result["freshness"]["status"] == "broken"
    assert not any("n" in row for row in result["data"])
    assert not snapshot_cache.snapshot()


@pytest.mark.asyncio
async def test_snapshot_over_row_budget_stops_before_data_pages():
    client = FixtureCkan()
    result = await DatastoreSqlService(settings=settings(ckan_sql_max_rows=3), client=client).query(
        resource_id=RESOURCE, sql=SQL,
    )
    assert result["ok"] is False
    assert len(client.calls) == 1


@pytest.mark.parametrize("resource,sql,limit,field", [
    ("not-enabled", SQL, None, "resource_id"),
    (RESOURCE, "DELETE FROM records", None, "sql"),
    (RESOURCE, "SELECT * FROM records; DROP TABLE records", None, "sql"),
    (RESOURCE, "SELECT * FROM records a, records b", None, "sql"),
    (RESOURCE, "SELECT * FROM sqlite_master", None, "sql"),
    (RESOURCE, "SELECT load_extension('anything') FROM records", None, "sql"),
    (RESOURCE, SQL, 0, "limit"),
    (RESOURCE, SQL, 101, "limit"),
])
@pytest.mark.asyncio
async def test_rejected_query_does_not_call_source(resource, sql, limit, field):
    client = FixtureCkan()
    result = await DatastoreSqlService(settings=settings(), client=client).query(
        resource_id=resource, sql=sql, limit=limit,
    )
    assert result["ok"] is False
    assert result["data"][0]["field"] == field
    assert not client.calls


@pytest.mark.asyncio
async def test_result_limit_is_enforced_independently_from_sql_limit():
    service = DatastoreSqlService(settings=settings(), client=FixtureCkan())
    result = await service.query(resource_id=RESOURCE, sql="SELECT * FROM records LIMIT 9999999", limit=2)
    assert len(result["data"]) == 2
    assert any("truncated" in text for text in result["warnings"])
    assert "snapshot_rows=4" in result["limits"]


@pytest.mark.asyncio
async def test_load_deadline_does_not_cache_partial_data():
    client = FixtureCkan()
    async def slow(**_kwargs):
        await asyncio.sleep(1)
    client.datastore_search_bounded = slow
    result = await DatastoreSqlService(settings=settings(ckan_sql_load_timeout_seconds=0.01), client=client).query(
        resource_id=RESOURCE, sql=SQL,
    )
    assert result["ok"] is False
    assert not snapshot_cache.snapshot()


@pytest.mark.asyncio
async def test_only_one_query_or_load_is_admitted_and_cancellation_keeps_gate(monkeypatch):
    started, release = Event(), Event()
    original = sql_module.execute_snapshot_query
    def slow(*args, **kwargs):
        started.set()
        assert release.wait(2)
        return original(*args, **kwargs)
    monkeypatch.setattr(sql_module, "execute_snapshot_query", slow)
    service = DatastoreSqlService(settings=settings(), client=FixtureCkan())
    first = asyncio.create_task(service.query(resource_id=RESOURCE, sql=SQL))
    assert await asyncio.to_thread(started.wait, 2)
    first.cancel()
    await asyncio.sleep(0)
    second = await service.query(resource_id=RESOURCE, sql=SQL)
    assert second["ok"] is False
    assert second["data"][0]["error_code"] == "sql_busy"
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await first
    assert not sql_module.query_gate.locked()


@pytest.mark.parametrize("overrides", [
    {"ckan_sql_max_rows": 50001}, {"ckan_sql_max_bytes": 30 * 1024 * 1024},
    {"ckan_sql_page_size": 5001}, {"ckan_sql_query_timeout_seconds": 5},
    {"ckan_sql_snapshot_ttl_seconds": 0},
])
def test_sql_config_cannot_disable_hard_limits(overrides):
    with pytest.raises(ValueError):
        validate_sql_settings(settings(**overrides))


@pytest.mark.asyncio
async def test_empty_complete_source_is_zero_not_source_failure():
    client = FixtureCkan()
    original = client.datastore_search_bounded
    async def empty(**kwargs):
        value, count = await original(**kwargs)
        value["total"] = 0
        value["records"] = []
        return value, count
    client.datastore_search_bounded = empty
    result = await DatastoreSqlService(settings=settings(), client=client).query(
        resource_id=RESOURCE, sql="SELECT COUNT(*) AS n FROM records",
    )
    assert result["ok"] is True
    assert result["data"] == [{"n": 0}]


def test_datastore_tool_works_through_authenticated_mcp_with_fixture_pages(monkeypatch, tmp_path):
    from app.main import create_app
    import app.mcp.server as handlers

    key = "fixture-sql-" + "s" * 32
    monkeypatch.setenv("MCP_AUTH_REQUIRED", "true")
    monkeypatch.setenv("MCP_API_KEYS", key)
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "runtime.sqlite3"))
    monkeypatch.setenv("CKAN_SQL_ALLOWED_RESOURCE_IDS", RESOURCE)
    monkeypatch.setenv("CKAN_SQL_PAGE_SIZE", "2")
    get_settings.cache_clear()
    client = FixtureCkan()
    monkeypatch.setattr(handlers, "DatastoreSqlService",
                        lambda **kwargs: DatastoreSqlService(settings=kwargs["settings"], client=client))
    with TestClient(create_app(), base_url="http://localhost") as http:
        response = http.post("/mcp/", headers={"accept": "application/json, text/event-stream",
                                               "authorization": "Bearer " + key},
                             json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                   "params": {"name": "istanbul_datastore_query",
                                              "arguments": {"resource_id": RESOURCE, "sql": SQL}}})
    assert response.status_code == 200
    result = response.json()["result"]
    assert not result.get("isError", False)
    actual = result.get("structuredContent") or json.loads(result["content"][0]["text"])
    ResponseEnvelope.model_validate(actual)
    assert actual["data"] == [{"district": "Kadıköy", "n": 2, "total": 10},
                              {"district": "Beşiktaş", "n": 1, "total": 4}]
    assert actual["sources"][0]["reported_total"] == 4
    assert len(client.calls) == 4
    assert response.headers["x-ratelimit-remaining"] == "9999"
