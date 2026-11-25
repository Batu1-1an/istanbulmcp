"""Validate MCP output without changing the bare-dict Python handler contract."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
import inspect
import json
from typing import Any, ParamSpec, get_type_hints

from mcp.types import CallToolResult, TextContent

from app.core.envelope import ResponseEnvelope

P = ParamSpec("P")

STRUCTURED_TOOL_NAMES = frozenset({
    "istanbul_health",
    "istanbul_search_datasets",
    "istanbul_get_dataset",
    "istanbul_get_resource_schema",
    "istanbul_query_resource",
    "istanbul_datastore_query",
    "istanbul_nearby",
    "istanbul_traffic_status",
    "istanbul_water_status",
    "istanbul_mobility_nearby",
    "istanbul_city_services_nearby",
    "istanbul_neighborhood_profile",
    "istanbul_transit_line",
    "istanbul_transport_disruptions",
    "istanbul_metro_accessibility_status",
    "istanbul_market_schedule",
    "istanbul_events_search",
    "istanbul_event_detail",
    "istanbul_events_plan",
    "istanbul_next_departures",
    "istanbul_gtfs_snapshot_status",
})
STRUCTURED_LEGACY_TOOL_NAMES = frozenset({
    "istanbul_nobetci_eczane_nearby", "istanbul_nobetci_eczane_by_district",
})


def _to_mcp_result(raw: dict[str, Any]) -> ResponseEnvelope | CallToolResult:
    envelope = ResponseEnvelope.model_validate(raw)
    if envelope.ok:
        return envelope
    dumped = envelope.model_dump(mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(dumped, ensure_ascii=False, separators=(",", ":")))],
        structured_content=dumped,
        is_error=True,
    )


def with_envelope_output(
    handler: Callable[P, Awaitable[dict[str, Any]] | dict[str, Any]],
) -> Callable[P, Awaitable[ResponseEnvelope] | ResponseEnvelope]:
    """Publish the canonical model only at the MCP registration boundary.

    FastMCP/MCPServer derives both schemas from the callable signature. Preserve
    every input parameter/default and the docstring, replacing only the return
    type on this adapter. Direct Python callers continue to receive dictionaries.
    Domain/validation/source errors (ok=False) propagate MCP isError=True while
    preserving the exact structured ResponseEnvelope in structuredContent and text.
    """
    if inspect.iscoroutinefunction(handler):
        @wraps(handler)
        async def structured(*args: P.args, **kwargs: P.kwargs) -> ResponseEnvelope:
            return _to_mcp_result(await handler(*args, **kwargs))  # type: ignore[return-value]
    else:
        @wraps(handler)
        def structured(*args: P.args, **kwargs: P.kwargs) -> ResponseEnvelope:
            return _to_mcp_result(handler(*args, **kwargs))  # type: ignore[return-value]

    # Resolve forward annotations in the original module before moving them to
    # the adapter, so Literal, Annotated[Field] and any future input models keep their identities.
    signature = inspect.signature(handler, eval_str=True)
    structured.__annotations__ = {
        **get_type_hints(handler, include_extras=True), "return": ResponseEnvelope,
    }
    setattr(structured, "__signature__", signature.replace(return_annotation=ResponseEnvelope))
    return structured
