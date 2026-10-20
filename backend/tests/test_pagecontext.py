"""Contract tests for POST /api/page-context (offline: validation only).

The live Chromium path is proven by real runs against public pages; here we
lock the guard wiring (SSRF refusals) with no browser involved.
"""
from app.api import routes_pagecontext as pc


def test_page_context_refuses_private_and_file(client, monkeypatch):
    from app.api.url_guard import LOCAL_TARGETS_ENV
    # Pin the local-targets opt-in OFF: compose sets it ON for the bundled demo
    # pages, and this test asserts the default (deployed) policy.
    monkeypatch.setenv(LOCAL_TARGETS_ENV, "0")
    for bad in ["http://169.254.169.254/", "file:///etc/passwd",
                "http://10.0.0.1/", "ftp://x/y"]:
        r = client.post("/api/page-context", json={"url": bad})
        assert r.status_code == 422, (bad, r.text)


def test_page_context_requires_url(client):
    assert client.post("/api/page-context", json={"url": ""}).status_code == 422
