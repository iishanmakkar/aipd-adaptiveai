"""Hardening contracts added in Round 4.

Server-side upload validation (a malicious client skips the frontend entirely),
the production startup guard, and the metrics endpoint.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest


def test_vlm_rejects_oversized_declared_payload(client, monkeypatch):
    r = client.post("/v1/chat/completions", json={"messages": []},
                    headers={"Content-Length": str(16 * 1024 * 1024)})
    # httpx/Starlette may override content-length; the handler also re-checks
    # the serialized body size, so 413 either way
    assert r.status_code in (413, 400)


def test_vlm_rejects_huge_body(client):
    # ~16MB of data URI that bypasses content-length games: the serialized-body
    # check in the handler must catch it
    big = "data:image/jpeg;base64," + "A" * (16 * 1024 * 1024)
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": big}},
        ]}]})
    assert r.status_code == 413


def test_vlm_rejects_unsupported_image_format(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "nim_api_key", "k")
    r = client.post("/v1/chat/completions", json={
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "describe"},
            {"type": "image_url", "image_url": {"url": "data:application/x-msdownload;base64,AAAA"}},
        ]}]})
    assert r.status_code == 415


def test_vlm_rejects_more_than_four_images(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "nim_api_key", "k")
    content = [{"type": "text", "text": "describe"}] + [
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,AAA{i}"}}
        for i in range(5)
    ]
    r = client.post("/v1/chat/completions", json={"messages": [{"role": "user", "content": content}]})
    assert r.status_code == 413


def test_production_guard_refuses_debug_build():
    """ADAPTIVEAI_PRODUCTION=1 + DEBUG=True must refuse to boot - that combo
    auto-logs every visitor in as the demo user and opens CORS to *."""
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('booted')"],
        cwd=backend_dir,
        env={
            **{"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
               "PATH": __import__("os").environ.get("PATH", "")},
            "ADAPTIVEAI_PRODUCTION": "1",
            "SUPABASE_DB_URL": "",
            "DEBUG": "True",
        },
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "Refusing to start" in (result.stderr + result.stdout)


def test_production_guard_refuses_default_jwt_secret():
    """ADAPTIVEAI_PRODUCTION=1 with the shipped JWT default must refuse to boot -
    the default is public, so production would accept forged tokens."""
    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('booted')"],
        cwd=backend_dir,
        env={
            **{"SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", ""),
               "PATH": __import__("os").environ.get("PATH", "")},
            "ADAPTIVEAI_PRODUCTION": "1",
            "SUPABASE_DB_URL": "",
            "DEBUG": "False",
            # Empty beats any backend/.env on disk: the guard must fire on a
            # missing secret even when a dev .env file happens to exist.
            "JWT_SECRET": "",
        },
        capture_output=True, text=True, timeout=60,
    )
    assert result.returncode != 0
    assert "JWT_SECRET" in (result.stderr + result.stdout)


def test_forged_token_never_gets_demo_user(client):
    """A garbage bearer token must 401 even in DEBUG (offline suite runs with
    DEBUG=True) - it must never mint a demo identity. get_db is stubbed so the
    token path itself is exercised (offline demo mode would otherwise 503 on
    the DB dependency before token logic runs)."""
    from app.main import app
    from app.database import get_db
    from tests.conftest import FakeSession

    async def _fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    try:
        r = client.get("/api/preferences",
                       headers={"Authorization": "Bearer forged-token"})
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 401, r.text


def test_heavy_chromium_endpoints_have_own_budgets(client, monkeypatch):
    """/api/form-fill (10/min) and /api/page-context (30/min) are IP-budgeted
    apart from the shared 200/min bucket - anonymous Chromium is expensive."""
    import app.main as service
    import app.api.routes_formfill as ff

    class FakeAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            return {"status": "success"}

    monkeypatch.setattr(ff, "FormAgent", FakeAgent)
    service._rate_limit_store.clear()
    try:
        codes = [client.post("/api/form-fill",
                             json={"url": "https://example.com/",
                                   "values": {"a": "b"}}).status_code
                 for _ in range(12)]
        assert 429 in codes, "form-fill should trip its own small budget"
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()


def test_formfill_values_are_bounded(client):
    big = {f"field-{i}": "x" for i in range(101)}
    r = client.post("/api/form-fill",
                    json={"url": "https://example.com/", "values": big})
    assert r.status_code == 422, r.text
    r = client.post("/api/form-fill",
                    json={"url": "https://example.com/",
                          "values": {"a": "x" * 2001}})
    assert r.status_code == 422, r.text


def test_metrics_endpoint_counts_and_percentiles(client):
    client.get("/health")
    client.get("/health")
    client.get("/api/does-not-exist")
    r = client.get("/api/metrics")
    assert r.status_code == 200
    body = r.json()
    assert body["total_requests"] >= 3
    assert body["total_4xx"] >= 1
    assert body["latency_ms"]["p50"] is not None
    assert body["uptime_seconds"] > 0


def test_delete_account_requires_db(client):
    r = client.request("DELETE", "/auth/account",
                       headers={"Authorization": "Bearer whatever"})
    # No DB in offline mode: dependency chain must 503, never 500
    assert r.status_code == 503


def test_auth_endpoints_have_a_tighter_ip_bucket(client):
    """register/login are unauthenticated (IP-keyed); they get a separate,
    tighter budget so one client cannot lock out a shared NAT IP or farm
    fresh per-user buckets by mass-registering."""
    import app.main as service
    service._rate_limit_store.clear()
    try:
        codes = []
        for i in range(15):
            codes.append(client.post("/auth/register",
                                     json={"email": f"rl{i}@example.com", "password": "x"}).status_code)
        assert 429 in codes, "register should hit the tight auth limit before the 200 general limit"
        # the auth bucket tripped, but the general per-IP bucket must still be
        # far from exhausted - normal endpoints keep working
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()


# --- operator-hardening bug hunts (round 5) ---------------------------------

def _authed_client(client, token):
    return {"Authorization": f"Bearer {token}"}


def test_expired_token_is_401_not_demo(client):
    """A correctly-signed but expired token must 401 in every mode (offline
    demo mode included) - never a demo identity."""
    from datetime import timedelta
    from uuid import uuid4
    from app.api.auth import create_access_token
    from app.database import get_db
    from app.main import app
    from tests.conftest import FakeSession

    token = create_access_token({"sub": str(uuid4())},
                                expires_delta=timedelta(seconds=-30))

    async def _fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    try:
        r = client.get("/api/preferences", headers=_authed_client(client, token))
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 401, r.text


def test_unknown_subject_is_401_with_db(client, monkeypatch):
    """A valid signature for a subject with no row must 401 (minting a demo
    identity for an attacker-chosen UUID would allow id impersonation)."""
    from uuid import uuid4
    import app.api.auth as auth_mod
    from app.api.auth import create_access_token
    from app.database import get_db
    from app.main import app
    from tests.conftest import FakeSession

    monkeypatch.setattr(auth_mod, "is_db_available", lambda: True)
    token = create_access_token({"sub": str(uuid4())})

    async def _fake_db():
        yield FakeSession()  # empty: no user row for the subject

    app.dependency_overrides[get_db] = _fake_db
    try:
        r = client.get("/api/preferences", headers=_authed_client(client, token))
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 401, r.text


def test_non_uuid_subject_is_401_not_500(client, monkeypatch):
    """A valid signature with a garbage subject used to escape as ValueError
    and 500; both the strict and the optional dependency must 401."""
    import app.api.auth as auth_mod
    from app.api.auth import create_access_token
    from app.database import get_db
    from app.main import app
    from tests.conftest import FakeSession

    monkeypatch.setattr(auth_mod, "is_db_available", lambda: True)
    token = create_access_token({"sub": "admin"})

    async def _fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    try:
        assert client.get("/auth/me", headers=_authed_client(client, token)).status_code == 401
        assert client.get("/api/preferences", headers=_authed_client(client, token)).status_code == 401
    finally:
        app.dependency_overrides.pop(get_db, None)


async def test_no_token_debug_demo_is_kept():
    """The UI has no login flow: no token + DEBUG must still yield the demo
    user (this fallback is intentionally kept, not a hole)."""
    from app.api.auth import get_current_user_optional, DemoUser
    from tests.conftest import FakeSession
    user = await get_current_user_optional(token=None, db=FakeSession())
    assert isinstance(user, DemoUser)


def test_valid_token_is_401_in_no_db_mode(client, monkeypatch):
    """No-DB demo mode used to mint a demo identity from ANY valid-signature
    token (attacker-chosen subject accepted). Only the no-token path yields a
    demo user; any presented token 401s."""
    from uuid import uuid4
    import app.api.auth as auth_mod
    from app.api.auth import create_access_token
    from app.database import get_db
    from app.main import app
    from tests.conftest import FakeSession

    monkeypatch.setattr(auth_mod, "is_db_available", lambda: False)
    token = create_access_token({"sub": str(uuid4())})

    async def _fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    try:
        r = client.get("/api/preferences", headers=_authed_client(client, token))
    finally:
        app.dependency_overrides.pop(get_db, None)
    assert r.status_code == 401, r.text


def test_heavy_budget_survives_trailing_slash(client, monkeypatch):
    """/api/form-fill/ (trailing slash) bypassed the 10/min heavy budget by
    exact-match miss. Paths normalize before lookup, so both spellings share
    one bucket."""
    import app.main as service
    import app.api.routes_formfill as ff

    class FakeAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            return {"status": "success"}

    monkeypatch.setattr(ff, "FormAgent", FakeAgent)
    service._rate_limit_store.clear()
    try:
        codes = [client.post("/api/form-fill/",
                             json={"url": "https://example.com/",
                                   "values": {"a": "b"}}).status_code
                 for _ in range(12)]
        assert 429 in codes, "trailing-slash form-fill should trip the same 10/min budget"
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()


def test_page_context_budget_trips(client, monkeypatch):
    """/api/page-context gets 30/min apart from the shared bucket: Chromium +
    a VLM call per request is too expensive to leave unbounded."""
    import app.main as service
    import app.api.routes_pagecontext as pc

    class FakeBrowser:
        async def start(self):
            pass

        async def navigate(self, url):
            return {"url": url, "http_status": 200}

        async def wait_for_load(self):
            pass

        async def get_accessibility_tree(self):
            return {"tree": []}

        async def get_title(self):
            return "t"

        async def get_vlm_description(self, prompt):
            return {"description": "d"}

        async def stop(self):
            pass

    monkeypatch.setattr(pc, "BrowserTool", FakeBrowser)
    service._rate_limit_store.clear()
    try:
        codes = [client.post("/api/page-context",
                             json={"url": "https://example.com/"}).status_code
                 for _ in range(32)]
        assert 429 in codes, "page-context should trip its own 30/min budget"
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()


def test_pagecontext_start_failure_is_503_not_500(client, monkeypatch):
    """No Chromium installed is a config error (503), never a 500."""
    import app.api.routes_pagecontext as pc

    class NoChromium:
        async def start(self):
            raise RuntimeError("playwright is not installed")

        async def stop(self):
            pass

    monkeypatch.setattr(pc, "BrowserTool", NoChromium)
    r = client.post("/api/page-context", json={"url": "https://example.com/"})
    assert r.status_code == 503, r.text


def test_special_budgets_do_not_touch_global_bucket(client, monkeypatch):
    """Auth + heavy requests must not also consume the shared 200/min bucket
    (their comments promise 'does not touch normal traffic' / 'instead of')."""
    import app.main as service
    import app.api.routes_formfill as ff

    class FakeAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            return {"status": "success"}

    monkeypatch.setattr(ff, "FormAgent", FakeAgent)
    service._rate_limit_store.clear()
    try:
        for i in range(5):
            client.post("/api/form-fill",
                        json={"url": "https://example.com/", "values": {"a": "b"}})
        for i in range(3):
            client.post("/auth/register",
                        json={"email": f"gb{i}@example.com", "password": "x"})
        assert not [k for k in service._rate_limit_store if k.startswith("ip:")], \
            f"global bucket consumed: {list(service._rate_limit_store)}"
        assert client.get("/health").status_code == 200
    finally:
        service._rate_limit_store.clear()


def test_heavy_budget_is_per_user_when_authenticated(client, monkeypatch):
    """Behind NAT every browser looks like one IP: an authenticated caller's
    Chromium budget must key on their user id, not the shared IP."""
    from uuid import uuid4
    import app.main as service
    import app.api.routes_formfill as ff
    from app.api.auth import create_access_token

    class FakeAgent:
        def __init__(self):
            pass

        async def fill_form(self, url, replay=False, user_values=None):
            return {"status": "success"}

    monkeypatch.setattr(ff, "FormAgent", FakeAgent)
    sub = str(uuid4())
    token = create_access_token({"sub": sub})
    service._rate_limit_store.clear()
    try:
        r = client.post("/api/form-fill",
                        json={"url": "https://example.com/", "values": {"a": "b"}},
                        headers=_authed_client(client, token))
        assert r.status_code == 200, r.text
        assert f"heavy:/api/form-fill:user:{sub}" in service._rate_limit_store
    finally:
        service._rate_limit_store.clear()


def test_parse_allowed_hosts_drops_blanks():
    from app.main import _parse_allowed_hosts
    assert _parse_allowed_hosts("a.example.com, b.example.com") == ["a.example.com", "b.example.com"]
    assert _parse_allowed_hosts("  , ,") == []
    assert _parse_allowed_hosts("") == []


def test_cors_headers_present_explicit_origins(client):
    """Explicit origins (never '*') with credentials for the cookie-less
    Bearer flow; the UI origin must be echoed back."""
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert r.headers.get("access-control-allow-credentials") == "true"


def test_blank_query_input_is_rejected_at_schema():
    """min_length=1 lets '   ' through; blank input would burn an intent LLM
    call plus an agent call on nothing."""
    import pytest as _pytest
    from app.schemas.query import QueryRequest
    with _pytest.raises(Exception):
        QueryRequest(session_id="s", input_text="   ")
    with _pytest.raises(Exception):
        QueryRequest(session_id="s", input_text="")
    assert QueryRequest(session_id="s", input_text="hi").input_text == "hi"


def test_blank_password_is_rejected_at_schema():
    """An empty/whitespace password would bcrypt-hash into a real credential."""
    import pytest as _pytest
    from app.schemas.auth import UserRegister, UserLogin
    for model in (UserRegister, UserLogin):
        with _pytest.raises(Exception):
            model(email="a@b.c", password="")
        with _pytest.raises(Exception):
            model(email="a@b.c", password="   ")
    assert UserRegister(email="a@b.c", password="x").password == "x"


def test_share_malformed_record_is_404_not_500():
    """A share row without created_at (legacy/corrupt) must read as expired."""
    from fastapi import HTTPException
    from app.api.routes_share import _get_share, _SHARES
    _SHARES["legacy-no-ts"] = {"session_id": "x", "annotations": []}
    try:
        try:
            _get_share("legacy-no-ts")
        except HTTPException as e:
            assert e.status_code == 404
        else:
            raise AssertionError("malformed share should 404")
    finally:
        _SHARES.pop("legacy-no-ts", None)


async def test_browser_transport_failure_is_honest_answer(monkeypatch):
    """A dead browser-agent during the intent-driven open must answer honestly
    (like the message-driven opener), never escape as a 500."""
    import app.api.routes_query as rq
    from types import SimpleNamespace

    async def _dead(*a, **k):
        raise ConnectionError("refused")

    async def _capture(*a, **k):
        return {"answered": True}

    monkeypatch.setattr(rq, "_ensure_live_session", _dead)
    monkeypatch.setattr(rq, "_browser_answer", _capture)
    intent = SimpleNamespace(intent="browser_inspect", extracted_entity="x",
                             reasoning="r", confidence=0.9)
    req = SimpleNamespace(session_id="chat-1", input_text="see https://example.com/",
                          screen_context=None)
    out = await rq._handle_browser_intent(None, None, SimpleNamespace(id="u"),
                                          "session-uuid", req, intent,
                                          "rid", 0)
    assert out == {"answered": True}

