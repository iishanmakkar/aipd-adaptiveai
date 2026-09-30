"""Monitor delivery guarantees, offline: dedupe, voice/button state parity."""
import uuid
from types import SimpleNamespace

from conftest import FakeResult, FakeSession
from app.api.auth import get_current_user_optional
from app.database import get_db
import app.api.routes_monitor as rm


SID = "55555555-5555-5555-5555-555555555555"
USER_ID = "66666666-6666-6666-6666-666666666666"

EVENT = {"id": 1, "ts": 1700000000.0, "trigger": "change",
         "raw_description": "an error banner appeared"}


def _session_ns():
    return SimpleNamespace(id=uuid.UUID(SID), user_id=USER_ID)


def _results(dedupe_rows=None):
    return FakeSession([
        FakeResult([_session_ns()]),  # _own_session
        FakeResult([]),  # prefs
        FakeResult([]),  # behavior signals
        FakeResult(list(dedupe_rows or [])),  # stored narration metas
    ])


def _authed(client, monkeypatch, db, events):
    client.app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(
        id=USER_ID, email="watcher@example.com")
    client.app.dependency_overrides[get_db] = lambda: db
    monkeypatch.setattr(rm, "is_db_available", lambda: True)

    async def fake_pull(session_id, cursor, request_id):
        return {"active": True, "events": [dict(e) for e in events], "stats": {}}

    async def fake_adjust(**kwargs):
        return kwargs["raw_answer"]

    monkeypatch.setattr(rm, "browser_monitor_narrations", fake_pull)
    monkeypatch.setattr(rm, "adjust_response", fake_adjust)


def _release(client):
    client.app.dependency_overrides.pop(get_current_user_optional, None)
    client.app.dependency_overrides.pop(get_db, None)
    rm._monitor_state.pop(SID, None)


def test_first_delivery_persists_and_advances_cursor(client, monkeypatch):
    db = _results()
    _authed(client, monkeypatch, db, [EVENT])
    try:
        r = client.get(f"/api/monitor/events?session_id={SID}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["narrations"]) == 1
        assert data["cursor"] == 1
        assert db.committed is True
        stored = [m for m in db.added if hasattr(m, "meta")]
        assert len(stored) == 1
        assert stored[0].meta["monitor_event_id"] == 1
    finally:
        _release(client)


def test_redelivered_narration_is_not_persisted_twice(client, monkeypatch):
    """Cursor TTL expiry (or a restart without Redis) resets `since` to 0 and
    the browser re-delivers: already-stored ids advance the cursor only."""
    db1 = _results()
    _authed(client, monkeypatch, db1, [EVENT])
    try:
        assert client.get(f"/api/monitor/events?session_id={SID}").status_code == 200
        assert len([m for m in db1.added if hasattr(m, "meta")]) == 1

        # Simulate cursor loss: delivery restarts from 0 with the same event.
        rm._monitor_state[SID] = {"since": 0, "active": True}
        db2 = _results(dedupe_rows=[({"kind": "narration", "monitor_event_id": 1},)])
        client.app.dependency_overrides[get_db] = lambda: db2
        r = client.get(f"/api/monitor/events?session_id={SID}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["narrations"] == []
        assert data["cursor"] == 1
        assert [m for m in db2.added if hasattr(m, "meta")] == []
        assert db2.committed is False
    finally:
        _release(client)


async def test_voice_stop_clears_monitor_state(monkeypatch):
    """The chat door must leave the same server-side flag as the button door."""
    import app.api.routes_query as rq
    import app.services.clients as clients_mod

    async def fake_stop(session_id, request_id=None):
        return {"status": "stopped", "stats": {"counters": {}}}

    async def fake_finish(*args, **kwargs):
        return SimpleNamespace(answer="stopped")

    monkeypatch.setattr(clients_mod, "browser_monitor_stop", fake_stop)
    monkeypatch.setattr(rq, "_finish_turn", fake_finish)
    rm._monitor_state["chat-v"] = {"since": 3, "active": True}
    try:
        await rq._monitor_voice_turn(
            FakeSession(), SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id="u"), uuid.uuid4(), "chat-v", "stop", "req", 0)
        assert rm._monitor_state["chat-v"] == {"since": 3, "active": False}
    finally:
        rm._monitor_state.pop("chat-v", None)


async def test_voice_start_sets_monitor_state(monkeypatch):
    import app.api.routes_query as rq
    import app.services.clients as clients_mod

    async def fake_start(session_id, requested_by="voice", request_id=None):
        return {"status": "started", "stats": {}}

    async def fake_finish(*args, **kwargs):
        return SimpleNamespace(answer="watching")

    monkeypatch.setattr(clients_mod, "browser_monitor_start", fake_start)
    monkeypatch.setattr(rq, "_finish_turn", fake_finish)
    rm._monitor_state.pop("chat-v", None)
    try:
        await rq._monitor_voice_turn(
            FakeSession(), SimpleNamespace(id=uuid.uuid4()),
            SimpleNamespace(id="u"), uuid.uuid4(), "chat-v", "start", "req", 0)
        assert rm._monitor_state["chat-v"]["active"] is True
    finally:
        rm._monitor_state.pop("chat-v", None)


def test_query_rejects_oversize_input_honestly(client, monkeypatch):
    """Past the data: URL shrink, >2000 chars would 400 in the intent engine
    and surface as 502 - the trust boundary reports 400 itself instead."""
    import app.api.routes_query as rq

    other_sid = str(uuid.uuid4())
    client.app.dependency_overrides[get_current_user_optional] = lambda: SimpleNamespace(
        id="u", email="u@example.com")
    client.app.dependency_overrides[get_db] = lambda: FakeSession([
        FakeResult([SimpleNamespace(id=uuid.UUID(other_sid), user_id="u")]),
        FakeResult([]),
    ])
    monkeypatch.setattr(rq, "is_db_available", lambda: True)

    async def must_not_run(*args, **kwargs):
        raise AssertionError("intent must not be called for oversize input")

    monkeypatch.setattr(rq, "classify_intent", must_not_run)
    try:
        r = client.post("/api/query", json={"session_id": other_sid,
                                            "input_text": "x" * 2001})
        assert r.status_code == 400, r.text
    finally:
        _release(client)


def test_query_rejects_empty_input(client):
    async def fake_db():
        return FakeSession([])

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/query", json={"session_id": SID, "input_text": ""})
        assert r.status_code == 422
    finally:
        client.app.dependency_overrides.pop(get_db, None)
