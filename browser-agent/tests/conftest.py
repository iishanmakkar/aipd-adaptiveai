"""Pytest bootstrap for the browser-agent suite.

Session/driver tests use fakes (no Chromium, no network); live tests are
marked and deselected by default, matching every other service.
"""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SERVICE_ROOT = os.path.dirname(_HERE)

if _SERVICE_ROOT not in sys.path:
    sys.path.insert(0, _SERVICE_ROOT)

import pytest  # noqa: E402


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    import app.main as service
    with TestClient(service.app, raise_server_exceptions=False) as c:
        yield c
