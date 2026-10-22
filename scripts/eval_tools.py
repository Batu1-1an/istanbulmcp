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


async def footprint(server=None) -> dict:
    server = server if server is not None else mcp
    tools = [tool.model_dump(by_alias=True, exclude_none=True) for tool in await server.list_tools()]
    without_output = [{key: value for key, value in tool.items() if key != "outputSchema"} for tool in tools]

    def size(value) -> int:
        return len(json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode())

    total = size(tools)
    input_only = size(without_output)
    resources = await server.list_resources()
    prompts = await server.list_prompts()
    return {
        "tool_count": len(tools), "definition_utf8_bytes": total,
        "definition_without_output_schema_utf8_bytes": input_only,
        "output_schema_overhead_utf8_bytes": total - input_only,
        "structured_tool_count": sum("outputSchema" in tool for tool in tools),
        "tool_names": [tool["name"] for tool in tools],
        "resource_count": len(resources), "prompt_count": len(prompts),
        "instructions_utf8_bytes": len((server.instructions or "").encode()),
    }


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
