"""Argument autocompletion for workflow prompts and resource templates."""
from __future__ import annotations

from mcp.server import MCPServer
from mcp.types import Completion, PromptReference, ResourceTemplateReference

from app.core.events import CATEGORIES
from app.mcp.resources import TOPIC_GUIDES
from app.services.places import _DISTRICT_DISPLAY_NAMES, _PLACES, normalize_place

MAX_COMPLETIONS = 20
COMMON_IETT_LINES = ("500T", "34A", "34AS", "34G", "34Z", "15F", "16D", "19F", "25E", "40T", "129T", "E-10", "E-11")
ISTANBUL_SIDES = ("europe", "asia", "Avrupa Yakası", "Anadolu Yakası")


def _filter_candidates(candidates: list[str], prefix: str) -> Completion:
    needle = normalize_place(prefix or "")
    if not needle:
        matches = candidates
    else:
        starts = [item for item in candidates if normalize_place(item).startswith(needle)]
        contains = [item for item in candidates if needle in normalize_place(item) and item not in starts]
        matches = starts + contains
    sliced = matches[:MAX_COMPLETIONS]
    return Completion(values=sliced, total=len(matches), has_more=len(matches) > MAX_COMPLETIONS)


def register_completions(server: MCPServer) -> None:
    districts = sorted(_DISTRICT_DISPLAY_NAMES.values())
    places = sorted({place.name for place in _PLACES} | set(districts))
    categories = sorted(CATEGORIES)
    topics = sorted(TOPIC_GUIDES)

    @server.completion()
    async def complete(ref, argument, _context) -> Completion:
        name = argument.name
        value = argument.value or ""
        if isinstance(ref, ResourceTemplateReference):
            if ref.uri == "istanbul://guides/{topic}" and name == "topic":
                return _filter_candidates(topics, value)
            if ref.uri == "istanbul://districts/{district}" and name == "district":
                return _filter_candidates(districts, value)
            return Completion(values=[], total=0, has_more=False)
        if isinstance(ref, PromptReference):
            if name == "district":
                return _filter_candidates(districts, value)
            if name == "interests":
                return _filter_candidates(categories, value)
            if name == "side":
                return _filter_candidates(list(ISTANBUL_SIDES), value)
            if name in {"origin", "destination"}:
                return _filter_candidates(places, value)
            if name == "line_code":
                return _filter_candidates(list(COMMON_IETT_LINES), value)
        return Completion(values=[], total=0, has_more=False)
