"""Validate MCP output without changing the bare-dict Python handler contract."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from functools import wraps
import inspect
from typing import Any, ParamSpec, get_type_hints

from app.core.envelope import ResponseEnvelope

P = ParamSpec("P")

STRUCTURED_TOOL_NAMES = frozenset({
    "istanbul_nearby", "istanbul_traffic_status", "istanbul_water_status",
    "istanbul_transit_line", "istanbul_transport_disruptions",
})
STRUCTURED_LEGACY_TOOL_NAMES = frozenset({
    "istanbul_nobetci_eczane_nearby", "istanbul_nobetci_eczane_by_district",
})


def with_envelope_output(
    handler: Callable[P, Awaitable[dict[str, Any]]],
) -> Callable[P, Awaitable[ResponseEnvelope]]:
    """Publish the canonical model only at the MCP registration boundary.

    FastMCP/MCPServer derives both schemas from the callable signature. Preserve
    every input parameter/default and the docstring, replacing only the return
    type on this adapter. Direct Python callers continue to receive dictionaries.
    No SDK-private tool metadata or managers are modified.
    """
    @wraps(handler)
    async def structured(*args: P.args, **kwargs: P.kwargs) -> ResponseEnvelope:
        return ResponseEnvelope.model_validate(await handler(*args, **kwargs))

    # Resolve forward annotations in the original module before moving them to
    # the adapter, so Literal and any future input models keep their identities.
    signature = inspect.signature(handler, eval_str=True)
    structured.__annotations__ = {
        **get_type_hints(handler, include_extras=True), "return": ResponseEnvelope,
    }
    setattr(structured, "__signature__", signature.replace(return_annotation=ResponseEnvelope))
    return structured
