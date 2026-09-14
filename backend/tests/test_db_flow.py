"""Real Postgres end-to-end flow.

Deselected by default; runs when TEST_DATABASE_URL points at a live Postgres
(CI provides one as a service container). This is the part that previously
could not be verified at all: the SQLAlchemy models, ownership checks and
message persistence had never executed against a real database.

Intent/agent calls are stubbed, so this costs no NIM quota - it is purely
proving the DB layer and the orchestration contract.
"""
import secrets
import uuid

import pytest

pytestmark = pytest.mark.live

from app.database import is_db_available  # noqa: E402
from app.services.clients import AgentResponse, IntentResponse  # noqa: E402

if not is_db_available():
    pytest.skip("TEST_DATABASE_URL not set - DB-backed tests need a real Postgres",
                allow_module_level=True)


@pytest.fixture(scope="module")
def client():
    """Module-scoped: app.database builds one engine at import time, so every DB
    test must share a single event loop. The app's own lifespan calls init_db()
    inside that loop - running it separately with asyncio.run() would pool
    connections against a loop that is then closed.
    """
    from fastapi.testclient import TestClient
    from app.main import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(autouse=True)
def _no_network(client, monkeypatch):
    """Stub the two downstream services and the policy rewrite."""
    import app.api.routes_query as rq
    import app.services.policy_engine as pe

    async def fake_intent(**kwargs):
        return IntentResponse("form_help", "form_agent", "Permanent Address field",
                              "stubbed for DB test")

    async def fake_agent(**kwargs):
        return AgentResponse("Enter your address as printed on your ID.",
                             ["form_permanent_address"], "highlight_field")

    async def no_rewrite(text, instruction):
        return text

    monkeypatch.setattr(rq, "classify_intent", fake_intent)
    monkeypatch.setattr(rq, "get_agent_response", fake_agent)
    monkeypatch.setattr(pe, "llm_rewrite", no_rewrite)


def _register(client, email=None, password=None):
    # Generated per call: these tests run against a throwaway DB, and a literal
    # password in source is what a secret scanner (rightly) flags.
    password = password or secrets.token_urlsafe(12)
    email = email or f"u{uuid.uuid4().hex[:12]}@example.com"
    r = client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return email, password, r.json()["access_token"]


def test_database_is_really_available(client):
    assert is_db_available() is True


def test_register_then_login_then_me(client):
    email, password, token = _register(client)

    login = client.post("/auth/login", json={"email": email, "password": password})
    assert login.status_code == 200
    assert login.json()["token_type"] == "bearer"

    me = client.get("/auth/me", headers={"Authorization": f"Bearer {login.json()['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == email


def test_duplicate_registration_rejected(client):
    email, _password, _token = _register(client)
    r = client.post("/auth/register", json={"email": email, "password": secrets.token_urlsafe(12)})
    assert r.status_code == 400


def test_wrong_password_is_401(client):
    email, _password, _token = _register(client)
    r = client.post("/auth/login", json={"email": email, "password": secrets.token_urlsafe(12)})
    assert r.status_code == 401


def test_session_is_persisted_with_a_real_row(client):
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}

    created = client.post("/api/session", headers=hdr)
    assert created.status_code == 201
    session_id = created.json()["session_id"]
    assert uuid.UUID(session_id)  # a genuine UUID from the DB, not a placeholder

    fetched = client.get(f"/api/history/{session_id}", headers=hdr)
    assert fetched.status_code == 200
    assert fetched.json()["total"] == 0


def test_query_persists_both_messages(client):
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/api/session", headers=hdr).json()["session_id"]

    r = client.post("/api/query", headers=hdr, json={
        "session_id": session_id, "input_text": "What is the permanent address field?",
        "input_source": "text", "screen_context": "admission form"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["agent_used"] == "form_agent"
    assert body["response_text"] == "Enter your address as printed on your ID."

    history = client.get(f"/api/history/{session_id}", headers=hdr).json()
    assert history["total"] == 2
    roles = [m["role"] for m in history["messages"]]
    assert roles == ["user", "assistant"]
    assistant = history["messages"][1]
    assert assistant["agent_used"] == "form_agent"
    assert assistant["content"] == "Enter your address as printed on your ID."


def test_history_pagination(client):
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/api/session", headers=hdr).json()["session_id"]

    for i in range(3):
        client.post("/api/query", headers=hdr, json={
            "session_id": session_id, "input_text": f"question {i} about the field",
            "input_source": "text", "screen_context": ""})

    page = client.get(f"/api/history/{session_id}?page=1&page_size=2", headers=hdr).json()
    assert page["total"] == 6
    assert len(page["messages"]) == 2
    assert page["page_size"] == 2


def test_session_ownership_is_enforced(client):
    """User B must not be able to read user A's session."""
    _e, _p, token_a = _register(client)
    _e, _p, token_b = _register(client)

    session_id = client.post("/api/session",
                             headers={"Authorization": f"Bearer {token_a}"}).json()["session_id"]

    r = client.get(f"/api/history/{session_id}", headers={"Authorization": f"Bearer {token_b}"})
    assert r.status_code == 404


def test_query_on_unknown_session_is_404(client):
    _email, _password, token = _register(client)
    r = client.post("/api/query", headers={"Authorization": f"Bearer {token}"}, json={
        "session_id": str(uuid.uuid4()), "input_text": "hi",
        "input_source": "text", "screen_context": ""})
    assert r.status_code == 404


def test_malformed_session_id_is_handled(client):
    _email, _password, token = _register(client)
    r = client.post("/api/query", headers={"Authorization": f"Bearer {token}"}, json={
        "session_id": "not-a-uuid", "input_text": "hi",
        "input_source": "text", "screen_context": ""})
    assert r.status_code == 400


def test_query_response_carries_rag_sources(client):
    """The answer must name the knowledge-base docs that grounded it."""
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/api/session", headers=hdr).json()["session_id"]

    r = client.post("/api/query", headers=hdr, json={
        "session_id": session_id, "input_text": "What is the permanent address field?",
        "input_source": "text", "screen_context": ""})
    assert r.status_code == 200
    assert r.json()["sources_used"] == ["form_permanent_address"]


def test_preferences_round_trip_persists(client):
    """The policy engine reads verbosity from this row - it must actually persist."""
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}

    put = client.put("/api/preferences", headers=hdr,
                     json={"verbosity_level": "detailed", "voice_speed": 1.3})
    assert put.status_code == 200, put.text
    assert put.json() == {"verbosity_level": "detailed", "voice_speed": 1.3}

    got = client.get("/api/preferences", headers=hdr)
    assert got.status_code == 200
    assert got.json()["verbosity_level"] == "detailed"

    # a second PUT updates the same row rather than failing on the unique user
    put2 = client.put("/api/preferences", headers=hdr,
                      json={"verbosity_level": "concise", "voice_speed": 1.0})
    assert put2.json()["verbosity_level"] == "concise"


def test_session_list_shows_sessions_with_counts(client):
    _email, _password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/api/session", headers=hdr).json()["session_id"]
    client.post("/api/query", headers=hdr, json={
        "session_id": session_id, "input_text": "q about the field",
        "input_source": "text", "screen_context": ""})

    r = client.get("/api/sessions", headers=hdr)
    assert r.status_code == 200
    sessions = r.json()["sessions"]
    assert r.json()["total"] >= 1
    mine = next(s for s in sessions if s["session_id"] == session_id)
    assert mine["message_count"] == 2  # user + assistant


def test_session_list_is_scoped_to_owner(client):
    _e, _p, token_a = _register(client)
    _e, _p, token_b = _register(client)
    hdr_a = {"Authorization": f"Bearer {token_a}"}
    hdr_b = {"Authorization": f"Bearer {token_b}"}

    session_id = client.post("/api/session", headers=hdr_a).json()["session_id"]

    ids_b = [s["session_id"] for s in client.get("/api/sessions", headers=hdr_b).json()["sessions"]]
    assert session_id not in ids_b

    ids_a = [s["session_id"] for s in client.get("/api/sessions", headers=hdr_a).json()["sessions"]]
    assert session_id in ids_a


def test_account_delete_removes_every_row(client):
    """Delete must be real: after 204, the API must know nothing about the user.
    (Row-level absence in Postgres is verified separately with psql in the
    deployment checks.)"""
    email, password, token = _register(client)
    hdr = {"Authorization": f"Bearer {token}"}
    session_id = client.post("/api/session", headers=hdr).json()["session_id"]
    client.post("/api/query", headers=hdr, json={
        "session_id": session_id, "input_text": "q about the field",
        "input_source": "text", "screen_context": ""})

    # data exists before deletion
    assert client.get(f"/api/history/{session_id}", headers=hdr).json()["total"] == 2

    r = client.request("DELETE", "/auth/account", headers=hdr)
    assert r.status_code == 204

    # the token is dead, the session is gone, the user is unknown
    assert client.get("/auth/me", headers=hdr).status_code == 401
    assert client.get(f"/api/history/{session_id}", headers=hdr).status_code == 404

    # logging in again must fail: the credential row is deleted
    assert client.post("/auth/login", json={"email": email, "password": password}).status_code == 401
