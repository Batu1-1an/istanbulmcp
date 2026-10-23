"""Pinned official manifest schema and metadata on every tool surface."""
from dataclasses import replace
import hashlib
from itertools import product
import json
from pathlib import Path
import tomllib

from jsonschema import Draft7Validator, FormatChecker
import pytest

from app.core.settings import Settings
from app.mcp.instructions import SERVER_INSTRUCTIONS
from app.mcp.registry import TOOL_TITLES, create_mcp_server

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "tests/fixtures/mcp_registry/server-2025-12-11.schema.json"


def test_manifest_matches_pinned_official_registry_schema_and_package():
    schema = json.loads(SCHEMA_PATH.read_text())
    manifest = json.loads((ROOT / "server.json").read_text())
    assert hashlib.sha256(SCHEMA_PATH.read_bytes()).hexdigest() == "3fba09590c99f61735d234822279f4223fab9e300c0a81e81c91ab62a4114de0"
    Draft7Validator.check_schema(schema)
    Draft7Validator(schema, format_checker=FormatChecker()).validate(manifest)
    assert manifest["$schema"] == schema["$id"]
    assert manifest["version"] == tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    assert manifest["name"] == "io.github.Batu1-1an/istanbul-mcp"
    assert manifest["remotes"] == [{"type": "streamable-http", "url": "https://istanbulmcp-production.up.railway.app/mcp/"}]
    assert "packages" not in manifest  # Remote-only, no unverified package claims.


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy,ferry,schedule", list(product([False, True], repeat=3)))
async def test_every_surface_has_explicit_titles_and_read_only_annotations(legacy, ferry, schedule):
    settings = replace(Settings(), mcp_legacy_tools_enabled=legacy, ferry_schedules_enabled=ferry, gtfs_schedule_enabled=schedule)
    tools = await create_mcp_server(settings).list_tools()
    for tool in tools:
        assert tool.title == TOOL_TITLES[tool.name]
        assert tool.title and len(tool.name) <= 64
        assert tool.annotations.read_only_hint is True
        assert tool.annotations.destructive_hint is False
        assert tool.description
    assert ("istanbul_next_departures" in {t.name for t in tools}) is schedule


@pytest.mark.asyncio
async def test_pharmacy_descriptions_are_narrow_and_presentation_guidance_is_preserved():
    tools = {t.name: t for t in await create_mcp_server(Settings(mcp_legacy_tools_enabled=True)).list_tools()}
    for name in ("istanbul_nearby", "istanbul_nobetci_eczane_nearby", "istanbul_nobetci_eczane_by_district"):
        description = tools[name].description
        assert "maps_search_url" in description and "verified pin" in description
        assert "In the user-facing answer" not in description
        assert "Do not display" not in description
        assert "Show source/citation footers" not in description
    for guidance in ("maps_url", "maps_search_url", "calling before visiting", "source footers only when asked", "freshness", "warnings"):
        assert guidance in SERVER_INSTRUCTIONS
