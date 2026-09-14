"""Contract tests for the preference + session-list endpoints.

The preference endpoint completes the adaptive-policy loop (policy_engine reads
verbosity from the DB, this is the only thing that writes it), so its contract
is locked here without a database; the real-Postgres flow is covered by the
`live` suite.
"""
import pytest
from types import SimpleNamespace

from conftest import FakeResult, FakeSession
from app.database import get_db
from app.models.preference import VerbosityLevel


@pytest.fixture
def fake_user(client, monkeypatch):
    from app.api.auth import get_current_user_optional
    import app.api.routes_preferences as rp
    import app.api.routes_session as rs

    class U:
        id = "11111111-1111-1111-1111-111111111111"
        email = "offline@example.com"

    client.app.dependency_overrides[get_current_user_optional] = lambda: U()
    # The routes gate on the global DB flag; point it at the fake session too.
    monkeypatch.setattr(rp, "is_db_available", lambda: True)
    monkeypatch.setattr(rs, "is_db_available", lambda: True)
    yield U()
    client.app.dependency_overrides.pop(get_current_user_optional, None)


def test_preferences_require_db(client):
    assert client.get("/api/preferences").status_code == 503
    r = client.put("/api/preferences", json={"verbosity_level": "concise", "voice_speed": 1.0})
    assert r.status_code == 503


def test_put_preferences_round_trip(client, fake_user):
    async def fake_db():
        return FakeSession([FakeResult([])])  # no existing preference row -> created

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.put("/api/preferences", json={"verbosity_level": "concise", "voice_speed": 1.4})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["verbosity_level"] == "concise"
        assert body["voice_speed"] == 1.4
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_put_preferences_rejects_bad_values(client, fake_user):
    client.app.dependency_overrides[get_db] = fake_db_override
    try:
        r = client.put("/api/preferences", json={"verbosity_level": "shouting", "voice_speed": 1.0})
        assert r.status_code == 422
        r = client.put("/api/preferences", json={"verbosity_level": "concise", "voice_speed": 9.9})
        assert r.status_code == 422
    finally:
        client.app.dependency_overrides.pop(get_db, None)


async def fake_db_override():
    return FakeSession([FakeResult([])])


def test_get_sessions_returns_rows_with_counts(client, fake_user):
    rows = [
        SimpleNamespace(id="aaaaaaaa-1111-1111-1111-111111111111",
                        created_at="2026-09-13T01:00:00Z", message_count=4),
        SimpleNamespace(id="aaaaaaaa-2222-2222-2222-222222222222",
                        created_at="2026-09-12T01:00:00Z", message_count=0),
    ]

    async def fake_db():
        return FakeSession([FakeResult(rows)])

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.get("/api/sessions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 2
        assert body["sessions"][0]["message_count"] == 4
        # newest first
        assert body["sessions"][0]["created_at"] > body["sessions"][1]["created_at"]
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_get_sessions_empty_for_new_user(client, fake_user):
    async def fake_db():
        return FakeSession([FakeResult([])])

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.get("/api/sessions")
        assert r.status_code == 200
        assert r.json() == {"sessions": [], "total": 0}
    finally:
        client.app.dependency_overrides.pop(get_db, None)


def test_query_response_includes_sources():
    """The shared contract grew `sources_used`; it must default so older
    callers keep working."""
    from app.schemas.query import QueryResponse
    minimal = QueryResponse(response_text="a", agent_used="form_agent", confidence=0.9)
    assert minimal.sources_used == []
