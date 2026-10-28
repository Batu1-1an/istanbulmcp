"""Restart the process when the event loop stops answering.

A single-process server with a frozen loop (a spin or a blocking call) keeps
its port open and looks "running" to the platform while serving nothing. A
daemon thread pings the loop; after `timeout_seconds` without an answer it
writes every thread's stack to stderr and exits non-zero, so the platform's
on-failure restart policy brings the service back.
"""
from __future__ import annotations

import asyncio
import faulthandler
import math
import os
import sys
import threading
import time
from collections.abc import Callable

from app.core.settings import Settings

STALL_EXIT_CODE = 70


def validate_watchdog_settings(settings: Settings) -> None:
    value = settings.event_loop_watchdog_seconds
    if not math.isfinite(value) or not (value == 0 or 5 <= value <= 3600):
        raise ValueError("EVENT_LOOP_WATCHDOG_SECONDS must be 0 (disabled) or between 5 and 3600")


def dump_stacks_and_exit(stalled_seconds: float) -> None:
    # No logging module here: a frozen loop may hold a handler lock. The timer
    # still exits if the dump itself blocks, for example on a full stderr pipe.
    threading.Timer(5.0, os._exit, args=(STALL_EXIT_CODE,)).start()
    os.write(2, f'event="event_loop_stalled" stalled_seconds={stalled_seconds:.0f} action="dump_stacks_and_exit"\n'.encode())
    faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    os._exit(STALL_EXIT_CODE)


class EventLoopWatchdog:
    def __init__(self, loop: asyncio.AbstractEventLoop, *, timeout_seconds: float,
                 on_stall: Callable[[float], None] = dump_stacks_and_exit):
        self.loop = loop
        self.timeout_seconds = timeout_seconds
        self.interval_seconds = min(5.0, timeout_seconds / 4)
        self.on_stall = on_stall
        self._last_beat = time.monotonic()
        self._stopped = threading.Event()
        self._thread = threading.Thread(target=self._run, name="event-loop-watchdog", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopped.set()

    def _beat(self) -> None:
        self._last_beat = time.monotonic()

    def _run(self) -> None:
        while not self._stopped.wait(self.interval_seconds):
            stalled = time.monotonic() - self._last_beat
            if stalled > self.timeout_seconds:
                self.on_stall(stalled)
                return
            try:
                self.loop.call_soon_threadsafe(self._beat)
            except RuntimeError:
                return  # The loop closed during shutdown.
