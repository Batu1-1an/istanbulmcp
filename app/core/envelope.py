from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Literal

from pydantic import BaseModel, Field

FreshnessStatus = Literal["fresh", "stale", "unknown", "broken"]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class Freshness(BaseModel):
    status: FreshnessStatus
    retrieved_at: str = Field(default_factory=utc_now_iso)
    source_updated_at: str | None = None
    ttl_seconds: int | None = None


class Source(BaseModel):
    name: str
    publisher: str = "Istanbul Metropolitan Municipality"
    operator: str | None = None
    modes: list[str] | None = None
    coverage_kind: Literal["live_status", "official_announcements", "published_timetable"] | None = None
    coverage_status: Literal["checked", "unavailable"] | None = None
    last_checked_at: str | None = None
    dataset_id: str | None = None
    resource_id: str | None = None
    source_updated_at: str | None = None
    last_successful_refresh_at: str | None = None
    scope: str | None = None
    reported_total: int | None = None
    received_total: int | None = None
    accepted_total: int | None = None
    skipped_total: int | None = None
    matched_total: int | None = None
    returned_total: int | None = None
    license: str | None = "Istanbul Metropolitan Municipality Open Data License"
    url: str | None = None


class Pagination(BaseModel):
    limit: int
    offset: int = 0
    total_estimate: int | None = None


class Repair(BaseModel):
    next_step: str
    tool: str | None = None
    arguments: dict[str, Any] | None = None


class ErrorInfo(BaseModel):
    code: str
    temporary: bool = False
    retry_after_ms: int | None = Field(default=None, ge=0)
    field: str | None = None
    repair: Repair | None = None


class ResultInfo(BaseModel):
    # Counts describe the named result scope, not total city/source coverage.
    returned: int = Field(ge=0)
    matched: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    scope: str = "data"
    next_step: str | None = None


def result_info(*, returned: int, matched: int | None = None,
                truncated: bool | None = None, scope: str = "data") -> ResultInfo:
    if truncated is None and matched is not None:
        truncated = matched > returned
    note = None
    if truncated:
        note = "Increase limit within the advertised maximum or narrow the filters. This is not a complete total."
    elif truncated is None:
        note = "Completeness is unknown; inspect source coverage, limits and warnings."
    return ResultInfo(returned=returned, matched=matched, truncated=truncated, scope=scope, next_step=note)


class ResponseEnvelope(BaseModel):
    ok: bool = True
    summary: str
    data: list[dict[str, Any]] = Field(default_factory=list)
    geojson: dict[str, Any] | None = None
    pagination: Pagination | None = None
    freshness: Freshness
    sources: list[Source] = Field(default_factory=list)
    limits: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    next_queries: list[str] = Field(default_factory=list)
    error: ErrorInfo | None = None
    result_info: ResultInfo | None = None


def success_envelope(
    *,
    summary: str,
    data: list[dict[str, Any]] | None = None,
    sources: list[Source] | None = None,
    freshness: Freshness | None = None,
    limits: list[str] | None = None,
    warnings: list[str] | None = None,
    next_queries: list[str] | None = None,
    pagination: Pagination | None = None,
    geojson: dict[str, Any] | None = None,
    result: ResultInfo | None = None,
) -> dict[str, Any]:
    if result is None:
        total = pagination.total_estimate if pagination else None
        # An estimate is not an exact matched count. No offset/cursor is
        # advertised unless a tool actually accepts one.
        result = result_info(returned=len(data or []), truncated=(
            total > pagination.offset + len(data or []) if total is not None else None
        ))
    envelope = ResponseEnvelope(
        summary=summary,
        data=data or [],
        sources=sources or [],
        freshness=freshness or Freshness(status="unknown"),
        limits=limits or [],
        warnings=warnings or [],
        next_queries=next_queries or [],
        pagination=pagination,
        geojson=geojson,
        result_info=result,
    )
    return envelope.model_dump(mode="json")


def error_envelope(
    *,
    summary: str,
    warning: str,
    sources: list[Source] | None = None,
    freshness_status: FreshnessStatus = "broken",
    data: list[dict[str, Any]] | None = None,
    limits: list[str] | None = None,
    code: str | None = None,
    temporary: bool | None = None,
    retry_after_ms: int | None = None,
    repair: Repair | None = None,
) -> dict[str, Any]:
    detail = next((row for row in data or [] if row.get("error_code")), {})
    retry_seconds = next((row.get("retry_after_seconds") for row in data or []
                          if isinstance(row.get("retry_after_seconds"), (int, float))
                          and not isinstance(row.get("retry_after_seconds"), bool)
                          and math.isfinite(row["retry_after_seconds"]) and row["retry_after_seconds"] >= 0), None)
    code = code or detail.get("error_code") or ("source_rate_limited" if retry_seconds is not None else "request_failed")
    if temporary is None:
        temporary = code in {"source_unavailable", "source_rate_limited", "warming_up", "source_timeout"}
    if retry_after_ms is None and retry_seconds is not None and temporary:
        retry_after_ms = math.ceil(retry_seconds * 1000)
    if repair is None:
        next_step = "Review the inputs and advertised tool limits before retrying."
        if temporary:
            next_step = ("Retry after the indicated delay; source availability is not guaranteed."
                         if retry_after_ms is not None else "Retry later; source availability is not guaranteed.")
        repair = Repair(next_step=next_step)
    envelope = ResponseEnvelope(
        ok=False,
        summary=summary,
        data=data or [],
        freshness=Freshness(status=freshness_status),
        sources=sources or [],
        limits=limits or [],
        warnings=[warning],
        error=ErrorInfo(code=code, temporary=temporary, retry_after_ms=retry_after_ms if temporary else None,
                        field=detail.get("field"), repair=repair),
        result_info=result_info(returned=len(data or []), scope="error_details"),
    )
    return envelope.model_dump(mode="json")
