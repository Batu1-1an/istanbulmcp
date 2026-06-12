from __future__ import annotations

from typing import Any

from app.core.envelope import Source, error_envelope
from app.core.validation import InputValidationError


def validation_error_envelope(
    exc: InputValidationError,
    *,
    sources: list[Source] | None = None,
) -> dict[str, Any]:
    data = [
        {
            "error_code": exc.code,
            "field": exc.field,
            "message": str(exc),
            "allowed_min": exc.allowed_min,
            "allowed_max": exc.allowed_max,
        }
    ]
    limits = [f"field={exc.field}"]
    if exc.allowed_min is not None:
        limits.append(f"allowed_min={exc.allowed_min}")
    if exc.allowed_max is not None:
        limits.append(f"allowed_max={exc.allowed_max}")
    return error_envelope(
        summary=f"Invalid input: {exc}",
        warning=str(exc),
        sources=sources,
        freshness_status="unknown",
        data=data,
        limits=limits,
    )


def source_error_envelope(
    *,
    summary: str,
    warning: str,
    sources: list[Source] | None = None,
    exception: Exception | None = None,
) -> dict[str, Any]:
    data: list[dict[str, Any]] = []
    if exception is not None:
        data.append(
            {
                "error_code": "source_unavailable",
                "exception_type": type(exception).__name__,
            }
        )
    return error_envelope(
        summary=summary,
        warning=warning,
        sources=sources,
        freshness_status="broken",
        data=data,
    )
