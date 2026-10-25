"""Bounded per-process tool metrics. Never retain arguments or response text."""
from __future__ import annotations

import asyncio
from collections import Counter
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import logging
import threading
import time
from typing import Any, Iterator

from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from pydantic import ValidationError

logger = logging.getLogger("istanbul_mcp.tools")
SLOW_THRESHOLD_MS = 1000
CACHE_EVENTS = ("hit", "miss", "load", "wait", "stale", "error")
OUTCOMES = ("success", "domain_error", "tool_error", "exception", "cancelled")
ERROR_CODES = frozenset({
    "validation_error", "not_found", "source_unavailable", "source_timeout",
    "source_rate_limited", "source_invalid_response", "warming_up", "outside_calendar",
    "snapshot_unavailable", "feature_disabled", "request_failed", "ambiguous_place",
    "resource_not_allowlisted", "sql_rejected", "sql_busy", "unknown_tool", "invalid_arguments",
})


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CallObservation:
    cache: Counter = field(default_factory=Counter)
    outcome: str = "success"
    error_code: str | None = None
    returned: int | None = None
    freshness: str | None = None
    partial: bool = False
    _active: bool = field(default=True, repr=False)
    _lock: Any = field(default_factory=threading.Lock, repr=False)

    def cache_event(self, event: str) -> None:
        with self._lock:
            if self._active and event in CACHE_EVENTS:
                self.cache[event] += 1

    def cache_snapshot(self) -> dict[str, int]:
        with self._lock:
            self._active = False
            return {event: self.cache[event] for event in CACHE_EVENTS}

    def result(self, result: Any) -> None:
        # Monitoring must not turn a successful tool call into an error.
        try:
            self._classify_result(result)
        except Exception:
            return

    def _classify_result(self, result: Any) -> None:
        if getattr(result, "is_error", False):
            self.outcome = "tool_error"
            self.error_code = "tool_execution_error"
            return
        payload = getattr(result, "structured_content", None)
        if not isinstance(payload, dict):
            content = getattr(result, "content", [])
            # Legacy dict tools can expose JSON text only. Parse a bounded
            # envelope for booleans/counts, never retain or log the text.
            if len(content) == 1:
                text = getattr(content[0], "text", None)
                if isinstance(text, str) and len(text) <= 1024 * 1024:
                    try:
                        payload = json.loads(text)
                    except (ValueError, RecursionError):
                        pass
        if not isinstance(payload, dict):
            return
        data = payload.get("data")
        self.returned = len(data) if isinstance(data, list) else None
        freshness = payload.get("freshness")
        status = freshness.get("status") if isinstance(freshness, dict) else None
        self.freshness = status if isinstance(status, str) and status in {"fresh", "stale", "unknown", "broken"} else None
        sources = payload.get("sources")
        if isinstance(sources, list):
            checked = any(isinstance(source, dict) and source.get("coverage_status") == "checked" for source in sources)
            unavailable = any(isinstance(source, dict) and source.get("coverage_status") == "unavailable" for source in sources)
            self.partial = checked and unavailable
        if payload.get("ok") is False:
            self.outcome = "domain_error"
            error = payload.get("error")
            code = error.get("code") if isinstance(error, dict) else None
            if code is None and isinstance(data, list):
                code = next((row.get("error_code") for row in data if isinstance(row, dict) and row.get("error_code")), None)
            self.error_code = code if isinstance(code, str) and code in ERROR_CODES else "other_error"


_current: ContextVar[CallObservation | None] = ContextVar("istanbul_tool_observation", default=None)


def observe_cache(event: str) -> None:
    observation = _current.get()
    if observation is not None and event in CACHE_EVENTS:
        observation.cache_event(event)


class ToolTelemetry:
    def __init__(self, tool_names: set[str]):
        self.started_at = _now()
        self._lock = threading.Lock()
        # Caller-provided unknown names share one bucket, not a growing map.
        self._rows = {name: self._new_row(name) for name in sorted(tool_names | {"__unknown__"})}

    @staticmethod
    def _new_row(name: str) -> dict:
        return {"tool": name, "calls": 0, "in_flight": 0, "slow_calls": 0,
                "duration_ms_total": 0.0, "duration_ms_max": 0.0,
                "outcomes": dict.fromkeys(OUTCOMES, 0), "errors": {},
                "cache": dict.fromkeys(CACHE_EVENTS, 0), "returned_total": 0,
                "stale_responses": 0, "partial_responses": 0,
                "last_outcome": None, "last_duration_ms": None, "last_completed_at": None}

    def _start(self, name: str) -> str:
        with self._lock:
            label = name if name in self._rows else "__unknown__"
            self._rows[label]["calls"] += 1
            self._rows[label]["in_flight"] += 1
            return label

    def _finish(self, label: str, observation: CallObservation, duration_ms: float) -> None:
        cache = observation.cache_snapshot()
        slow = duration_ms >= SLOW_THRESHOLD_MS
        with self._lock:
            row = self._rows[label]
            row["in_flight"] -= 1
            row["slow_calls"] += int(slow)
            row["duration_ms_total"] += duration_ms
            row["duration_ms_max"] = max(row["duration_ms_max"], duration_ms)
            row["outcomes"][observation.outcome] += 1
            if observation.error_code:
                row["errors"][observation.error_code] = row["errors"].get(observation.error_code, 0) + 1
            for event, count in cache.items():
                row["cache"][event] += count
            row["returned_total"] += observation.returned or 0
            row["stale_responses"] += int(observation.freshness == "stale")
            row["partial_responses"] += int(observation.partial)
            row.update(last_outcome=observation.outcome, last_duration_ms=round(duration_ms, 3), last_completed_at=_now())
        try:
            logger.info(json.dumps({
                "event": "mcp_tool_call", "tool": label, "outcome": observation.outcome,
                "error_code": observation.error_code, "duration_ms": round(duration_ms, 3),
                "slow": slow, "returned": observation.returned, "freshness": observation.freshness,
                "partial": observation.partial, "cache": cache,
            }, separators=(",", ":")))
        except Exception:
            # A broken log handler must not replace a result or the original
            # exception. Never log the logging error (it may contain payloads).
            pass

    @contextmanager
    def track(self, name: str) -> Iterator[CallObservation]:
        label = self._start(name)
        observation = CallObservation()
        token = _current.set(observation)
        started = time.perf_counter()
        try:
            yield observation
        except asyncio.CancelledError:
            observation.outcome, observation.error_code = "cancelled", "cancelled"
            raise
        except ToolError as exc:
            observation.outcome = "exception" if isinstance(exc, UnexpectedToolError) else "tool_error"
            observation.error_code = ("unknown_tool" if label == "__unknown__" else
                                      "invalid_arguments" if isinstance(exc.__cause__, ValidationError) else "tool_execution_error")
            raise
        except BaseException:
            observation.outcome, observation.error_code = "exception", "tool_execution_error"
            raise
        finally:
            _current.reset(token)
            self._finish(label, observation, max(0.0, (time.perf_counter() - started) * 1000))

    def snapshot(self) -> dict:
        with self._lock:
            rows = []
            for row in self._rows.values():
                completed = row["calls"] - row["in_flight"]
                rows.append({**row, "outcomes": dict(row["outcomes"]), "errors": dict(row["errors"]),
                             "cache": dict(row["cache"]), "duration_ms_total": round(row["duration_ms_total"], 3),
                             "duration_ms_max": round(row["duration_ms_max"], 3),
                             "duration_ms_mean": round(row["duration_ms_total"] / completed, 3) if completed else None})
        return {"enabled": True, "storage": "process_memory", "started_at": self.started_at,
                "reset_on_restart": True, "slow_threshold_ms": SLOW_THRESHOLD_MS,
                "cache_coverage": "shared_SourceTTLCache_only", "tools": rows}
