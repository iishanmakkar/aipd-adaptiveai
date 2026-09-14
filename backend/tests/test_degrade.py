"""Degrade paths: when a dependency is missing the API must fail honestly.

For an accessibility product a silent 200 with junk is worse than a clear 503,
and a raw exception (500) tells the operator nothing. These are regressions for
the "DB down returned 500" and "no key returned 500" failures.
"""
import pytest

from app.database import is_db_available


def test_offline_suite_runs_in_demo_mode():
    """Guard: conftest must have cleared the DB URL or the tests below are moot."""
    assert is_db_available() is False


@pytest.mark.parametrize("path,body", [
    ("/api/session", None),
    ("/api/query", {"session_id": "s", "input_text": "hi", "input_source": "text", "screen_context": ""}),
])
def test_db_routes_return_503_not_500_when_db_unconfigured(client, path, body):
    r = client.post(path, json=body) if body else client.post(path)
    assert r.status_code == 503, f"{path} returned {r.status_code}: {r.text[:200]}"
    assert "Database not available" in r.json()["detail"]


def test_history_returns_503_when_db_unconfigured(client):
    assert client.get("/api/history/whatever").status_code == 503


def test_health_is_available_without_db(client):
    """Liveness must not depend on optional services."""
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "adaptiveai-backend"


def test_register_and_login_are_503_without_db(client):
    assert client.post("/auth/register", json={"email": "a@b.co", "password": "secret123"}).status_code == 503
    assert client.post("/auth/login", json={"email": "a@b.co", "password": "secret123"}).status_code == 503


def test_me_without_token_is_401(client):
    """Auth must reject a missing token. Without a DB the dependency chain
    short-circuits to 503, so override get_db to reach the credential check."""
    from conftest import FakeSession
    from app.database import get_db

    async def fake_db():
        return FakeSession()

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.get("/auth/me")
        assert r.status_code == 401
        assert r.headers.get("www-authenticate") == "Bearer"
    finally:
        client.app.dependency_overrides.clear()


def test_me_with_garbage_token_is_401(client):
    from conftest import FakeSession
    from app.database import get_db

    async def fake_db():
        return FakeSession()

    client.app.dependency_overrides[get_db] = fake_db
    try:
        r = client.get("/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
        assert r.status_code == 401
    finally:
        client.app.dependency_overrides.clear()


def test_query_demo_maps_upstream_failure_to_502(client, monkeypatch):
    """query-demo needs no DB, so it isolates the service-call failure path:
    an unreachable intent engine must surface as 502, never a fake answer."""
    import app.api.routes_query as rq

    async def boom(**kwargs):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(rq, "classify_intent", boom)
    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "hi", "input_source": "text", "screen_context": ""})
    assert r.status_code == 502
    assert "Intent service error" in r.json()["detail"]


def test_query_demo_maps_agent_failure_to_502(client, monkeypatch):
    import app.api.routes_query as rq
    from app.services.clients import IntentResponse

    async def intent_ok(**kwargs):
        return IntentResponse("form_help", "form_agent", "field", "stub")

    async def agent_boom(**kwargs):
        raise RuntimeError("agent down")

    monkeypatch.setattr(rq, "classify_intent", intent_ok)
    monkeypatch.setattr(rq, "get_agent_response", agent_boom)
    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "hi", "input_source": "text", "screen_context": ""})
    assert r.status_code == 502
    assert "Agent service error" in r.json()["detail"]


def test_unknown_route_is_404(client):
    assert client.get("/api/does-not-exist").status_code == 404


def test_describe_names_the_exception_when_the_message_is_empty():
    """httpx timeouts carry no message; the old `str(e)` produced
    'Agent service error: ' which gave whoever debugged it nothing."""
    import httpx
    from app.api.deps import describe

    assert describe(httpx.ReadTimeout("")) == "ReadTimeout"
    assert describe(RuntimeError("boom")) == "RuntimeError: boom"


def test_malformed_session_id_is_400_not_503(client, monkeypatch):
    """Bad input must not be reported as a database outage asking to be retried."""
    import app.api.routes_query as rq
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        rq.parse_session_uuid("not-a-uuid")
    assert exc.value.status_code == 400

    r = client.post("/api/query", json={
        "session_id": "not-a-uuid", "input_text": "hi",
        "input_source": "text", "screen_context": ""})
    assert r.status_code in (400, 503)  # 503 only because the DB is absent here


def test_request_id_and_process_time_headers(client):
    r = client.get("/health")
    assert "X-Request-ID" in r.headers
    assert "X-Process-Time" in r.headers


def test_rate_limit_key_is_per_user_when_authenticated():
    """IP-only keying lets one abusive client lock everyone out behind NAT."""
    from app.main import _rate_limit_key
    from app.api.auth import create_access_token

    class Req:
        client = type("C", (), {"host": "203.0.113.9"})()
        def __init__(self, auth):
            self.headers = {"authorization": auth} if auth else {}

    tok_a = create_access_token({"sub": "user-a"})
    tok_b = create_access_token({"sub": "user-b"})
    assert _rate_limit_key(Req(f"Bearer {tok_a}")) == "user:user-a"
    assert _rate_limit_key(Req(f"Bearer {tok_b}")) == "user:user-b"
    assert _rate_limit_key(Req("")) == "ip:203.0.113.9"
    assert _rate_limit_key(Req("Bearer garbage")) == "ip:203.0.113.9"


def test_full_bucket_for_one_user_does_not_block_another(client):
    """Regression for the NAT problem: with IP-only buckets, filling the shared
    bucket locked out every other user behind the same source address."""
    import app.main as service
    from app.api.auth import create_access_token
    service._rate_limit_store.clear()
    tok_a = create_access_token({"sub": "user-a"})
    tok_b = create_access_token({"sub": "user-b"})
    service._rate_limit_store["user:user-a"] = [__import__("time").time()] * 200
    try:
        assert client.get("/health", headers={"Authorization": f"Bearer {tok_a}"}).status_code == 429
        assert client.get("/health", headers={"Authorization": f"Bearer {tok_b}"}).status_code == 200
    finally:
        service._rate_limit_store.clear()


def test_rate_limit_returns_429(client):
    """Regression: the limiter once returned 500 because a dict was handed to
    starlette's bare Response instead of JSONResponse."""
    import app.main as service
    service._rate_limit_store.clear()

    codes = [client.get("/health").status_code for _ in range(205)]
    assert codes[0] == 200
    assert 429 in codes
    assert codes[-1] == 429
