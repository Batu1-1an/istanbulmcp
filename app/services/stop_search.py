"""Bounded name discovery over the already validated GTFS schedule snapshot."""
from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import time
from unicodedata import combining, normalize

from app.core.geo import google_maps_url
from app.core.validation import InputValidationError, validate_text


def normalize_stop_name(value: str) -> str:
    text = normalize("NFKD", value.casefold().replace("ı", "i"))
    text = "".join(char for char in text if not combining(char))
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def validate_stop_query(value: str) -> str:
    query = validate_text(value, field="stop_query", min_length=2, max_length=200)
    if len(normalize_stop_name(query)) < 2:
        raise InputValidationError("stop_query must contain at least two letters or digits", field="stop_query")
    return query


@dataclass(frozen=True)
class StopSearchResult:
    rows: list[dict]
    matched_total: int
    suggested_total: int = 0


def search_stops(conn, query: str, limit: int) -> StopSearchResult:
    """Exact, prefix, then all-token substring matches; typos are suggestions only.

    No user text enters SQL. The feed caps stops at 100,000 rows. The wall-clock
    budget also covers Python normalization and fuzzy matching, not just SQLite.
    """
    deadline = time.monotonic() + 1
    needle = normalize_stop_name(query)
    tokens = needle.split()
    named = []
    matches = []
    for row in conn.execute("SELECT * FROM gtfs_schedule_stops"):
        if time.monotonic() > deadline:
            raise TimeoutError("GTFS stop search exceeded its budget")
        name = normalize_stop_name(row["stop_name"])
        named.append((name, dict(row)))
        if all(token in name for token in tokens):
            rank = 0 if name == needle else 1 if name.startswith(needle) else 2
            matches.append((rank, name, row["stop_id"], dict(row)))
    if matches:
        matches.sort(key=lambda item: item[:3])
        if time.monotonic() > deadline:
            raise TimeoutError("GTFS stop search exceeded its budget")
        kinds = ("exact", "prefix", "contains")
        return StopSearchResult(
            [_candidate(row, kinds[rank]) for rank, _, _, row in matches[:limit]], len(matches),
        )

    # Do not fuzzy-match short fragments: they produce misleading candidates.
    scores = {}
    if len(needle) >= 4:
        matcher = SequenceMatcher(autojunk=False, b=needle)
        for name, _ in named:
            if time.monotonic() > deadline:
                raise TimeoutError("GTFS stop search exceeded its budget")
            if name in scores:
                continue
            matcher.set_seq1(name)
            score = 0.0
            if matcher.real_quick_ratio() >= .72 and matcher.quick_ratio() >= .72:
                score = matcher.ratio()
            scores[name] = score
    suggested_names = sorted((name for name, score in scores.items() if score >= .72),
                             key=lambda name: (-scores[name], name))[:5]
    ranks = {name: rank for rank, name in enumerate(suggested_names)}
    suggestions = sorted(((ranks[name], name, row["stop_id"], row) for name, row in named if name in ranks),
                         key=lambda item: item[:3])
    if time.monotonic() > deadline:
        raise TimeoutError("GTFS stop search exceeded its budget")
    return StopSearchResult(
        [_candidate(row, "suggestion") for _, _, _, row in suggestions[:limit]], 0, len(suggestions),
    )


def _candidate(row: dict, match_kind: str) -> dict:
    return {**row, "result_kind": "stop_candidate", "match_kind": match_kind,
            "platform_direction_text": row.get("stop_desc"),
            "maps_url": google_maps_url(row["lat"], row["lon"])}
