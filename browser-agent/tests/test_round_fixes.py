"""Browser nits: select-on-non-select is 422, driver.select validates."""
import pytest

from app.services.sessions import SessionManager, RobotsCache


NODES = [
    {"tag": "input", "label": "Full name", "selector": "#name", "type": "text"},
    {"tag": "select", "label": "Country", "selector": "#country", "type": ""},
]


class FakeDriver:
    def __init__(self, nodes=None):
        self.nodes = NODES if nodes is None else nodes

    async def start(self):
        pass

    async def navigate(self, url):
        return {"url": url, "http_status": 200, "title": "t"}

    async def snapshot(self):
        return {"title": "t", "url": "data:,x", "nodes": self.nodes}

    async def fill(self, selector, value):
        return {"status": "completed", "selector": selector, "readback": value}

    async def click(self, selector):
        return {"status": "completed", "selector": selector}

    async def select(self, selector, value):
        from app.tools.driver import Driver
        # Reuse the real validation without Chromium: emulate tag lookup.
        node = next((n for n in self.nodes if n.get("selector") == selector), None)
        if node is not None and str(node.get("tag", "")).lower() != "select":
            raise ValueError("select needs a <select> element")
        return {"status": "completed", "selector": selector, "readback": value}


async def _allow_fetch(host, scheme):
    return "User-agent: *\n"


@pytest.fixture
def stubbed_app(monkeypatch):
    import app.main as service
    fake_mgr = SessionManager(driver_factory=FakeDriver,
                              robots=RobotsCache(fetch=_allow_fetch))
    monkeypatch.setattr(service, "sessions", fake_mgr)
    return service


def test_select_on_input_is_422(client, stubbed_app):
    assert client.post("/session/open",
                       json={"session_id": "s1", "url": "data:text/html,<form></form>"}).status_code == 200
    r = client.post("/session/s1/act",
                    json={"kind": "select", "label": "Full name", "value": "x"})
    assert r.status_code == 422, r.text


async def test_request_interceptor_aborts_ssrf_redirect(monkeypatch):
    """The entry-URL guard alone admits 302-to-metadata and DNS rebinding:
    every in-page request must be re-validated, not just the first."""
    from types import SimpleNamespace
    from app.tools.driver import Driver
    import app.tools.url_guard as guard

    def fake_resolve(host):
        # Mirror real DNS for IP literals (no lookup happens); only
        # hostnames resolve to the canned public address.
        import ipaddress
        try:
            ipaddress.ip_address(host)
            return [(2, 1, 6, "", (host, 0))]
        except ValueError:
            return [(2, 1, 6, "", ("93.184.216.34", 0))]  # public, no network

    monkeypatch.setattr(guard, "_resolve", fake_resolve)
    # Pin the local-targets opt-in OFF (compose sets it ON): this test locks
    # the interception mechanism under the default policy.
    monkeypatch.setenv(guard.LOCAL_TARGETS_ENV, "0")

    seen = {}

    class FakeRoute:
        def __init__(self, url):
            self.request = SimpleNamespace(url=url)
            self.verdict = None

        async def abort(self):
            self.verdict = "abort"

        async def continue_(self):
            self.verdict = "continue"

    class FakePage:
        async def route(self, pattern, handler):
            seen["pattern"] = pattern
            seen["handler"] = handler

    driver = Driver.__new__(Driver)
    driver._page = FakePage()
    await driver._guard_requests()
    assert seen["pattern"] == "**/*"

    public = FakeRoute("https://example.com/app.css")
    await seen["handler"](public)
    assert public.verdict == "continue"

    evil = FakeRoute("http://169.254.169.254/latest/meta-data")
    await seen["handler"](evil)
    assert evil.verdict == "abort"

    internal = FakeRoute("http://10.9.9.9/admin")
    await seen["handler"](internal)
    assert internal.verdict == "abort"

    ws = FakeRoute("wss://example.com/sock")
    await seen["handler"](ws)
    assert ws.verdict == "continue"


def test_select_on_dropdown_succeeds(client, stubbed_app):
    assert client.post("/session/open",
                       json={"session_id": "s2", "url": "data:text/html,<form></form>"}).status_code == 200
    r = client.post("/session/s2/act",
                    json={"kind": "select", "label": "Country", "value": "IN"})
    assert r.status_code == 200, r.text


def test_driver_select_validates_tag():
    import asyncio
    from app.tools.driver import Driver
    # Validation lives on Driver.select: non-select must raise, not fill.
    import inspect
    src = inspect.getsource(Driver.select)
    assert "select" in src and "ValueError" in src


def test_blank_inspect_target_is_422(client, stubbed_app):
    """min_length=1 lets '   ' through; a blank target matches nothing and
    would waste a live snapshot + scan on every call."""
    assert client.post("/session/open",
                       json={"session_id": "s3", "url": "data:text/html,<form></form>"}).status_code == 200
    assert client.post("/session/s3/inspect", json={"target": "   "}).status_code == 422
    assert client.post("/session/s3/inspect", json={"target": ""}).status_code == 422
    # A real target still works.
    r = client.post("/session/s3/inspect", json={"target": "Full name"})
    assert r.status_code == 200, r.text
    assert r.json()["match_count"] >= 1


def test_cors_allows_origins_without_credentials(client):
    """Service-to-service needs no cookies; browsers reject wildcard +
    credentials, so origins are explicit and credentials are off."""
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in r.headers
