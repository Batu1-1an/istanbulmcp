"""Tests pin the default public mode so ambient secrets never change behavior."""
import os

import pytest

# app.main creates its default ASGI app at import time, before fixtures run.
os.environ["MCP_AUTH_REQUIRED"] = "false"
os.environ["GTFS_SCHEDULE_ENABLED"] = "false"
# The production watchdog exits the process; never let it kill pytest.
os.environ["EVENT_LOOP_WATCHDOG_SECONDS"] = "0"
os.environ.pop("MCP_API_KEYS", None)
os.environ.pop("MCP_CORS_ALLOWED_ORIGINS", None)
os.environ.pop("FORWARDED_ALLOW_IPS", None)
os.environ.pop("IBB_RELAY_BASE_URL", None)
os.environ.pop("IBB_RELAY_TOKEN", None)


@pytest.fixture(autouse=True)
def isolate_runtime_settings():
    from app.core.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def isolate_unreachable_hosts():
    from app.connectors.http_retry import reset_unreachable_hosts
    reset_unreachable_hosts()
    yield
    reset_unreachable_hosts()
