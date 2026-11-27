"""Tests for Skills over MCP (`io.modelcontextprotocol/skills`, SEP-2640 Beta)."""
from __future__ import annotations

import hashlib
import re

import pytest
from starlette.testclient import TestClient

from app.main import create_app
from app.mcp.skills import (
    DEFAULT_TTL_MS,
    EVENTS_SKILL_NAME,
    EXTENSION_ID,
    parse_skill_frontmatter,
)


@pytest.fixture(autouse=True)
def isolated_database(monkeypatch, tmp_path):
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "skills.sqlite3"))


def _modern(client: TestClient, method: str, params: dict | None = None):
    payload_params = dict(params or {})
    payload_params["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": {"name": "skills-pytest", "version": "1.0.0"},
        "io.modelcontextprotocol/clientCapabilities": {},
    }
    headers = {
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2026-07-28",
        "mcp-method": method,
    }
    if method == "resources/read" and "uri" in payload_params:
        headers["mcp-name"] = payload_params["uri"]
    return client.post(
        "/mcp/",
        headers=headers,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": payload_params},
    )


def _legacy(client: TestClient, method: str, params: dict | None = None):
    return client.post(
        "/mcp/",
        headers={"accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
    )


def test_discover_and_server_card_advertise_skills_extension(monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "true")
    with TestClient(create_app(), base_url="http://localhost") as client:
        discovered = _modern(client, "server/discover").json()["result"]
        caps = discovered["capabilities"]
        assert "resources" in caps
        assert caps["extensions"][EXTENSION_ID] == {"directoryRead": True}

        for path in ("/mcp/server-card", "/.well-known/mcp/server-card.json"):
            card = client.get(path).json()
            assert EXTENSION_ID in card["capabilities"]["extensions"]


def test_skills_list_get_read_and_digest_verification_with_events_enabled(monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "true")
    with TestClient(create_app(), base_url="http://localhost") as client:
        listed_res = _modern(client, "skills/list")
        assert listed_res.status_code == 200
        result = listed_res.json()["result"]
        assert result["resultType"] == "complete"
        assert result["ttlMs"] == DEFAULT_TTL_MS
        assert result["cacheScope"] == "public"
        assert "nextCursor" not in result

        skills = result["skills"]
        names = {s["frontmatter"]["name"] for s in skills}
        assert names == {
            "istanbul-city-briefing",
            "istanbul-events-planner",
            "istanbul-open-data-explorer",
            "istanbul-transit-guide",
        }

        for entry in skills:
            uri = entry["uri"]
            name = entry["frontmatter"]["name"]
            description = entry["frontmatter"]["description"]
            assert uri == f"skill://{name}/SKILL.md"
            assert re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name)
            assert 1 <= len(description) <= 1024
            assert "allowed-tools" not in entry["frontmatter"]

            # skills/get returns the exact same entry shape and cache metadata
            got_res = _modern(client, "skills/get", {"uri": uri})
            assert got_res.status_code == 200
            got = got_res.json()["result"]
            assert got["resultType"] == "complete"
            assert got["ttlMs"] == DEFAULT_TTL_MS
            assert got["cacheScope"] == "public"
            assert got["skill"] == entry

            # Manifest includes SKILL.md and every file verifies against resources/read bytes
            manifest_uris = [item["uri"] for item in entry["resources"]]
            assert uri in manifest_uris
            assert len(manifest_uris) == len(set(manifest_uris))

            for item in entry["resources"]:
                read_res = _modern(client, "resources/read", {"uri": item["uri"]})
                assert read_res.status_code == 200
                contents = read_res.json()["result"]["contents"]
                assert len(contents) == 1
                assert contents[0]["uri"] == item["uri"]
                assert contents[0]["mimeType"] == "text/markdown"
                text = contents[0]["text"]
                raw_bytes = text.encode("utf-8")
                assert len(raw_bytes) == item["size"]
                assert len(raw_bytes) < 100_000
                assert item["digest"] == f"sha256:{hashlib.sha256(raw_bytes).hexdigest()}"
                if item["uri"] == uri:
                    assert parse_skill_frontmatter(text) == entry["frontmatter"]


def test_events_skill_is_gated_when_events_disabled(monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "false")
    with TestClient(create_app(), base_url="http://localhost") as client:
        skills = _modern(client, "skills/list").json()["result"]["skills"]
        names = {s["frontmatter"]["name"] for s in skills}
        assert EVENTS_SKILL_NAME not in names
        assert names == {
            "istanbul-city-briefing",
            "istanbul-open-data-explorer",
            "istanbul-transit-guide",
        }

        missing = _modern(client, "skills/get", {"uri": f"skill://{EVENTS_SKILL_NAME}/SKILL.md"}).json()
        assert missing["error"]["code"] == -32602


def test_skills_get_and_directory_read_errors_and_navigation(monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "true")
    with TestClient(create_app(), base_url="http://localhost") as client:
        unknown = _modern(client, "skills/get", {"uri": "skill://does-not-exist/SKILL.md"}).json()
        assert unknown["error"]["code"] == -32602

        root_dir = _modern(client, "resources/directory/read", {"uri": "skill://istanbul-events-planner"}).json()["result"]
        assert root_dir["resultType"] == "complete"
        assert root_dir["ttlMs"] == DEFAULT_TTL_MS
        assert root_dir["cacheScope"] == "public"
        by_uri = {item["uri"]: item for item in root_dir["resources"]}
        assert by_uri["skill://istanbul-events-planner/SKILL.md"]["mimeType"] == "text/markdown"
        assert by_uri["skill://istanbul-events-planner/references"]["mimeType"] == "inode/directory"
        assert "skill://istanbul-events-planner/references/rules.md" not in by_uri

        sub_dir = _modern(
            client,
            "resources/directory/read",
            {"uri": "skill://istanbul-events-planner/references"},
        ).json()["result"]
        assert [item["uri"] for item in sub_dir["resources"]] == [
            "skill://istanbul-events-planner/references/rules.md"
        ]
        assert sub_dir["resources"][0]["name"] == "rules.md"
        assert sub_dir["resources"][0]["mimeType"] == "text/markdown"

        # File URI or nonexistent URI is rejected with -32602
        not_a_dir = _modern(
            client,
            "resources/directory/read",
            {"uri": "skill://istanbul-events-planner/SKILL.md"},
        ).json()
        assert not_a_dir["error"]["code"] == -32602

        unknown_dir = _modern(
            client,
            "resources/directory/read",
            {"uri": "skill://missing-dir"},
        ).json()
        assert unknown_dir["error"]["code"] == -32602

        # Invalid pagination cursor is rejected with -32602
        bad_cursor = _modern(client, "skills/list", {"cursor": "not-an-int"}).json()
        assert bad_cursor["error"]["code"] == -32602


def test_keyed_mode_marks_skills_cache_scope_private(monkeypatch):
    key = "fixture-skills-private-scope-key-1234567890"
    monkeypatch.setenv("MCP_API_KEYS", key)
    with TestClient(create_app(), base_url="http://localhost") as client:
        client.headers["authorization"] = f"Bearer {key}"
        listed = _modern(client, "skills/list").json()["result"]
        assert listed["cacheScope"] == "private"
        got = _modern(client, "skills/get", {"uri": "skill://istanbul-transit-guide/SKILL.md"}).json()["result"]
        assert got["cacheScope"] == "private"
        listed_dir = _modern(
            client,
            "resources/directory/read",
            {"uri": "skill://istanbul-transit-guide"},
        ).json()["result"]
        assert listed_dir["cacheScope"] == "private"


def test_legacy_clients_read_skill_resources_but_cannot_call_modern_skill_methods():
    with TestClient(create_app(), base_url="http://localhost") as client:
        init = _legacy(
            client,
            "initialize",
            {
                "protocolVersion": "2025-11-25",
                "capabilities": {},
                "clientInfo": {"name": "legacy-skills-pytest", "version": "1"},
            },
        )
        assert init.status_code == 200

        listed_res = _legacy(client, "resources/list").json()["result"]["resources"]
        skill_uris = {r["uri"] for r in listed_res if r["uri"].startswith("skill://")}
        assert "skill://istanbul-transit-guide/SKILL.md" in skill_uris

        read_res = _legacy(
            client,
            "resources/read",
            {"uri": "skill://istanbul-transit-guide/SKILL.md"},
        ).json()["result"]
        assert "Istanbul Transit Guide" in read_res["contents"][0]["text"]

        # skills/list is gated to modern 2026-07-28 revision
        legacy_skills = _legacy(client, "skills/list").json()
        assert legacy_skills["error"]["code"] == -32601


def test_skill_docs_match_live_tool_parameter_names(monkeypatch):
    monkeypatch.setenv("EVENTS_ENABLED", "true")
    with TestClient(create_app(), base_url="http://localhost") as client:
        transit = _modern(client, "resources/read", {"uri": "skill://istanbul-transit-guide/SKILL.md"}).json()["result"]["contents"][0]["text"]
        assert 'action="info"' in transit
        assert 'view="info"' not in transit
        assert "equipment_type" in transit
        assert "`metro_istanbul`" in transit

        events = _modern(client, "resources/read", {"uri": "skill://istanbul-events-planner/SKILL.md"}).json()["result"]["contents"][0]["text"]
        assert "`time_from`/`time_to`" in events
        assert "`side`" in events
        rules = _modern(client, "resources/read", {"uri": "skill://istanbul-events-planner/references/rules.md"}).json()["result"]["contents"][0]["text"]
        assert "`price_quote`" in rules
        assert "party_quote" not in rules
        assert 'fulfillment.status="partial"' in rules


def test_structured_tool_text_output_is_compact_utf8():
    with TestClient(create_app(), base_url="http://localhost") as client:
        res = client.post(
            "/mcp/",
            headers={
                "accept": "application/json, text/event-stream",
                "mcp-protocol-version": "2026-07-28",
                "mcp-method": "tools/call",
                "mcp-name": "istanbul_health",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/call",
                "params": {
                    "name": "istanbul_health",
                    "arguments": {},
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    },
                },
            },
        ).json()["result"]
        text = res["content"][0]["text"]
        assert "\n" not in text
        assert "\\u" not in text
        assert res["structuredContent"] == __import__("json").loads(text)
