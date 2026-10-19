"""Inspect the tool definition footprint and optionally score external predictions.

No model is called. Predictions are JSON objects keyed by scenario id, with
{"tool": "...", "arguments": {...}} values. This reports exact matches only;
the pytest suite separately exercises dispatch and envelope preservation.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from app.mcp.server import mcp

CASES_PATH = Path(__file__).resolve().parents[1] / "tests/fixtures/evals/city_questions.json"


def score_predictions(cases: list[dict], predictions: dict) -> dict:
    correct = sum(
        predictions.get(case["id"]) == {"tool": case["tool"], "arguments": case["arguments"]}
        for case in cases
    )
    return {"exact_matches": correct, "total": len(cases)}


async def footprint() -> dict:
    tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in await mcp.list_tools()]
    encoded = json.dumps(tools, ensure_ascii=False, separators=(",", ":"))
    return {"tool_count": len(tools), "definition_utf8_bytes": len(encoded.encode()),
            "tool_names": [tool["name"] for tool in tools]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path)
    args = parser.parse_args()
    report = asyncio.run(footprint())
    report["measurement"] = "serialized tools/list definitions; bytes are not tokens"
    if args.predictions:
        cases = json.loads(CASES_PATH.read_text())["cases"]
        report["external_predictions"] = score_predictions(
            cases, json.loads(args.predictions.read_text())
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
