"""Opt-in replay of the 100 QA intents; stores summaries, never credentials or raw responses.

Run as: python -m scripts.events_100_uat [--url ...] [--output .data/...json]
This exercises explicit MCP arguments, not LLM routing or user-facing prose.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import time

import httpx

from app.core.events import ISTANBUL
from scripts.events_persona_uat import call_tool, inspect_result

CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/events/user_scenarios_100.json"
TOOLS = {name: "istanbul_events_" + name if name != "detail" else "istanbul_event_detail"
         for name in ("search", "detail", "plan")}


def resolve_arguments(value, replacements):
    if isinstance(value, str):
        return replacements.get(value, value)
    if isinstance(value, list):
        return [resolve_arguments(item, replacements) for item in value]
    if isinstance(value, dict):
        return {key: resolve_arguments(item, replacements) for key, item in value.items()}
    return value


def inspect_case(case, args, payload):
    expected = case.get("expected_error")
    if not payload["ok"]:
        code = (payload.get("error") or {}).get("code")
        allowed = expected or ("validation_error" if case["expect"] == "either" else None)
        return ([] if code == allowed else ["unexpected_error:" + str(code)]), {"error_code": code, "returned": 0}
    if expected or case["expect"] == "error":
        return ["expected_error"], {}
    if case["tool"] == "detail":
        values = payload["data"]
        if not values or not values[0].get("performances"):
            return ["detail_empty"], {}
        performances = values[0]["performances"]
        return [], {"returned": len(values), "performances": len(performances),
                    "offers": sum(len(card["offers"]) for card in performances)}
    adapted = {"tool": TOOLS[case["tool"]], "arguments": args}
    failures, observations = inspect_result(adapted, payload)
    cards = payload["data"] if case["tool"] == "search" else [
        card for key in ("options", "unverified_budget") for option in payload["data"][0][key]
        for card in option["performances"]]
    if case["tool"] == "search":
        today = datetime.now(ISTANBUL).date()
        def day(value, fallback):
            if value == "today":
                return today
            if value == "tomorrow":
                return today + timedelta(days=1)
            return datetime.fromisoformat(value).date() if value else fallback
        first = day(args.get("date_from"), today)
        last = day(args.get("date_to"), first + timedelta(days=6))
        for card in cards:
            start = datetime.fromisoformat(card["start_at"]).astimezone(ISTANBUL)
            if not first <= start.date() <= last:
                failures.append("outside_search_dates")
            clock = start.strftime("%H:%M")
            if args.get("time_from") and clock < args["time_from"] or args.get("time_to") and clock > args["time_to"]:
                failures.append("outside_search_hours")
    for card in cards:
        if not card.get("ticket_url") and not any(link.get("url") for link in card.get("ticket_links", [])):
            # Missing source URLs are valid, but record them rather than inventing links.
            observations["missing_event_links"] = observations.get("missing_event_links", 0) + 1
    if case["tool"] == "plan":
        data = payload["data"][0]
        for option in data["unverified_budget"]:
            if option["total_price_known"] or option["budget_status"] != "unknown":
                failures.append("unknown_budget_not_separated")
            if args.get("max_price_try") is not None and option["known_minimum_total_try"] > args["max_price_try"]:
                failures.append("unverified_subtotal_over_budget")
        for option in [*data["options"], *data["unverified_budget"]]:
            if option["total_price_known"] is False and option.get("total_observed_minimum_try") is not None:
                failures.append("partial_subtotal_presented_as_total")
            for card in option["performances"]:
                if card["start_at"][:10] != data["date"]:
                    failures.append("wrong_plan_day")
                if not data["window"]["start"] <= card["start_at"][11:16] <= data["window"]["end"]:
                    failures.append("outside_plan_window")
        if args.get("event_ids") and any(item["reason"] == "outside_time_window" for item in data["rejected"]):
            if not any("start_time/end_time" in warning for warning in payload["warnings"]):
                failures.append("missing_selection_window_repair")
    return sorted(set(failures)), observations


def workflow(client, url, headers, *, family=False):
    search = call_tool(client, url, headers, TOOLS["search"],
        {"date_from": "tomorrow", "limit": 20, **({"category": "family"} if family else {})})
    candidates = search["data"] if search["ok"] else []
    if not candidates:
        return ["workflow_no_source_candidate"], {"returned": 0}
    card = next((card for card in candidates if card["detail_checked"] and card["availability"] in {"in_stock", "limited"}), candidates[0])
    detail = call_tool(client, url, headers, TOOLS["detail"], {"event_id": card["performance_id"]})
    if not detail["ok"]:
        return ["workflow_detail_failed"], {"returned": 0}
    chosen = detail["data"][0]
    plan = call_tool(client, url, headers, TOOLS["plan"], {"date": card["start_at"][:10],
        "start_time": "00:00", "end_time": "23:59", "event_ids": [card["performance_id"]]})
    if not plan["ok"]:
        return ["workflow_plan_failed"], {"returned": 0}
    options = plan["data"][0]["options"]
    failures = [] if options else ["workflow_plan_empty"]
    allowed = set(chosen.get("selected_performance_ids", []))
    if chosen.get("selection_status") != "matched":
        failures.append("workflow_selection_ambiguous")
    for option in options:
        for picked in option["performances"]:
            if picked["performance_id"] not in allowed or picked["start_at"] != card["start_at"]:
                failures.append("selected_session_changed")
            if family and picked["category"] != "family":
                failures.append("workflow_wrong_category")
    return sorted(set(failures)), {"returned": len(options), "selection_status": chosen.get("selection_status")}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://istanbulmcp-production.up.railway.app/mcp/")
    parser.add_argument("--output", type=Path, default=Path(".data/events-100-current.json"))
    parser.add_argument("--allow-partial-sources", action="store_true", help="Record partial coverage instead of waiting for all configured sources")
    args = parser.parse_args()
    headers = {"accept": "application/json, text/event-stream"}
    key = os.getenv("MCP_API_KEYS", "").split(",")[0].strip()
    if key:
        headers["authorization"] = "Bearer " + key
    today = datetime.now(ISTANBUL).date()
    replacements = {"$TODAY": today.isoformat(), "$TOMORROW": (today + timedelta(days=1)).isoformat(),
        "$WEEK_END": (today + timedelta(days=6)).isoformat(), "$MAX_END": (today + timedelta(days=30)).isoformat(),
        "$PAST_WEEK_START": (today - timedelta(days=7)).isoformat(), "$YESTERDAY": (today - timedelta(days=1)).isoformat(),
        "$PAST_PLAN_DAY": (today - timedelta(days=3)).isoformat()}
    report = {"started_at": datetime.now(ISTANBUL).isoformat(), "results": []}
    with httpx.Client(timeout=90) as client:
        init = client.post(args.url, headers=headers, json={"jsonrpc": "2.0", "id": 0, "method": "initialize",
            "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "events-100-uat", "version": "1.0"}}})
        init.raise_for_status()
        report["server_version"] = init.json()["result"]["serverInfo"]["version"]
        seed = None
        for _ in range(60):
            seed = call_tool(client, args.url, headers, TOOLS["search"], {"date_from": "tomorrow", "limit": 20})
            ready = seed["ok"] and seed["data"] and (args.allow_partial_sources or
                all(source["coverage_status"] == "checked" for source in seed["sources"]))
            if ready:
                break
            time.sleep(2)
        else:
            raise SystemExit("preflight_failed: no usable catalogue or configured source not checked")
        report["source_snapshots"] = [{key: source.get(key) for key in (
            "publisher", "coverage_status", "refresh_status", "serving_stale", "last_successful_refresh_at", "accepted_total")}
            for source in seed["sources"]]
        replacements.update({"$EVENT_ID": seed["data"][0]["event_id"], "$PERF_ID": seed["data"][0]["performance_id"]})
        cases = json.loads(CASES.read_text())
        assert len(cases) == 100
        for case in cases:
            started = time.monotonic()
            actual = resolve_arguments(case["args"], replacements)
            try:
                if case["tool"].startswith("workflow"):
                    failures, observations = workflow(client, args.url, headers, family=case["tool"] == "workflow_search_plan")
                else:
                    payload = call_tool(client, args.url, headers, TOOLS[case["tool"]], actual)
                    failures, observations = inspect_case(case, actual, payload)
                    observations["ok"] = payload["ok"]
                    observations["freshness"] = payload["freshness"]["status"]
                    observations["sources"] = [{key: source.get(key) for key in (
                        "publisher", "coverage_status", "refresh_status", "serving_stale", "last_successful_refresh_at")}
                        for source in payload["sources"]]
            except Exception as exc:
                failures, observations = ["request_failed:" + type(exc).__name__], {}
            row = {"id": case["id"], "question": case["question"], "checks_failed": failures,
                   "elapsed_ms": round((time.monotonic() - started) * 1000), **observations}
            report["results"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(0.25)
    report["completed_at"] = datetime.now(ISTANBUL).isoformat()
    report["failed"] = sum(bool(row["checks_failed"]) for row in report["results"])
    report["wall_seconds"] = round((datetime.fromisoformat(report["completed_at"]) - datetime.fromisoformat(report["started_at"])).total_seconds(), 3)
    report["request_seconds"] = sum(row["elapsed_ms"] for row in report["results"]) / 1000
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(report["results"]), "failed": report["failed"], "wall_seconds": report["wall_seconds"]}))
    raise SystemExit(bool(report["failed"]))


if __name__ == "__main__":
    main()
