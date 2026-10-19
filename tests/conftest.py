"""Tests pin the default public mode so ambient secrets never change behavior."""
import os

import pytest

# app.main creates its default ASGI app at import time, before fixtures run.
os.environ["MCP_AUTH_REQUIRED"] = "false"
os.environ.pop("MCP_API_KEYS", None)
os.environ.pop("FORWARDED_ALLOW_IPS", None)


@pytest.fixture(autouse=True)
def isolate_runtime_settings():
    from app.core.settings import get_settings
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
