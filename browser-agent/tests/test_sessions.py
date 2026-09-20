"""Live-session safety net, offline: sessions, confirmations, guards.

Every test here uses a fake Driver ( scripted snapshots, no Chromium) and a
fake robots fetcher (no network), so the suite proves the SAFETY LOGIC -
proposal gating, TTL sweep, budgets, robots parsing, CAPTCHA refusal - without
spending anything. Real-Chromium proofs live in the Round 8 fix log.
"""
import pytest

from app.services import sessions as mod
from app.services.sessions import (
    SessionManager, RateBudget, RobotsCache,
    is_sensitive_url, is_submit_text, detect_captcha,
)


NODES = [
    {"tag": "input", "label": "Full name", "selector": "#name", "type": "text"},
    {"tag": "input", "label": "Email address", "selector": "#email", "type": "email"},
    {"tag": "button", "label": "Book tickets", "selector": "#book", "type": "submit"},
    {"tag": "button", "label": "Clear form", "selector": "#clear", "type": "button"},
]


class FakeDriver:
    """Scripted stand-in for Driver: real method shapes, canned page."""

    def __init__(self, nodes=None, title="Demo", captcha=False):
        self.nodes = NODES if nodes is None else nodes
        self.title = "Verify you are human" if captcha else title
        self.started = False
        self.stopped = False
        self.clicked = []
        self.filled = []

    async def start(self):
        self.started = True

    async def stop(self):
        self.stopped = True

    async def navigate(self, url):
        return {"url": url, "http_status": 200, "title": self.title}

    async def snapshot(self):
        return {"title": self.title, "url": "data:,x", "nodes": self.nodes}

    async def fill(self, selector, value):
        self.filled.append((selector, value))
        return {"status": "completed", "selector": selector, "readback": value}

    async def click(self, selector):
        self.clicked.append(selector)
        return {"status": "completed", "selector": selector}


def make_manager(**kw):
    kw.setdefault("driver_factory", FakeDriver)
    return SessionManager(**kw)


async def test_open_and_reuse_same_session():
    mgr = make_manager()
    a = await mgr.open("chat-1")
    b = await mgr.open("chat-1")
    assert a is b
    assert mgr.active_ids() == ["chat-1"]


async def test_capacity_evicts_oldest():
    mgr = make_manager(max_sessions=2)
    await mgr.open("a")
    await mgr.open("b")
    await mgr.open("c")
    assert sorted(mgr.active_ids()) == ["b", "c"]


async def test_idle_sweep_closes_and_stops_driver():
    mgr = make_manager(ttl_seconds=60.0)
    session = await mgr.open("chat-9")
    driver = session.driver
    closed = await mgr.sweep_once(now=session.last_active + 61.0)
    assert closed == ["chat-9"]
    assert driver.stopped, "sweep must free the browser, not just forget it"
    assert mgr.get("chat-9") is None


async def test_sweep_keeps_active_sessions():
    import time
    mgr = make_manager(ttl_seconds=60.0)
    await mgr.open("busy")
    # 59s of idleness must NOT evict with a 60s TTL.
    session = mgr.get("busy")
    session.last_active = time.time() - 59.0
    closed = await mgr.sweep_once()
    assert closed == []
    assert mgr.get("busy") is not None


async def test_close_unknown_is_false():
    mgr = make_manager()
    assert await mgr.close("nope") is False


def test_sensitive_domains_need_confirmation():
    assert is_sensitive_url("https://mybank.example.com/login")
    assert is_sensitive_url("https://pay.example.com/checkout")
    assert not is_sensitive_url("https://example.com/book-tickets")
    assert not is_sensitive_url("data:text/html,<form></form>")


def test_submit_detection():
    assert is_submit_text("Book tickets")
    assert is_submit_text("Pay now")
    assert is_submit_text("", tag="input", input_type="submit")
    assert not is_submit_text("Full name", tag="input", input_type="text")
    assert not is_submit_text("Clear form")


def test_captcha_detection():
    assert detect_captcha({"title": "Just a moment...", "nodes": []}) == "just a moment"
    recaptcha_nodes = [{"label": "I'm not a robot reCAPTCHA"}]
    assert detect_captcha({"title": "x", "nodes": recaptcha_nodes}) == "recaptcha"
    assert detect_captcha({"title": "Web form", "nodes": NODES}) is None


def test_rate_budget_slides_and_caps():
    budget = RateBudget(limit=2, window_seconds=100.0)
    assert budget.check_and_spend(now=1000.0)
    assert budget.check_and_spend(now=1001.0)
    assert not budget.check_and_spend(now=1002.0)
    assert budget.check_and_spend(now=1000.0 + 101.0), "window must slide"


async def test_proposal_expiry():
    import time
    mgr = make_manager()
    session = await mgr.open("s")
    prop = session.propose("submit", "summary", {"selector": "#book"})
    assert session.take_proposal(prop["proposal_id"]) is not None
    prop2 = session.propose("submit", "summary", {"selector": "#book"})
    prop2["created_at"] = time.time() - 301.0
    assert session.take_proposal(prop2["proposal_id"]) is None
    assert session.take_proposal("wrong-id") is None


async def test_robots_parse_and_enforce():
    async def fetch(host, scheme):
        return "User-agent: *\nDisallow: /admin/\nDisallow: /pay\n"
    robots = RobotsCache(fetch=fetch)
    ok, _ = await robots.allowed("https://example.com/shop")
    assert ok
    ok, reason = await robots.allowed("https://example.com/pay/now")
    assert not ok and "robots.txt" in reason


async def test_robots_unfetchable_refuses_act():
    async def fetch(host, scheme):
        return None
    robots = RobotsCache(fetch=fetch)
    ok, reason = await robots.allowed("https://example.com/shop")
    assert not ok and "unfetchable" in reason


async def test_robots_skipped_for_data_urls():
    robots = RobotsCache(fetch=None)
    ok, reason = await robots.allowed("data:text/html,<form></form>")
    assert ok


# ---- HTTP-level contract (fake driver injected into the live app) ----

@pytest.fixture
def stubbed_app(monkeypatch):
    import app.main as service
    fake_mgr = SessionManager(driver_factory=FakeDriver,
                              robots=RobotsCache(fetch=_allow_fetch))
    monkeypatch.setattr(service, "sessions", fake_mgr)
    return service


async def _allow_fetch(host, scheme):
    return "User-agent: *\n"


def test_open_navigate_snapshot_inspect_act_flow(client, stubbed_app):
    r = client.post("/session/open", json={"session_id": "c1", "url": "data:text/html,<form></form>"})
    assert r.status_code == 200, r.text
    assert r.json()["title"] == "Demo"

    r = client.get("/session/c1/snapshot")
    assert r.status_code == 200
    assert r.json()["node_count"] == 4

    r = client.post("/session/c1/inspect", json={"target": "book tickets"})
    assert r.status_code == 200
    body = r.json()
    assert body["match_count"] == 1
    match = body["matches"][0]
    assert match["label"] == "Book tickets"
    assert match["position"] == "3 of 4 interactive elements"
    assert match["submit_action"] is True

    # Fill is routine: executes immediately with readback.
    r = client.post("/session/c1/act",
                    json={"kind": "fill", "label": "Full name", "value": "Asha"})
    assert r.status_code == 200
    assert r.json()["status"] == "completed"

    # Submit-class click is HELD: proposal, nothing clicked.
    r = client.post("/session/c1/act", json={"kind": "click", "label": "Book tickets"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs_confirmation"
    proposal_id = body["proposal"]["proposal_id"]

    # Confirm executes exactly once.
    r = client.post("/session/c1/confirm", json={"proposal_id": proposal_id})
    assert r.status_code == 200
    assert r.json()["status"] == "submitted"

    # Replaying the same proposal is a 404, not a double submit.
    r = client.post("/session/c1/confirm", json={"proposal_id": proposal_id})
    assert r.status_code == 404


def test_act_refuses_captcha(client, monkeypatch):
    import app.main as service

    def captcha_driver():
        return FakeDriver(captcha=True)

    fake_mgr = SessionManager(driver_factory=captcha_driver,
                              robots=RobotsCache(fetch=_allow_fetch))
    monkeypatch.setattr(service, "sessions", fake_mgr)
    assert client.post("/session/open",
                       json={"session_id": "cap", "url": "data:text/html,<form></form>"}).status_code == 200
    r = client.post("/session/cap/act",
                    json={"kind": "fill", "label": "Full name", "value": "x"})
    assert r.status_code == 423, r.text


def test_sensitive_url_needs_confirmation(client, stubbed_app, monkeypatch):
    import app.main as service

    def fake_guard(url):
        if url.startswith("file://"):
            raise ValueError("file refused")
        return url

    monkeypatch.setattr(service, "validate_browse_url", fake_guard)
    r = client.post("/session/open",
                    json={"session_id": "bank", "url": "https://mybank.example.com/login"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "needs_confirmation"
    assert body["proposal"]["kind"] == "navigate"

    r = client.post("/session/bank/confirm",
                    json={"proposal_id": body["proposal"]["proposal_id"]})
    assert r.status_code == 200
    assert r.json()["url"] == "https://mybank.example.com/login"


def test_unknown_session_is_404(client, stubbed_app):
    assert client.get("/session/ghost/snapshot").status_code == 404
    assert client.post("/session/ghost/act",
                       json={"kind": "click", "label": "x"}).status_code == 404


def test_bad_url_is_422(client, stubbed_app):
    r = client.post("/session/open", json={"session_id": "s", "url": "file:///etc/passwd"})
    assert r.status_code == 422
