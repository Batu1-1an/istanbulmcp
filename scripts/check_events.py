"""Opt-in real Ticketmaster -> temporary SQLite -> three MCP tools check."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import tempfile


async def check():
    from mcp import Client
    from app.core.settings import get_settings
    from app.mcp.registry import create_mcp_server
    settings = get_settings()
    if not settings.ticketmaster_api_key:
        print(json.dumps({"ok": False, "error": "TICKETMASTER_API_KEY is not configured"}))
        return False
    server = create_mcp_server(settings)
    async with Client(server) as client:
        search = await client.call_tool("istanbul_events_search", {"limit": 5})
        payload = search.structured_content
        if not payload or not payload["ok"]:
            print(json.dumps({"ok": False, "stage": "search", "error": (payload or {}).get("error", {}).get("code", "tool_error")}))
            return False
        print(json.dumps({"stage": "search", "ok": True, "result_info": payload["result_info"],
                          "sources": [{"publisher": s["publisher"], "received": s["received_total"], "accepted": s["accepted_total"]} for s in payload["sources"]]}))
        if not payload["data"]:
            print(json.dumps({"ok": False, "stage": "search", "error": "No sessions for detail/plan verification"}))
            return False
        card = next((card for card in payload["data"] if card.get("timing_kind") != "flexible_entry"), payload["data"][0])
        detail = await client.call_tool("istanbul_event_detail", {"event_id": card["event_id"]})
        plan = await client.call_tool("istanbul_events_plan", {"date": card.get("event_date") or card["start_at"][:10], "start_time": "00:00", "end_time": "23:59", "event_ids": [card["event_id"]]})
        for stage, result in (("detail", detail), ("plan", plan)):
            value = result.structured_content
            ok = bool(value and value["ok"] and not result.is_error)
            print(json.dumps({"stage": stage, "ok": ok, "result_info": value.get("result_info") if value else None}))
            if not ok:
                return False
    return True


def main():
    os.environ["EVENTS_ENABLED"] = "true"
    os.environ["EVENTS_BILETINIAL_ENABLED"] = "false"
    with tempfile.TemporaryDirectory(prefix="istanbul-events-check-") as directory:
        os.environ["DATABASE_PATH"] = str(Path(directory) / "events.sqlite3")
        try:
            passed = asyncio.run(check())
        except Exception as exc:
            print(json.dumps({"ok": False, "error_type": type(exc).__name__}))
            passed = False
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__":
    main()
