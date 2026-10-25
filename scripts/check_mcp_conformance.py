"""Run selected pinned official checks against the real disposable local app."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from scripts.smoke_mcp import ROOT, Server

PROFILE = ROOT / "tests/conformance/profile.json"
PACKAGE = ROOT / "tests/conformance/node_modules/@modelcontextprotocol/conformance"


def check_reports(directory: Path) -> tuple[bool, int]:
    """Missing, empty, malformed, failed or warning-only reports fail closed."""
    reports = list(directory.rglob("checks.json"))
    if len(reports) != 1:
        return False, 0
    try:
        checks = json.loads(reports[0].read_text())
    except (OSError, ValueError):
        return False, 0
    if not isinstance(checks, list) or not checks:
        return False, 0
    return all(isinstance(check, dict) and check.get("status") == "SUCCESS" for check in checks), len(checks)


def run(output: Path) -> bool:
    profile = json.loads(PROFILE.read_text())
    installed = json.loads((PACKAGE / "package.json").read_text())
    if installed["version"] != profile["version"] or installed["name"] != profile["package"]:
        raise RuntimeError("Installed conformance package does not match the pinned profile; run npm ci")
    output = output.resolve()
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use an empty output directory; existing evidence is never overwritten")
    output.mkdir(parents=True, exist_ok=True)
    summary = {"ok": False, "package": profile["package"], "version": profile["version"],
               "surface": "real python -m app.main subprocess", "coverage": profile["coverage"],
               "scenarios": []}
    try:
        with tempfile.TemporaryDirectory(prefix="istanbul-mcp-conformance-") as raw:
            directory = Path(raw)
            try:
                # Server supplies a clean environment. No deploy secrets, auth,
                # GTFS warm-up, or external city-data calls are needed here.
                with Server(directory, {}) as server:
                    for scenario in profile["scenarios"]:
                        destination = output / scenario
                        destination.mkdir()
                        exit_code = None
                        with (destination / "cli.log").open("w") as log:
                            try:
                                completed = subprocess.run([
                                    "node", str(PACKAGE / "dist/index.js"), "server",
                                    "--url", server.base + "/mcp/", "--scenario", scenario,
                                    "--output-dir", str(destination),
                                ], cwd=ROOT, env={"PATH": os.environ.get("PATH", os.defpath), "NO_COLOR": "1"},
                                    stdout=log, stderr=subprocess.STDOUT, timeout=60)
                                exit_code = completed.returncode
                            except (subprocess.TimeoutExpired, OSError) as exc:
                                log.write(f"\nRunner failure: {type(exc).__name__}\n")
                        reports_ok, checks = check_reports(destination)
                        passed = exit_code == 0 and reports_ok
                        summary["scenarios"].append({"name": scenario, "passed": passed,
                                                     "exit_code": exit_code, "checks": checks})
                        print(f"{scenario}: {'PASS' if passed else 'FAIL'} ({checks} checks)", flush=True)
                    summary["ok"] = all(item["passed"] for item in summary["scenarios"])
            finally:
                if (directory / "server.log").exists():
                    shutil.copyfile(directory / "server.log", output / "server.log")
    finally:
        (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary["ok"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / ".artifacts/conformance")
    args = parser.parse_args()
    raise SystemExit(0 if run(args.output) else 1)


if __name__ == "__main__":
    main()
