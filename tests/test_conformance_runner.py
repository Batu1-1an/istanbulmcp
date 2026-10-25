import json
from pathlib import Path

import pytest

from scripts.check_mcp_conformance import check_reports


@pytest.mark.parametrize("checks,expected", [
    ([{"status": "SUCCESS"}], True),
    ([{"status": "SUCCESS"}, {"status": "FAILURE"}], False),
    ([{"status": "WARNING"}], False),
    ([], False), ({"status": "SUCCESS"}, False), ([None], False),
])
def test_official_reports_fail_closed(tmp_path, checks, expected):
    (tmp_path / "checks.json").write_text(json.dumps(checks))
    assert check_reports(tmp_path)[0] is expected


def test_missing_malformed_or_duplicate_reports_fail(tmp_path):
    assert check_reports(tmp_path) == (False, 0)
    (tmp_path / "checks.json").write_text("not JSON")
    assert check_reports(tmp_path) == (False, 0)
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "checks.json").write_text('[{"status":"SUCCESS"}]')
    assert check_reports(tmp_path) == (False, 0)


def test_profile_and_lockfile_pin_the_same_official_package():
    directory = Path(__file__).parent / "conformance"
    profile = json.loads((directory / "profile.json").read_text())
    package = json.loads((directory / "package.json").read_text())
    lock = json.loads((directory / "package-lock.json").read_text())
    assert package["devDependencies"] == {profile["package"]: profile["version"]}
    dependency = lock["packages"]["node_modules/" + profile["package"]]
    assert dependency["version"] == profile["version"]
    assert dependency["integrity"].startswith("sha512-")
    assert len(profile["scenarios"]) == len(set(profile["scenarios"])) == 5


@pytest.mark.parametrize("exit_code,status,expected", [
    (0, "SUCCESS", True), (1, "SUCCESS", False), (0, "FAILURE", False), (0, None, False),
])
def test_runner_requires_both_exit_success_and_successful_report(monkeypatch, tmp_path, exit_code, status, expected):
    from types import SimpleNamespace
    from scripts import check_mcp_conformance as runner

    profile = json.loads(runner.PROFILE.read_text())
    package = tmp_path / "package"
    package.mkdir()
    (package / "package.json").write_text(json.dumps({"name": profile["package"], "version": profile["version"]}))
    monkeypatch.setattr(runner, "PACKAGE", package)

    class FakeServer:
        def __init__(self, directory, env):
            assert env == {}
            self.base = "http://127.0.0.1:1234"
            (directory / "server.log").write_text("fixture server logs\n")

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            pass

    def fake_run(command, **options):
        destination = Path(command[command.index("--output-dir") + 1])
        if status:
            (destination / "checks.json").write_text(json.dumps([{"status": status}]))
        assert options["timeout"] == 60
        return SimpleNamespace(returncode=exit_code)

    monkeypatch.setattr(runner, "Server", FakeServer)
    monkeypatch.setattr(runner.subprocess, "run", fake_run)
    output = tmp_path / "output"
    assert runner.run(output) is expected
    summary = json.loads((output / "summary.json").read_text())
    assert summary["ok"] is expected and len(summary["scenarios"]) == 5
    assert (output / "server.log").read_text() == "fixture server logs\n"
    with pytest.raises(ValueError, match="empty output"):
        runner.run(output)
