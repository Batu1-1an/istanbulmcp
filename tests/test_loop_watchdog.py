import asyncio
import threading
import time

import pytest
from starlette.testclient import TestClient

from app.core.loop_watchdog import EventLoopWatchdog, validate_watchdog_settings
from app.core.settings import Settings
from app.main import create_app


@pytest.mark.asyncio
async def test_watchdog_reports_a_frozen_event_loop():
    stalls = []
    reported = threading.Event()

    def on_stall(seconds):
        stalls.append(seconds)
        reported.set()

    watchdog = EventLoopWatchdog(asyncio.get_running_loop(), timeout_seconds=0.2, on_stall=on_stall)
    watchdog.start()
    try:
        time.sleep(0.6)  # Blocks the loop like the production spin did.
        assert reported.wait(1)
    finally:
        watchdog.stop()
    assert len(stalls) == 1 and stalls[0] > 0.2


@pytest.mark.asyncio
async def test_watchdog_stays_quiet_while_the_loop_answers():
    stalls = []
    watchdog = EventLoopWatchdog(asyncio.get_running_loop(), timeout_seconds=0.2, on_stall=stalls.append)
    watchdog.start()
    await asyncio.sleep(0.8)
    watchdog.stop()
    assert stalls == []


@pytest.mark.parametrize("value", [-1, 1, 4.9, 3601, float("nan"), float("inf")])
def test_watchdog_setting_rejects_unsafe_values(value):
    with pytest.raises(ValueError, match="EVENT_LOOP_WATCHDOG_SECONDS"):
        validate_watchdog_settings(Settings(event_loop_watchdog_seconds=value))


@pytest.mark.parametrize("value", [0, 5, 60, 3600])
def test_watchdog_setting_accepts_disabled_or_bounded_values(value):
    validate_watchdog_settings(Settings(event_loop_watchdog_seconds=value))


def test_app_runs_the_watchdog_only_while_serving(monkeypatch, tmp_path):
    monkeypatch.setenv("EVENT_LOOP_WATCHDOG_SECONDS", "30")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "watchdog.sqlite3"))
    with TestClient(create_app(), base_url="http://localhost") as client:
        assert client.get("/healthz").status_code == 200
        watchdogs = [t for t in threading.enumerate() if t.name == "event-loop-watchdog" and t.is_alive()]
        assert len(watchdogs) == 1
    watchdogs[0].join(1)
    assert not watchdogs[0].is_alive()
