"""OpenTelemetry trace context helpers and optional OTLP exporter bootstrap."""
from __future__ import annotations

import logging
from typing import Any

from opentelemetry import propagate, trace

from app.core.settings import Settings

logger = logging.getLogger("istanbul_mcp.otel")
_configured = False


def current_trace_fields() -> dict[str, str]:
    """Return active W3C trace_id/span_id hex strings when a valid span exists."""
    span = trace.get_current_span()
    ctx = span.get_span_context() if span is not None else None
    if ctx is None or not ctx.is_valid:
        return {}
    return {
        "trace_id": f"{ctx.trace_id:032x}",
        "span_id": f"{ctx.span_id:016x}",
    }


def inject_trace_headers(headers: dict[str, str]) -> dict[str, str]:
    """Propagate active W3C traceparent/tracestate/baggage to outbound requests."""
    if not current_trace_fields():
        return headers
    carrier = dict(headers)
    propagate.inject(carrier)
    return carrier


def configure_otel(settings: Settings) -> bool:
    """Configure an OTLP TracerProvider only when OTEL_EXPORTER_OTLP_ENDPOINT is set.

    `mcp>=2.3` already instruments inbound MCP RPCs via `opentelemetry-api`.
    When no endpoint or optional SDK package is present this is a silent no-op.
    """
    global _configured
    if _configured or not settings.otel_exporter_otlp_endpoint:
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning(
            "OTEL_EXPORTER_OTLP_ENDPOINT is set but opentelemetry-sdk / "
            "opentelemetry-exporter-otlp-proto-http are not installed; tracing stays no-op."
        )
        return False
    resource = Resource.create({"service.name": settings.app_name})
    provider = TracerProvider(resource=resource)
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    trace.set_tracer_provider(provider)
    _configured = True
    return True


def with_trace_context(record: dict[str, Any]) -> dict[str, Any]:
    fields = current_trace_fields()
    return {**record, **fields} if fields else record
