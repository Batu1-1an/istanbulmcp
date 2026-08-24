from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_BASE_URL = "https://istanbulmcp-production.up.railway.app/mcp/"


@dataclass(frozen=True)
class Flow:
    question: str
    tool: str
    args: dict[str, Any]
    min_data: int = 0
    expect_ok: bool = True


CRITICAL_FLOWS = [
    Flow("Servis sağlıklı mı?", "istanbul_health", {}, min_data=1),
    Flow("Trafik catalog araması sonuç veriyor mu?", "istanbul_search_datasets", {"query": "trafik", "limit": 2}, min_data=1),
    Flow("Taksim yakınında şehir verisi var mı?", "istanbul_nearby", {"lat": 41.0369, "lon": 28.9850, "radius_m": 1000, "limit": 3}, min_data=1),
    Flow("Kadıköy otopark verisi var mı?", "istanbul_parking_nearby", {"lat": 40.9909, "lon": 29.0303, "radius_m": 1500, "limit": 3}, min_data=1),
    Flow("Levent metro istasyonları dönüyor mu?", "istanbul_metro_stations_nearby", {"lat": 41.0812, "lon": 29.0105, "radius_m": 1500, "limit": 3}, min_data=1),
    Flow("Kadıköy hava kalitesi istasyonları dönüyor mu?", "istanbul_air_quality_nearby", {"lat": 40.9909, "lon": 29.0303, "radius_m": 5000, "limit": 3}, min_data=1),
    Flow("İstanbul trafik index dönüyor mu?", "istanbul_traffic_status", {}, min_data=1),
    Flow("Kadıköy Rıhtım yakın mobilite özeti dönüyor mu?", "istanbul_mobility_nearby", {"place": "Kadıköy Rıhtım", "radius_m": 1500, "limit": 3}, min_data=1),
    Flow("Başakşehir merkez sorusu ilçe otoparkı olarak mesafesiz dönüyor mu?", "istanbul_mobility_nearby", {"place": "Başakşehir merkez", "radius_m": 1500, "limit": 5}, min_data=1),
    Flow("Taksim yakın şehir hizmetleri dönüyor mu?", "istanbul_city_services_nearby", {"place": "Taksim", "radius_m": 1500, "limit": 3}, min_data=1),
    Flow("Başakşehir ilçe otoparkları mesafesiz dönüyor mu?", "istanbul_parking_by_district", {"district": "Başakşehir", "limit": 5}, min_data=1),
    Flow("Kadıköy Caferağa mahalle profili dönüyor mu?", "istanbul_neighborhood_profile", {"district": "Kadıköy", "neighborhood": "Caferağa"}, min_data=1),
    Flow("Kadıköy mahalle profil adayları listeleniyor mu?", "istanbul_neighborhood_profile", {"district": "Kadıköy", "limit": 3}, min_data=1),
    Flow("34A hat bilgisi dönüyor mu?", "istanbul_transit_line_info", {"line_code": "34A"}, min_data=1),
    Flow("34A durakları dönüyor mu?", "istanbul_stops_for_line", {"line_code": "34A"}, min_data=1),
    Flow("İETT duyuruları dönüyor mu?", "istanbul_transit_disruptions", {}, min_data=1),
    Flow("34A planlanan kalkışları dönüyor mu?", "istanbul_planned_departures", {"line_code": "34A", "limit": 5}, min_data=1),
    Flow("Invalid radius envelope dönüyor mu?", "istanbul_air_quality_nearby", {"lat": 40.9909, "lon": 29.0303, "radius_m": 7000, "limit": 1}, expect_ok=False),
]


def rpc_call(base_url: str, request_id: int, tool: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None, float]:
    payload = {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": tool, "arguments": args},
    }
    request = urllib.request.Request(
        base_url,
        data=json.dumps(payload).encode(),
        headers={
            "accept": "application/json, text/event-stream",
            "content-type": "application/json",
        },
        method="POST",
    )
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = json.loads(response.read())
        elapsed = time.perf_counter() - started
        result = body.get("result", {})
        text = (result.get("content") or [{}])[0].get("text", "")
        if result.get("isError"):
            return None, text or "tool returned isError", elapsed
        return json.loads(text), None, elapsed
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}", time.perf_counter() - started


def run_flows(base_url: str) -> dict[str, Any]:
    rows = []
    for index, flow in enumerate(CRITICAL_FLOWS, start=1):
        payload, error, elapsed = rpc_call(base_url, 5000 + index, flow.tool, flow.args)
        data_count = len(payload.get("data") or []) if isinstance(payload, dict) else 0
        ok = payload.get("ok") if isinstance(payload, dict) else False
        passed = error is None and ok is flow.expect_ok and data_count >= flow.min_data
        rows.append(
            {
                "n": index,
                "question": flow.question,
                "tool": flow.tool,
                "args": flow.args,
                "passed": passed,
                "elapsed_ms": round(elapsed * 1000, 1),
                "ok": ok,
                "data_count": data_count,
                "summary": payload.get("summary") if isinstance(payload, dict) else error,
                "warnings": payload.get("warnings") if isinstance(payload, dict) else [],
            }
        )
        time.sleep(0.35)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": base_url,
        "passed": sum(1 for row in rows if row["passed"]),
        "failed": sum(1 for row in rows if not row["passed"]),
        "flows": rows,
    }


def run_performance_samples(base_url: str, sample_count: int) -> dict[str, Any] | None:
    if sample_count <= 0:
        return None

    # Warm the same transit cache used by the timed calls, but exclude this
    # request from the latency ratio.
    rpc_call(base_url, 7000, "istanbul_transit_disruptions", {})
    samples = []
    for index in range(sample_count):
        payload, error, elapsed = rpc_call(
            base_url,
            7001 + index,
            "istanbul_transit_disruptions",
            {"limit": 5},
        )
        samples.append(
            {
                "n": index + 1,
                "elapsed_ms": round(elapsed * 1000, 1),
                "within_five_seconds": error is None and isinstance(payload, dict) and payload.get("ok") is True and elapsed <= 5,
                "ok": isinstance(payload, dict) and payload.get("ok") is True,
                "error": error,
            }
        )
    within_five_seconds = sum(1 for sample in samples if sample["within_five_seconds"])
    ratio = within_five_seconds / sample_count
    return {
        "tool": "istanbul_transit_disruptions",
        "warmup": "one untimed request",
        "sample_count": sample_count,
        "within_five_seconds": within_five_seconds,
        "within_five_seconds_ratio": round(ratio, 4),
        "threshold": 0.95,
        "passed": ratio >= 0.95,
        "samples": samples,
    }


def write_reports(report: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"live-mcp-uat-{stamp}.json"
    md_path = output_dir / f"live-mcp-uat-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# Live MCP UAT",
        "",
        f"**Generated:** {report['generated_at']}",
        f"**Endpoint:** `{report['base_url']}`",
        f"**Passed:** {report['passed']}",
        f"**Failed:** {report['failed']}",
        "",
        "| # | Result | Tool | Question | Data | ms | Summary |",
        "|---|--------|------|----------|------|----|---------|",
    ]
    for row in report["flows"]:
        result = "PASS" if row["passed"] else "FAIL"
        summary = str(row.get("summary") or "").replace("|", "\\|")[:160]
        question = row["question"].replace("|", "\\|")
        lines.append(f"| {row['n']} | {result} | `{row['tool']}` | {question} | {row['data_count']} | {row['elapsed_ms']} | {summary} |")
    performance = report.get("performance")
    if performance:
        lines.extend(
            [
                "",
                "## Warm-cache performance",
                "",
                f"- Tool: `{performance['tool']}`",
                f"- Samples: {performance['sample_count']} plus one untimed warm-up",
                f"- Within 5 seconds: {performance['within_five_seconds']} ({performance['within_five_seconds_ratio']:.1%})",
                f"- Threshold: {performance['threshold']:.1%}",
                f"- Result: {'PASS' if performance['passed'] else 'FAIL'}",
            ]
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Run opt-in live MCP UAT flows.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output-dir", default=".planning/reports")
    parser.add_argument(
        "--performance-samples",
        type=int,
        default=0,
        help="Run a warm-cache transit timing sample (use at least 20).",
    )
    args = parser.parse_args()
    if 0 < args.performance_samples < 20:
        parser.error("--performance-samples must be 0 or at least 20")

    report = run_flows(args.base_url)
    report["performance"] = run_performance_samples(args.base_url, args.performance_samples)
    json_path, md_path = write_reports(report, Path(args.output_dir))
    performance = report["performance"]
    performance_failed = bool(performance and not performance["passed"])
    print(f"PASS={report['passed']} FAIL={report['failed']} PERFORMANCE_FAIL={int(performance_failed)}")
    print(f"JSON={json_path}")
    print(f"MD={md_path}")
    return 0 if report["failed"] == 0 and not performance_failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
