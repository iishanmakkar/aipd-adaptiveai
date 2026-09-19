"""Contract + wiring tests for POST /api/behavior-event (B2).

The endpoint persists per-session signal counts behind the same ownership
check as /api/query: unknown sessions 404, bad UUIDs 400, no DB 503s.
"""
import pytest
from types import SimpleNamespace

from conftest import FakeResult, FakeSession
from app.database import get_db


def _user(monkeypatch_client=None):
    class U:
        id = "11111111-1111-1111-1111-111111111111"
        email = "offline@example.com"
    return U()


@pytest.fixture
def authed(client, monkeypatch):
    from app.api.auth import get_current_user_optional
    import app.api.routes_behavior as rb
    u = _user()
    client.app.dependency_overrides[get_current_user_optional] = lambda: u
    monkeypatch.setattr(rb, "is_db_available", lambda: True)
    yield u
    client.app.dependency_overrides.pop(get_current_user_optional, None)


SID = "22222222-2222-2222-2222-222222222222"


def test_behavior_requires_db(client):
    r = client.post("/api/behavior-event",
                    json={"session_id": SID, "event_type": "skip"})
    assert r.status_code == 503


def test_behavior_rejects_bad_uuid(client, authed):
    # get_db itself 503s without a DB, so override it: the 400 must come from
    # input validation, not from the database layer.
    async def fake_db():
        return FakeSession([])
    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/behavior-event",
                        json={"session_id": "not-a-uuid", "event_type": "skip"})
        assert r.status_code == 400
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_behavior_rejects_bad_event(client, authed):
    async def fake_db():
        return FakeSession([FakeResult([SimpleNamespace(id=SID)])])
    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/behavior-event",
                        json={"session_id": SID, "event_type": "rewind"})
        assert r.status_code == 422
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_behavior_404_for_unknown_session(client, authed):
    async def fake_db():
        return FakeSession([FakeResult([])])  # no session row
    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/behavior-event",
                        json={"session_id": SID, "event_type": "skip"})
        assert r.status_code == 404
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_behavior_accepts_and_counts(client, authed):
    async def fake_db():
        # 1st execute: session ownership; 2nd: existing signals (none)
        return FakeSession([FakeResult([SimpleNamespace(id=SID)]), FakeResult([])])
    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/behavior-event",
                        json={"session_id": SID, "event_type": "replay"})
        assert r.status_code == 200, r.text
        assert r.json() == {"status": "accepted", "replay_count": 1, "skip_count": 0}
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_behavior_increments_existing(client, authed):
    existing = SimpleNamespace(session_id=SID, replay_count=2, skip_count=1,
                               listen_count=0, listen_seconds=0.0)

    async def fake_db():
        return FakeSession([FakeResult([SimpleNamespace(id=SID)]),
                            FakeResult([existing])])
    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.post("/api/behavior-event",
                        json={"session_id": SID, "event_type": "skip"})
        assert r.status_code == 200, r.text
        assert r.json()["skip_count"] == 2
        assert r.json()["replay_count"] == 2
    finally:
        client.app.dependency_overrides.pop(get_db, None)
