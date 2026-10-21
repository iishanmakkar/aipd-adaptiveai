"""The robots field in the session log must say what was actually checked.

`_navigate_session` initialised `robots_ok, robots_reason = True, "no host to
check"` for non-http targets. `True` plus a reason that reads like a verdict made
every `data:` and `file:` navigation look robots-cleared in the log, when nothing
had been consulted at all. Non-applicable is a different fact from allowed.
"""
import pytest

import app.main as main


class UnlimitedBudget:
    def check_and_spend(self):
        return True


class FakeDriver:
    async def navigate(self, url):
        return {"url": url, "http_status": 200, "title": "Fixture"}


class FakeSession:
    def __init__(self):
        self.driver = FakeDriver()
        self.nav_budget = UnlimitedBudget()
        self.url = ""
        self.title = ""
        self.logs = []
        self.touched = 0

    def touch(self):
        self.touched += 1

    def log(self, action, **kwargs):
        self.logs.append({"action": action, **kwargs})


class RecordingRobots:
    def __init__(self):
        self.queries = []

    async def allowed(self, url):
        self.queries.append(url)
        return (False, "disallowed by robots.txt")


@pytest.fixture
def isolated_robots(monkeypatch):
    rec = RecordingRobots()
    monkeypatch.setattr(main.sessions, "robots", rec)
    return rec


@pytest.mark.asyncio
async def test_data_url_is_logged_as_not_applicable_not_allowed(isolated_robots):
    session = FakeSession()
    await main._navigate_session(session, "data:text/html,<title>Fixture</title>", None)

    entry = session.logs[-1]
    assert entry["robots_reason"].startswith("not_applicable"), entry["robots_reason"]
    assert "no host to check" not in entry["robots_reason"]
    # Nothing was fetched, so nothing can claim clearance.
    assert isolated_robots.queries == []


@pytest.mark.asyncio
async def test_http_url_still_consults_robots_and_records_the_verdict(isolated_robots):
    session = FakeSession()
    await main._navigate_session(session, "https://example.com/", None)

    assert isolated_robots.queries == ["https://example.com/"]
    entry = session.logs[-1]
    assert entry["robots_ok"] is False
    assert entry["robots_reason"] == "disallowed by robots.txt"
    assert "not_applicable" not in entry["robots_reason"]


@pytest.mark.asyncio
async def test_budget_exhaustion_is_a_429_not_a_silent_no_op():
    from fastapi import HTTPException

    class SpentBudget:
        def check_and_spend(self):
            return False

    session = FakeSession()
    session.nav_budget = SpentBudget()
    with pytest.raises(HTTPException) as exc:
        await main._navigate_session(session, "data:text/html,x", None)
    assert exc.value.status_code == 429
    assert session.logs == [], "a refused navigation must not be logged as a navigate"
