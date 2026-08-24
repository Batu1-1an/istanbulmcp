from __future__ import annotations

from datetime import datetime, timezone
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
    dataset_id: str | None = None
    resource_id: str | None = None
    source_updated_at: str | None = None
    last_successful_refresh_at: str | None = None
    scope: str | None = None
    reported_total: int | None = None
    received_total: int | None = None
    accepted_total: int | None = None
    skipped_total: int | None = None
    license: str | None = "Istanbul Metropolitan Municipality Open Data License"
    url: str | None = None


class Pagination(BaseModel):
    limit: int
    offset: int = 0
    total_estimate: int | None = None


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
) -> dict[str, Any]:
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
) -> dict[str, Any]:
    envelope = ResponseEnvelope(
        ok=False,
        summary=summary,
        data=data or [],
        freshness=Freshness(status=freshness_status),
        sources=sources or [],
        limits=limits or [],
        warnings=[warning],
    )
    return envelope.model_dump(mode="json")
