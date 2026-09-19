"""Contract tests for POST /api/form-fill.

The live Chromium path is proven by real runs (ticket-booking demo); here we
lock validation (422s) and the route wiring with the pipeline stubbed - the
same isolation pattern the rest of this suite uses (cf. FakeSession).
"""
import pytest

import app.api.routes_formfill as ff


def test_form_fill_rejects_bad_scheme(client):
    r = client.post("/api/form-fill", json={"url": "ftp://x", "values": {"a": "b"}})
    assert r.status_code == 422


def test_form_fill_rejects_empty_values(client):
    r = client.post("/api/form-fill", json={"url": "https://example.com", "values": {}})
    assert r.status_code == 422


def test_form_fill_returns_pipeline_result(client, monkeypatch):
    class FakeAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            assert url.startswith("data:")
            assert user_values == {"Name": "Asha"}
            return {"status": "success", "episode_id": "e1",
                    "success_count": 1, "failure_count": 0}

    monkeypatch.setattr(ff, "FormAgent", FakeAgent)
    r = client.post("/api/form-fill",
                    json={"url": "data:text/html,<form></form>", "values": {"Name": "Asha"}})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"


def test_form_fill_maps_browser_failure_to_502(client, monkeypatch):
    class BoomAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            raise RuntimeError("chromium exploded")

    monkeypatch.setattr(ff, "FormAgent", BoomAgent)
    r = client.post("/api/form-fill",
                    json={"url": "https://example.com", "values": {"a": "b"}})
    assert r.status_code == 503
