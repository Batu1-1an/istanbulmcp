"""Opt-in combined-filter and modest concurrent-read checks against a running MCP."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from itertools import product
import json
import os
from pathlib import Path
import time

import httpx

from app.core.events import ISTANBUL
from scripts.events_100_uat import inspect_case
from scripts.events_persona_uat import call_tool


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url",default="https://istanbulmcp-production.up.railway.app/mcp/")
    parser.add_argument("--output",type=Path,default=Path(".data/events-cross-live.json"))
    args=parser.parse_args()
    headers={"accept":"application/json, text/event-stream"}
    key=os.getenv("MCP_API_KEYS","").split(",")[0].strip()
    if key:headers["authorization"]="Bearer "+key
    cases=[]
    for category,budget,district in product(("family","theatre","concert"),(0,500),("Kadıköy","Beşiktaş")):
        cases.append(("search",dict(category=category,max_price_try=budget,district=district,include_unknown_prices=False,limit=10)))
    for radius in (100,500,3000,20000):
        cases.append(("search",dict(lat=40.99,lon=29.03,radius_m=radius,limit=10)))
    for age in (0,5,17):cases.append(("search",dict(child_age=age,limit=10)))
    for start,end in (("00:00","09:00"),("12:00","17:00"),("23:00","23:59")):
        cases.append(("search",dict(time_from=start,time_to=end,limit=10)))
    for query in ("Sıla","sila","çocuk","\"çocuk\""):
        cases.append(("search",dict(query=query,limit=10)))
    cases += [("plan",dict(date="tomorrow",start_time="09:00",end_time="20:00",interests=["family"],child_age=5,require_known_end=True)),
              ("plan",dict(date="tomorrow",interests=["concert","theatre"],max_price_try=500,min_gap_minutes=60))]
    report={"started_at":datetime.now(ISTANBUL).isoformat(),"results":[]}
    with httpx.Client(timeout=90) as client:
        r=client.post(args.url,headers=headers,json={"jsonrpc":"2.0","id":0,"method":"initialize","params":{
            "protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"events-cross-uat","version":"1"}}})
        r.raise_for_status();report["server_version"]=r.json()["result"]["serverInfo"]["version"]
        for _ in range(60):
            seed=call_tool(client,args.url,headers,"istanbul_events_search",{"limit":1})
            if seed["ok"] and seed["sources"] and all(s["coverage_status"]=="checked" for s in seed["sources"]):
                report["source_snapshots"]=[{key:s.get(key) for key in (
                    "publisher","coverage_status","serving_stale","last_successful_refresh_at","accepted_total")}
                    for s in seed["sources"]]
                break
            time.sleep(2)
        else:raise SystemExit("preflight_failed: configured sources not ready")
        def execute(kind,values,identity,session):
            started=time.monotonic()
            try:
                payload=call_tool(session,args.url,headers,"istanbul_events_"+kind,values)
                failures,observations=inspect_case({"tool":kind,"expect":"ok"},values,payload)
                observations["freshness"]=payload["freshness"]["status"]
            except Exception as exc:failures,observations=[type(exc).__name__],{}
            return {"id":identity,"tool":kind,"arguments":values,"errors":failures,
                    "elapsed_ms":round((time.monotonic()-started)*1000),**observations}
        for i,(kind,values) in enumerate(cases,1):
            report["results"].append(execute(kind,values,f"C{i:02d}",client))
            time.sleep(.25)
    def concurrent_read(index):
        with httpx.Client(timeout=30) as session:
            return execute("search",{"date_from":"tomorrow","limit":3},f"R{index+1:02d}",session)
    with ThreadPoolExecutor(max_workers=4) as pool:
        report["results"].extend(pool.map(concurrent_read,range(8)))
    report["completed_at"]=datetime.now(ISTANBUL).isoformat()
    report["failed"]=sum(bool(row["errors"]) for row in report["results"])
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"cases":len(report["results"]),"failed":report["failed"],"version":report["server_version"]}))
    raise SystemExit(bool(report["failed"]))


if __name__=="__main__":main()
