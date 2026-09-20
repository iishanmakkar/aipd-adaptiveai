"""Round 9 monitor gating, offline: no Chromium, no network, no NIM calls.

The driver and the NIM describe call are injected fakes (test seams only -
every live claim in the Round 9 log comes from the real stack). What is under
test is the correctness core: a NIM call happens ONLY when a settled,
meaningful change passes the interruption and rate gates.
"""
import asyncio
import time

import pytest

from app.services.monitor import PageMonitor


class FakeDriver:
    """Returns scripted {mutations, text} signals, like page.evaluate would."""

    def __init__(self):
        self.signal = {"mutations": 0, "text": "static page"}
        self.screenshots = 0

    async def monitor_signal(self):
        return dict(self.signal)


def make_monitor(**overrides):
    driver = FakeDriver()
    calls = []

    async def fake_describe(text, prev):
        calls.append({"text": text, "prev": prev, "ts": time.time()})
        return f"change noted: {text}"

    cfg = dict(poll_seconds=0.0, stable_seconds=0.0, min_call_seconds=0.0,
               quiet_seconds=0.0)
    cfg.update(overrides)
    monitor = PageMonitor("s1", driver, describe_fn=fake_describe, **cfg)
    return monitor, driver, calls


async def settle(monitor, n=2):
    """Two polls: one to see the change, one to let it settle."""
    for _ in range(n):
        await monitor.poll_once()


LONG = "booking form with email field seats dropdown and submit button x"  # 66 chars


def test_no_change_means_no_nim_call():
    monitor, driver, calls = make_monitor()
    for _ in range(10):
        asyncio.run(monitor.poll_once())
    assert monitor.counters["polls"] == 10
    assert monitor.counters["baseline_polls"] == 1
    assert monitor.counters["polls_idle"] == 9
    assert calls == []
    assert monitor.counters["nim_calls"] == 0


def test_text_change_settles_into_one_call():
    monitor, driver, calls = make_monitor()
    asyncio.run(monitor.poll_once())            # baseline
    driver.signal["text"] = "email error: required"
    asyncio.run(settle(monitor))
    assert len(calls) == 1
    assert monitor.counters["narrations"] == 1
    assert monitor.counters["changes_detected"] == 1


def test_typing_flicker_coalesces_into_one_call():
    """A burst of intermediate states (keystrokes) narrates once, at the end."""
    monitor, driver, calls = make_monitor()
    asyncio.run(monitor.poll_once())
    for chunk in ("a", "as", "ash", "asha", "asha sharma"):
        driver.signal["text"] = f"form {chunk}"
        asyncio.run(monitor.poll_once())        # change seen, unstable
    driver.signal["text"] = "form asha sharma"
    asyncio.run(settle(monitor))
    assert len(calls) == 1
    assert calls[0]["text"] == "form asha sharma"


def test_minor_change_is_ignored():
    monitor, driver, calls = make_monitor()
    asyncio.run(monitor.poll_once())
    base = LONG * 2  # 132 identical chars, so a 1-char tick stays >0.98 ratio
    monitor.described_text = base
    monitor.stable_text = base
    monitor.last_text = base
    driver.signal["text"] = base[:-1] + "9"
    asyncio.run(settle(monitor))
    assert calls == []
    assert monitor.counters["minor_ignored"] == 1
    assert monitor.counters["nim_calls"] == 0


def test_rate_ceiling_blocks_and_then_fires_deferred():
    monitor, driver, calls = make_monitor(min_call_seconds=60.0)
    asyncio.run(monitor.poll_once())
    driver.signal["text"] = "error one appeared"
    asyncio.run(settle(monitor))
    assert len(calls) == 1                       # first change goes through
    now = time.time()
    monitor.last_call_ts = now                   # pretend the ceiling is active
    driver.signal["text"] = "error two appeared"
    asyncio.run(settle(monitor))
    assert len(calls) == 1                       # blocked
    assert monitor.counters["rate_blocked"] == 1
    # Ceiling expires: the deferred (newest) state is described.
    monitor.last_call_ts = now - 61.0
    event = asyncio.run(monitor.poll_once())
    assert event is not None and "error two" in event["raw_description"]
    assert len(calls) == 2
    assert calls[1]["text"] == "error two appeared"


def test_interrupt_holds_narration_then_releases():
    monitor, driver, calls = make_monitor(stable_seconds=0.0, quiet_seconds=15.0)
    asyncio.run(monitor.poll_once())
    monitor.interrupt()                          # user started talking
    driver.signal["text"] = "error appeared under email"
    asyncio.run(settle(monitor))
    assert calls == []                           # held while quiet window runs
    assert monitor.counters["deferred_by_quiet"] == 1
    monitor.quiet_until = time.time() - 1        # quiet window over
    event = asyncio.run(monitor.poll_once())
    assert event is not None
    assert len(calls) == 1                       # delivered after, not over, the user


def test_interrupt_defers_only_newest_state():
    monitor, driver, calls = make_monitor(stable_seconds=0.0, quiet_seconds=15.0)
    asyncio.run(monitor.poll_once())
    monitor.interrupt()
    driver.signal["text"] = "first error"
    asyncio.run(settle(monitor))
    driver.signal["text"] = "second error replaced first"
    asyncio.run(settle(monitor))
    monitor.quiet_until = time.time() - 1
    asyncio.run(monitor.poll_once())
    assert len(calls) == 1
    assert calls[0]["text"] == "second error replaced first"


def test_continuously_changing_page_is_capped_by_ceiling():
    """A page that never settles (live dashboard) still gets evaluated after
    max_pending_seconds, but the hard ceiling bounds the call rate: with a
    60s ceiling, 60s of continuous churn yields ONE call, and the deferred
    change fires when the ceiling expires."""
    monitor, driver, calls = make_monitor(stable_seconds=100.0,
                                          max_pending_seconds=0.0,
                                          min_call_seconds=60.0)
    asyncio.run(monitor.poll_once())  # baseline
    for i in range(20):               # 20 forced evaluations in 60s of churn
        driver.signal["text"] = (
            f"train {i} to Chennai delayed {i} minutes, platform {i % 7 + 1}")
        asyncio.run(monitor.poll_once())
    assert len(calls) == 1            # the ceiling held: 1 call, not 20
    assert monitor.counters["forced_evaluations"] == 10
    assert monitor.counters["rate_blocked"] == 9
    # Ceiling expires: the newest deferred state is described once.
    monitor.last_call_ts = time.time() - 61.0
    asyncio.run(monitor.poll_once())
    assert len(calls) == 2
    assert calls[1]["text"] == "train 19 to Chennai delayed 19 minutes, platform 6"


def test_stop_disables_and_discards_events():
    monitor, driver, calls = make_monitor()
    asyncio.run(monitor.poll_once())
    driver.signal["text"] = "error appeared"
    asyncio.run(settle(monitor))
    assert monitor.counters["narrations"] == 1
    monitor.stop(reason="test")
    assert monitor.poll_once is not None
    asyncio.run(monitor.poll_once())
    assert monitor.counters["polls"] == 3        # poll_once no-ops when stopped
    assert list(monitor.events) == []            # unsent descriptions discarded


def test_max_duration_auto_stops():
    monitor, driver, calls = make_monitor(max_duration_seconds=100.0)
    monitor.started_at = time.time() - 101.0
    event = asyncio.run(monitor.poll_once())
    assert event is None
    assert not monitor.enabled


def test_failed_describe_does_not_lose_the_change():
    monitor, driver, calls = make_monitor()
    async def failing(text, prev):
        raise RuntimeError("nim down")
    monitor.describe_fn = failing
    asyncio.run(monitor.poll_once())
    driver.signal["text"] = "error appeared"
    asyncio.run(settle(monitor))
    assert monitor.counters["errors"] == 1
    assert monitor.counters["narrations"] == 0
    # Recovery: next settled change goes out normally.
    monitor.describe_fn = None  # falls back to real NIM path... not in tests
    # Instead re-inject a working fake.
    async def working(text, prev):
        calls.append(text)
        return "recovered description"
    monitor.describe_fn = working
    driver.signal["text"] = "error appeared and page recovered"
    asyncio.run(settle(monitor))
    assert monitor.counters["narrations"] == 1


def test_delivery_cursor_roundtrip():
    monitor, driver, calls = make_monitor()
    asyncio.run(monitor.poll_once())
    driver.signal["text"] = "error appeared"
    asyncio.run(settle(monitor))
    events = monitor.narrations_since(0)
    assert len(events) == 1
    monitor.mark_delivered(events[-1]["id"])
    assert monitor.stats()["undelivered"] == 0
    assert monitor.narrations_since(events[-1]["id"]) == []


# ---- endpoint-level consent + stop flow (no Chromium: FakeDriver injected).

@pytest.fixture
def monitor_client():
    from fastapi.testclient import TestClient
    import app.main as service
    from app.services.sessions import LiveSession
    with TestClient(service.app, raise_server_exceptions=False) as c:
        driver = FakeDriver()
        session = LiveSession("ep1", driver)
        session.url = "data:text/html,x"
        service.sessions._sessions["ep1"] = session
        yield c, session
        service.sessions._sessions.pop("ep1", None)


def test_start_requires_existing_session(client):
    r = client.post("/session/nope/monitor/start", json={"requested_by": "voice"})
    assert r.status_code == 404


def test_start_needs_explicit_call_and_page(monitor_client):
    c, session = monitor_client
    # Nothing started by default: opening a session never creates a monitor.
    assert session.monitor is None
    r = c.post("/session/ep1/monitor/start", json={"requested_by": "voice"})
    assert r.status_code == 200
    assert r.json()["status"] == "started"
    assert r.json()["requested_by"] == "voice"
    assert session.monitor is not None and session.monitor.enabled


def test_stop_then_status_reflects_it(monitor_client):
    c, session = monitor_client
    c.post("/session/ep1/monitor/start", json={"requested_by": "button"})
    r = c.post("/session/ep1/monitor/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    assert not session.monitor.enabled
    status = c.get("/session/ep1/monitor/status").json()
    assert status["active"] is False
    # Stopping again is honest: monitoring is not active.
    r2 = c.post("/session/ep1/monitor/stop")
    assert r2.status_code == 409


def test_narrations_pull_and_stats(monitor_client):
    c, session = monitor_client
    c.post("/session/ep1/monitor/start", json={"requested_by": "button"})
    r = c.get("/session/ep1/monitor/narrations")
    assert r.status_code == 200
    body = r.json()
    assert body["active"] is True
    assert body["events"] == []
    assert body["stats"]["counters"]["polls"] >= 0


def test_session_close_stops_monitor(monitor_client):
    c, session = monitor_client
    c.post("/session/ep1/monitor/start", json={"requested_by": "button"})
    r = c.post("/session/ep1/close")
    assert r.status_code == 200
    assert session.monitor.enabled is False
