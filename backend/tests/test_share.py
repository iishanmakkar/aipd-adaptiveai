"""Phase 4.2 share links, offline: ownership, transcript view, annotations.

Covers the MessageRole.SYSTEM regression (the enum has user/assistant only, so
every annotate silently failed to persist the owner-visible note) and the
annotation cap on the unauthenticated annotate endpoint.
"""
import time
import uuid
from types import SimpleNamespace

from conftest import FakeResult, FakeSession
from app.api.auth import get_current_user
from app.database import get_db
from app.models.message import MessageRole
import app.api.routes_share as rs


SID = "33333333-3333-3333-3333-333333333333"
OWNER_ID = "44444444-4444-4444-4444-444444444444"


def _owner():
    return SimpleNamespace(id=OWNER_ID, email="owner@example.com")


def _session_row():
    return SimpleNamespace(id=uuid.UUID(SID), user_id=OWNER_ID)


def _override(client, db):
    client.app.dependency_overrides[get_current_user] = _owner
    client.app.dependency_overrides[get_db] = lambda: db


def _release(client):
    client.app.dependency_overrides.pop(get_current_user, None)
    client.app.dependency_overrides.pop(get_db, None)


def _create(client):
    r = client.post("/api/share", json={"session_id": SID})
    assert r.status_code == 200, r.text
    return r.json()["share_token"]


def test_create_and_watch_round_trip(client):
    _override(client, FakeSession([FakeResult([_session_row()])]))
    try:
        token = _create(client)
        watch_db = FakeSession([FakeResult([
            SimpleNamespace(role=SimpleNamespace(value="user"), content="hello"),
            SimpleNamespace(role=SimpleNamespace(value="assistant"), content="hi there"),
        ])])
        client.app.dependency_overrides[get_db] = lambda: watch_db
        r = client.get(f"/api/share/{token}")
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["session_id"] == SID
        assert data["read_only"] is True
        assert [m["content"] for m in data["messages"]] == ["hello", "hi there"]
    finally:
        rs._SHARES.pop(token, None)
        _release(client)


def test_create_rejects_other_users_session(client):
    _override(client, FakeSession([FakeResult([])]))
    try:
        r = client.post("/api/share", json={"session_id": SID})
        assert r.status_code == 404
    finally:
        _release(client)


def test_create_rejects_bad_session_id(client):
    _override(client, FakeSession([]))
    try:
        r = client.post("/api/share", json={"session_id": "not-a-uuid"})
        assert r.status_code == 400
    finally:
        _release(client)


def test_annotate_persists_owner_visible_message(client):
    """Regression: role=MessageRole.SYSTEM raised AttributeError, so the note
    never reached the owner transcript despite 'annotated' being returned."""
    _override(client, FakeSession([FakeResult([_session_row()])]))
    try:
        token = _create(client)
        note_db = FakeSession([])
        client.app.dependency_overrides[get_db] = lambda: note_db
        r = client.post(f"/api/share/{token}/annotate", json={"text": "look at step 2"})
        assert r.status_code == 200, r.text
        assert r.json()["total"] == 1
        assert note_db.committed is True
        stored = [m for m in note_db.added if isinstance(m, object) and hasattr(m, "content")]
        assert len(stored) == 1
        assert stored[0].role == MessageRole.assistant
        assert stored[0].content == "Helper note: look at step 2"
        assert stored[0].meta.get("kind") == "helper_note"
        assert rs._SHARES[token]["annotations"][0]["text"] == "look at step 2"
    finally:
        rs._SHARES.pop(token, None)
        _release(client)


def test_annotate_rejects_blank_text(client):
    _override(client, FakeSession([FakeResult([_session_row()])]))
    try:
        token = _create(client)
        client.app.dependency_overrides[get_db] = lambda: FakeSession([])
        r = client.post(f"/api/share/{token}/annotate", json={"text": "   "})
        assert r.status_code == 422
    finally:
        rs._SHARES.pop(token, None)
        _release(client)


def test_annotate_enforces_share_cap(client):
    _override(client, FakeSession([FakeResult([_session_row()])]))
    try:
        token = _create(client)
        share = rs._SHARES[token]
        share["annotations"] = [{"text": "x", "ts": 0.0}] * rs.MAX_ANNOTATIONS_PER_SHARE
        rs._SHARES[token] = share
        client.app.dependency_overrides[get_db] = lambda: FakeSession([])
        r = client.post(f"/api/share/{token}/annotate", json={"text": "one more"})
        assert r.status_code == 429
    finally:
        rs._SHARES.pop(token, None)
        _release(client)


def test_unknown_and_expired_tokens_404(client):
    client.app.dependency_overrides[get_db] = lambda: FakeSession([])
    try:
        assert client.get("/api/share/nope").status_code == 404
        assert client.post("/api/share/nope/annotate", json={"text": "hi"}).status_code == 404
        rs._SHARES["stale"] = {"session_id": SID, "owner_id": OWNER_ID,
                               "created_at": time.time() - rs.SHARE_TTL_SECONDS - 1,
                               "annotations": []}
        assert client.get("/api/share/stale").status_code == 404
        assert "stale" not in rs._SHARES  # expiry is enforced, not just reported
    finally:
        rs._SHARES.pop("stale", None)
        _release(client)
