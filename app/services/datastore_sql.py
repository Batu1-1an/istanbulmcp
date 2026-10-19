"""Allowlisted complete DataStore snapshots plus a local, constrained SQL engine."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
from typing import Any

from app.connectors.ckan import CkanClient
from app.core.envelope import Freshness, Pagination, Source, error_envelope, success_envelope
from app.core.error_responses import source_error_envelope, validation_error_envelope
from app.core.rate_limit import SourceRateLimitExceeded
from app.core.settings import Settings
from app.core.source_cache import SourceTTLCache
from app.core.validation import InputValidationError, validate_identifier, validate_limit
from app.storage.guarded_sql import QueryRejected, SnapshotRejected, execute_snapshot_query, validate_fields, validate_sql

# Not the general 1024-entry cache: snapshots can each be up to 20 MiB on the
# wire (Python/SQLite representations are larger). Serialize loads and queries.
snapshot_cache = SourceTTLCache()
query_gate = asyncio.Lock()


@dataclass(frozen=True)
class Snapshot:
    fields: tuple[tuple[str, str], ...]
    records: list[dict]
    received_bytes: int


def validate_sql_settings(settings: Settings) -> None:
    bounds = (
        (settings.ckan_sql_max_rows, 1, 50000),
        (settings.ckan_sql_max_bytes, 1024, 20 * 1024 * 1024),
        (settings.ckan_sql_page_size, 1, 5000),
        (settings.ckan_sql_snapshot_ttl_seconds, 1, 3600),
        (settings.ckan_sql_load_timeout_seconds, 0.01, 60),
        (settings.ckan_sql_query_timeout_seconds, 0.001, 2),
    )
    if any(not low <= value <= high for value, low, high in bounds):
        raise ValueError("CKAN SQL settings exceed the hard safety bounds")
    if len(settings.ckan_sql_allowed_resource_ids) > 100:
        raise ValueError("At most 100 SQL resources may be allowlisted")
    for value in settings.ckan_sql_allowed_resource_ids:
        validate_identifier(value, field="CKAN_SQL_ALLOWED_RESOURCE_IDS")


class DatastoreSqlService:
    def __init__(self, *, settings: Settings, client: CkanClient | None = None):
        validate_sql_settings(settings)
        self.settings = settings
        self.client = client or CkanClient(timeout=settings.request_timeout_seconds)

    def _source(self, resource_id: str, **kwargs) -> Source:
        return Source(
            name="İBB CKAN DataStore — bounded local snapshot",
            url="https://data.ibb.gov.tr/api/3/action/datastore_search",
            resource_id=resource_id, **kwargs,
        )

    async def query(self, *, resource_id: str, sql: str, limit: int | None = None) -> dict:
        try:
            resource_id = validate_identifier(resource_id, field="resource_id")
            source = self._source(resource_id)
            if resource_id not in self.settings.ckan_sql_allowed_resource_ids:
                raise InputValidationError(
                    "Resource is not enabled for SQL; configure CKAN_SQL_ALLOWED_RESOURCE_IDS",
                    field="resource_id", code="resource_not_allowlisted",
                )
            sql = validate_sql(sql)
            safe_limit = validate_limit(
                self.settings.default_limit if limit is None else limit,
                min(self.settings.max_limit, 100),
            )
        except InputValidationError as exc:
            return validation_error_envelope(exc, sources=[self._source(resource_id)])

        if query_gate.locked():
            return error_envelope(
                summary="Local SQL snapshot service is busy.",
                warning="Retry after the current bounded query completes.",
                sources=[source], freshness_status="unknown",
                data=[{"error_code": "sql_busy", "retry_after_seconds": 1}],
                limits=["max_concurrent_sql=1"],
            )
        async with query_gate:
            key = json.dumps(
                [getattr(self.client, "base_url", "ibb"), resource_id,
                 self.settings.ckan_sql_max_rows, self.settings.ckan_sql_max_bytes,
                 self.settings.ckan_sql_page_size, self.settings.ckan_sql_snapshot_ttl_seconds],
                separators=(",", ":"),
            )
            try:
                cached = await snapshot_cache.get_with_status(
                    "ckan_sql.snapshot." + key,
                    ttl_seconds=self.settings.ckan_sql_snapshot_ttl_seconds,
                    max_entries=2, loader=lambda: asyncio.wait_for(
                        self._load_snapshot(resource_id),
                        timeout=self.settings.ckan_sql_load_timeout_seconds,
                    ),
                )
                snapshot = cached.value
                # Shield the bounded worker so cancellation cannot release the
                # single-query gate while a thread is still using its snapshot.
                worker = asyncio.create_task(asyncio.to_thread(
                    execute_snapshot_query, snapshot.fields, snapshot.records, sql,
                    limit=safe_limit, timeout_seconds=self.settings.ckan_sql_query_timeout_seconds,
                ))
                try:
                    data, truncated = await asyncio.shield(worker)
                except asyncio.CancelledError:
                    try:
                        await worker
                    finally:
                        raise
            except QueryRejected as exc:
                return validation_error_envelope(
                    InputValidationError(str(exc), field="sql", code="sql_rejected"), sources=[source],
                )
            except SourceRateLimitExceeded as exc:
                return error_envelope(
                    summary="CKAN snapshot is rate limited.",
                    warning="Retry after local source back-pressure expires.",
                    data=[{"error_code": "source_rate_limited", "retry_after_seconds": round(exc.retry_after_seconds, 3)}],
                    sources=[source], limits=["no_partial_aggregates"], freshness_status="unknown",
                )
            except Exception as exc:
                result = source_error_envelope(
                    summary="Complete bounded DataStore snapshot is unavailable.",
                    warning="No partial aggregate was computed; check source totals and configured snapshot limits.",
                    sources=[source], exception=exc,
                )
                result["limits"] = ["no_partial_aggregates",
                                    f"max_snapshot_rows={self.settings.ckan_sql_max_rows}",
                                    f"max_snapshot_wire_bytes={self.settings.ckan_sql_max_bytes}"]
                if isinstance(exc, SnapshotRejected):
                    result["warnings"].append(str(exc))
                return result

        source = self._source(
            resource_id, last_successful_refresh_at=cached.refreshed_at_iso,
            reported_total=len(snapshot.records), received_total=len(snapshot.records),
            accepted_total=len(snapshot.records), skipped_total=0,
            scope="complete local DataStore capture; not a source-transaction snapshot",
        )
        warnings = [
            "Freshness refers to snapshot retrieval, not the age of source records.",
            "HTTP pages are not transactionally frozen; updates with unchanged totals may occur during capture.",
        ]
        if truncated:
            warnings.append("SQL output was truncated by the enforced result limit; aggregate inputs were complete.")
        return success_envelope(
            summary=f"{len(data)} SQL result row(s) from a complete {len(snapshot.records)}-row capture.",
            data=data, sources=[source],
            freshness=Freshness(
                status="fresh", retrieved_at=cached.refreshed_at_iso,
                ttl_seconds=self.settings.ckan_sql_snapshot_ttl_seconds,
            ),
            pagination=Pagination(limit=safe_limit),
            limits=[
                "engine=isolated_in_memory_sqlite", "table=records", "no_upstream_sql",
                "select_only; allowlisted_functions; no_app_database_access",
                f"snapshot_rows={len(snapshot.records)}", f"snapshot_wire_bytes={snapshot.received_bytes}",
                f"outer_limit={safe_limit}", "result_max_bytes=262144",
                f"query_timeout_seconds={self.settings.ckan_sql_query_timeout_seconds}",
                "max_vm_steps=2000000", "max_concurrent_sql=1", "no_partial_aggregates",
            ],
            warnings=warnings,
        )

    async def _load_snapshot(self, resource_id: str) -> Snapshot:
        size = 0
        async def page(limit: int, offset: int):
            nonlocal size
            remaining = self.settings.ckan_sql_max_bytes - size
            if remaining <= 0:
                raise SnapshotRejected("Snapshot byte budget exhausted")
            value, received = await self.client.datastore_search_bounded(
                resource_id=resource_id, limit=limit, offset=offset, max_bytes=remaining,
            )
            if not isinstance(received, int) or received <= 0 or received > remaining:
                raise SnapshotRejected("Invalid snapshot byte accounting")
            size += received
            return value

        metadata = await page(0, 0)
        fields = validate_fields(metadata.get("fields"))
        total = metadata.get("total")
        if (type(total) is not int or not 0 <= total <= self.settings.ckan_sql_max_rows
                or metadata.get("total_was_estimated") or metadata.get("records") != []):
            raise SnapshotRejected("Exact source total is required and must fit the row budget")
        records: list[dict[str, Any]] = []
        column_names = {name for name, _kind in fields}
        last_id = None
        while len(records) < total:
            requested = min(self.settings.ckan_sql_page_size, total - len(records))
            value = await page(requested, len(records))
            rows = value.get("records")
            if (type(value.get("total")) is not int or value.get("total") != total or value.get("total_was_estimated")
                    or validate_fields(value.get("fields")) != fields
                    or not isinstance(rows, list) or not 0 < len(rows) <= requested):
                raise SnapshotRejected("Incomplete/changing DataStore page")
            for row in rows:
                if not isinstance(row, dict) or not set(row) <= column_names:
                    raise SnapshotRejected("Malformed DataStore record")
                row_id = row.get("_id")
                if type(row_id) is not int or (last_id is not None and row_id <= last_id):
                    raise SnapshotRejected("Duplicate or unstable DataStore _id ordering")
                last_id = row_id
            records.extend(rows)

        final = await page(0, 0)
        if (type(final.get("total")) is not int or final.get("total") != total or final.get("total_was_estimated")
                or final.get("records") != [] or validate_fields(final.get("fields")) != fields):
            raise SnapshotRejected("DataStore changed while capturing pages")
        return Snapshot(fields, records, size)
