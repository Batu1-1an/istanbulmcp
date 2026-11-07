"""Opt-in persona questions mapped to explicit MCP calls and semantic checks.

This checks tool-backed workflows, not an LLM's natural-language routing quality.
Only report summaries are persisted; credentials and raw responses are omitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time

import httpx

from app.core.envelope import ResponseEnvelope
from app.core.events import age_suitability, normalize_category, search_text
from app.services.places import normalize_place

CASES = Path(__file__).resolve().parents[1] / "tests/fixtures/events/persona_queries.json"


def call_tool(client, url, headers, name, arguments):
    response = client.post(url,headers=headers,json={"jsonrpc":"2.0","id":1,"method":"tools/call",
        "params":{"name":name,"arguments":arguments}})
    response.raise_for_status()
    result=response.json()["result"]
    payload=result.get("structuredContent") or json.loads(result["content"][0]["text"])
    ResponseEnvelope.model_validate(payload)
    return payload


def selection_workflow(client,url,headers):
    started=time.monotonic()
    row={"id":"selected_session_workflow","persona":"Seansını seçmiş takipçi",
         "question":"Seçtiğim seansı başka bir saatle değiştirmeden plana ekle."}
    try:
        search=call_tool(client,url,headers,"istanbul_events_search",{"date_from":"tomorrow","limit":20})
        cards=search["data"]
        if not search["ok"] or not cards:
            raise ValueError("No session available for selection check")
        card=next((c for c in cards if c["detail_checked"] and c["availability"] in {"in_stock","limited"}),cards[0])
        detail=call_tool(client,url,headers,"istanbul_event_detail",{"event_id":card["performance_id"]})
        if not detail["ok"]:
            raise ValueError("Selected session detail unavailable")
        selected=detail["data"][0]
        plan=call_tool(client,url,headers,"istanbul_events_plan",{"date":card["start_at"][:10],
            "start_time":"00:00","end_time":"23:59","event_ids":[card["performance_id"]]})
        if selected.get("selection_status") != "matched":
            errors=[] if not plan["ok"] and (plan.get("error") or {}).get("code")=="selection_changed" else ["ambiguous_session_substituted"]
            row.update(errors=errors,returned=0,selection_status=selected.get("selection_status"))
        else:
            if not plan["ok"]:
                raise ValueError("Selected session plan failed")
            allowed=set(selected["selected_performance_ids"])
            options=plan["data"][0]["options"]
            wrong=[c for option in options for c in option["performances"]
                   if c["performance_id"] not in allowed or c["start_at"] != card["start_at"]]
            errors=["selected_session_changed"] if wrong else []
            if not options:
                errors.append("selected_session_missing_from_plan")
            row.update(errors=errors,returned=len(options),
                       selection_status="matched",selected_start=card["start_at"])
    except Exception as exc:
        row["errors"]=["workflow_failed:"+type(exc).__name__]
    row["elapsed_ms"]=round((time.monotonic()-started)*1000)
    return row


def inspect_result(case, payload):
    errors = []
    expected = case.get("expected_error")
    if expected:
        if payload["ok"] or (payload.get("error") or {}).get("code") != expected:
            errors.append("expected_validation_error")
        return errors, {}
    if not payload["ok"]:
        return ["unexpected_error:" + (payload.get("error") or {}).get("code", "unknown")], {}
    args = case["arguments"]
    if case["tool"] == "istanbul_events_search":
        cards = payload["data"]
        for card in cards:
            if args.get("category") and card["category"] != normalize_category(args["category"]):
                errors.append("category_mismatch")
            if args.get("district") and normalize_place(card["venue"]["district"] or "") != normalize_place(args["district"]):
                errors.append("district_mismatch")
            price = card["price"]["minimum_observed_try"]
            if args.get("free_only") and price != 0:
                errors.append("free_filter_not_verified")
            if args.get("max_price_try") is not None and price is not None and price > args["max_price_try"]:
                errors.append("over_budget")
            if not args.get("include_unknown_prices", True) and price is None:
                errors.append("strict_price_not_verified")
            if not args.get("include_sold_out",False) and card["availability"]=="sold_out":
                errors.append("sold_out_attendance_recommendation")
            if args.get("child_age") is not None and (card["category"] != "family" or age_suitability(card.get("age_limit"), args["child_age"]) != "within"):
                errors.append("child_age_not_verified")
            if args.get("query") and args.get("query_scope", "title") == "title":
                words=search_text(card["title"]).split()
                if not all(any(word.startswith(token) for word in words) for token in search_text(args["query"]).split()):
                    errors.append("title_query_matched_only_venue")
            if args.get("radius_m") is not None and (card["distance_m"] is None or card["distance_m"] > args["radius_m"] + 1):
                errors.append("outside_radius")
        return errors, {"returned": len(cards), "matched": payload["result_info"]["matched"],
                        "known_prices": sum(c["price"]["status"] == "known" for c in cards),
                        "verified_details": sum(c["detail_checked"] for c in cards),
                        "sold_out": sum(c["availability"]=="sold_out" for c in cards),
                        "categories": sorted({c["category"] for c in cards}),
                        "sample_titles": [c["title"] for c in cards[:3]],
                        "sample_ids": [c["performance_id"] for c in cards[:3]]}
    data = payload["data"][0]
    options = data["options"]
    for option in options:
        cards = option["performances"]
        if args.get("interests") and any(c["category"] not in [normalize_category(i) for i in args["interests"]] for c in cards):
            errors.append("unrequested_category_in_plan")
        if args.get("max_price_try") is not None and (not option["total_price_known"] or option["known_minimum_total_try"] > args["max_price_try"]):
            errors.append("budget_not_verified")
        if len(cards) > args.get("max_events", 3):
            errors.append("too_many_stops")
        if len({c["event_id"] for c in cards}) != len(cards):
            errors.append("duplicate_event_in_plan")
        if any(g["minutes"] < args.get("min_gap_minutes", 30) for g in option["gaps"]):
            errors.append("minimum_gap_broken")
        if option["calendar"]["ics"].count("BEGIN:VEVENT") != len(cards):
            errors.append("calendar_stop_count_mismatch")
        if args.get("require_known_end") and not option["checks"]["window_end_verified"]:
            errors.append("requested_end_time_not_verified")
        if args.get("child_age") is not None and any(c["category"] != "family" or age_suitability(c.get("age_limit"),args["child_age"]) != "within" for c in cards):
            errors.append("child_age_not_verified_in_plan")
    return errors, {"returned": len(options), "unverified_budget": len(data["unverified_budget"]),
                    "stop_counts": [len(o["performances"]) for o in options],
                    "known_end_plans": sum(o["checks"]["window_end_verified"] for o in options),
                    "categories": sorted({c["category"] for o in options for c in o["performances"]}),
                    "sample_titles": [c["title"] for c in options[0]["performances"]] if options else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="https://istanbulmcp-production.up.railway.app/mcp/")
    parser.add_argument("--output", type=Path, default=Path(".data/events-persona-uat.json"))
    args = parser.parse_args()
    headers = {"accept": "application/json, text/event-stream"}
    key = os.getenv("MCP_API_KEYS", "").split(",")[0].strip()
    if key:
        headers["authorization"] = "Bearer " + key
    report = {"checked_at": datetime.now(timezone.utc).isoformat(), "cases": []}
    with httpx.Client(timeout=90) as client:
        # Separate connection/warm-up readiness from product failures. The first
        # candidate run raced local startup; it is not an application regression.
        ready = False
        for _ in range(30):
            try:
                probe = client.post(args.url,headers=headers,json={"jsonrpc":"2.0","id":0,"method":"tools/call",
                    "params":{"name":"istanbul_events_search","arguments":{"limit":1}}})
                probe.raise_for_status()
                value=probe.json()["result"]
                payload=value.get("structuredContent") or json.loads(value["content"][0]["text"])
                if payload["ok"] and payload["sources"] and all(s["coverage_status"]=="checked" for s in payload["sources"]):
                    ready=True
                    report["source_snapshots"]=[{k:s.get(k) for k in ("publisher","last_successful_refresh_at","accepted_total")} for s in payload["sources"]]
                    break
            except (httpx.ConnectError,httpx.ReadTimeout):
                pass
            time.sleep(2)
        if not ready:
            print(json.dumps({"preflight_failed":"source_or_server_not_ready"}))
            raise SystemExit(2)
        for case in json.loads(CASES.read_text()):
            started = time.monotonic()
            try:
                r = client.post(args.url, headers=headers, json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": case["tool"], "arguments": case["arguments"]}})
                r.raise_for_status()
                result = r.json()["result"]
                payload = result.get("structuredContent") or json.loads(result["content"][0]["text"])
                ResponseEnvelope.model_validate(payload)
                errors, observations = inspect_result(case, payload)
            except Exception as exc:
                errors, observations = ["request_failed:" + type(exc).__name__], {}
            row = {"id": case["id"], "persona": case["persona"], "question": case["question"],
                   "errors": sorted(set(errors)), "elapsed_ms": round((time.monotonic() - started) * 1000), **observations}
            report["cases"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
            time.sleep(0.15)
        selection=selection_workflow(client,args.url,headers)
        report["cases"].append(selection)
        print(json.dumps(selection,ensure_ascii=False),flush=True)
    report["failed"] = sum(bool(row["errors"]) for row in report["cases"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(report["cases"]), "failed": report["failed"]}))
    raise SystemExit(bool(report["failed"]))


if __name__ == "__main__":
    main()
