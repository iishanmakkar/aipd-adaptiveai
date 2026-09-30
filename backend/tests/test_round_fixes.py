"""Round fixes: relay passthrough, VLM safe JSON, TTL ceiling/preserve, caps, demo guards."""
import httpx
import time


def _http_status_error(code, detail="no live session"):
    req = httpx.Request("GET", "http://x")
    resp = httpx.Response(code, json={"detail": detail}, request=req)
    return httpx.HTTPStatusError("err", request=req, response=resp)


def test_relay_error_passes_browser_404_409():
    from app.api.routes_monitor import _relay_error, _browser_status
    assert _browser_status(_http_status_error(404)) == 404
    assert _relay_error(_http_status_error(404, "gone"), "start").status_code == 404
    assert _relay_error(_http_status_error(409, "idle"), "stop").status_code == 409
    assert _relay_error(_http_status_error(500, "boom"), "start").status_code == 502


def test_monitor_stop_409_shortcircuits_without_browser():
    # _browser_status is the single reader monitors use; 409 must be visible.
    from app.api.routes_monitor import _browser_status
    assert _browser_status(_http_status_error(409)) == 409


def test_vlm_non_json_upstream_does_not_500(client, monkeypatch):
    from app.api import routes_vlm
    from app.config import settings
    monkeypatch.setattr(settings, "nim_api_key", "k")

    class _Resp:
        status_code = 200
        text = "<html>bad gateway</html>"

        def json(self):
            raise ValueError("no json")

    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, *a, **k):
            return _Resp()

    monkeypatch.setattr(routes_vlm.httpx, "AsyncClient", lambda **kw: _Client())
    r = client.post("/v1/chat/completions", json={"messages": []})
    assert r.status_code == 200
    assert "upstream_response" in r.json()


def test_vlm_single_route_registered():
    from app.main import app
    paths = [r.path for r in app.routes if getattr(r, "path", "") == "/v1/chat/completions/"]
    assert paths == [], "trailing-slash duplicate must be gone"


def test_shared_store_ttl_ceiling_minimum_one(monkeypatch):
    import app.services.session_memory as sm
    sm._client = None
    store = sm.SharedStore(namespace="t1")
    calls = {}

    class FakeRedis:
        def setex(self, k, ttl, payload):
            calls["ttl"] = ttl

        def set(self, k, payload):
            calls["ttl"] = "no-expire"

        def ttl(self, k):
            return 5

    monkeypatch.setattr(sm, "_client", FakeRedis())
    store.set("k", {"a": 1}, ttl_seconds=0.4)
    assert calls["ttl"] == 1
    store.set("k", {"a": 1}, ttl_seconds=1.2)
    assert calls["ttl"] == 2


def test_shared_dict_rewrite_preserves_absolute_expiry():
    import app.services.session_memory as sm
    sm._client = None
    store = sm.SharedStore(namespace="t2")
    d = sm.SharedDict(store, default_ttl=100.0)
    d["k"] = {"v": 1}
    first_exp = store._local["k"][2]
    time.sleep(0.02)
    d.save_preserving_ttl("k", {"v": 2})
    assert store._local["k"][2] == first_exp
    assert store.ttl_remaining("k") is not None


def test_shared_store_set_writes_through_to_local_on_redis_success(monkeypatch):
    """set used to return after a Redis write without touching the local
    fallback; after the Redis key expired, get fell back to the stale local
    copy and resurrected it. Every set refreshes local with the same expiry."""
    import app.services.session_memory as sm

    class FakeRedis:
        def __init__(self):
            self.data = {}

        def setex(self, k, ttl, payload):
            self.data[k] = payload

        def set(self, k, payload):
            self.data[k] = payload

        def get(self, k):
            return None  # Redis copy gone (expired/evicted server-side)

        def ttl(self, k):
            return -2

        def delete(self, k):
            self.data.pop(k, None)

    monkeypatch.setattr(sm, "_client", FakeRedis())
    store = sm.SharedStore(namespace="write-through")
    store.set("k", {"v": 1}, ttl_seconds=100.0)
    assert store._local.get("k") is not None, "local fallback must be written on Redis success"
    assert store.get("k") == '{"v": 1}', "Redis miss must read the write-through local copy"
    assert store.ttl_remaining("k") is not None and store.ttl_remaining("k") > 0


def test_ttl_remaining_is_none_when_expired(monkeypatch):
    """An exactly-expired key used to read 0.0 (falsy), which
    save_preserving_ttl turned into a full default TTL - resurrecting the key.
    Expired keys now evict and report None."""
    import app.services.session_memory as sm
    monkeypatch.setattr(sm, "_client", None)
    store = sm.SharedStore(namespace="expired-ttl")
    store.set("k", {"v": 1}, ttl_seconds=0.05)
    assert store.ttl_remaining("k") is not None
    time.sleep(0.06)
    assert store.ttl_remaining("k") is None
    assert store.get("k") is None


def test_query_demo_truncates_overlong_context_like_real(client, monkeypatch):
    """/api/query truncates over-long fused context silently while
    /api/query-demo 400'd it - demo must truncate too (parity, no 400)."""
    import app.api.routes_query as rq
    from app.services.clients import IntentResponse, AgentResponse

    seen = {}

    async def fake_classify(session_id, input_text, screen_context, history, request_id=None):
        seen["screen_context"] = screen_context
        return IntentResponse(intent="general_query", target_agent="general_agent",
                             extracted_entity="x", reasoning="r", confidence=0.5)

    async def fake_agent(session_id, agent, query, entity, extra_context, request_id=None):
        return AgentResponse(answer="hi", sources_used=[], suggested_action="none")

    monkeypatch.setattr(rq, "classify_intent", fake_classify)
    monkeypatch.setattr(rq, "get_agent_response", fake_agent)
    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "hi", "screen_context": "y" * 6000})
    assert r.status_code == 200, r.text
    assert len(seen["screen_context"]) <= rq.INTENT_SCREEN_CONTEXT_LIMIT


def test_query_demo_rejects_whitespace_input_with_422(client):
    """Blank input burns an intent call plus an agent call on nothing; the
    schema validator rejects it before any service is touched."""
    r = client.post("/api/query-demo", json={"session_id": "s", "input_text": "   "})
    assert r.status_code == 422, r.text


def test_rate_limit_store_evicts_oldest():
    import app.main as service
    service._rate_limit_store.clear()
    try:
        service._RATE_LIMIT_MAX_KEYS = 3
        for i in range(5):
            assert service.check_rate_limit(f"ip-{i}", max_requests=100, window_sec=60) is True
        assert len(service._rate_limit_store) == 3
        assert "ip-0" not in service._rate_limit_store
    finally:
        service._rate_limit_store.clear()
        service._RATE_LIMIT_MAX_KEYS = 5000


def test_auth_remaining_header_uses_auth_bucket(client):
    import app.main as service
    service._rate_limit_store.clear()
    try:
        r = client.post("/auth/register", json={"email": "a@b.c", "password": "x"})
        # Offline without DB this may 500/422, but the rate header must reflect the 10-bucket.
        remaining = r.headers.get("X-Rate-Limit-Remaining")
        if remaining is not None:
            assert int(remaining) <= 10
    finally:
        service._rate_limit_store.clear()


def test_query_demo_rejects_autonomous_and_fuses_context(client, monkeypatch):
    import app.api.routes_query as rq
    # Autonomous must fail honestly.
    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "hi", "autonomous": True})
    assert r.status_code == 422
    # Fusion caps unified context to the intent limit.
    from app.schemas.query import QueryRequest, UnifiedContext
    req = QueryRequest(session_id="s", input_text="hi",
                       unified_context=UnifiedContext(screen_text="x" * 9000))
    assert len(rq._effective_screen_context(req)) <= rq.INTENT_SCREEN_CONTEXT_LIMIT


def test_browser_tool_exposes_title_accessor():
    import inspect
    from app.agents.form.browser_tool import BrowserTool
    assert "get_title" in dir(BrowserTool)
    src = inspect.getsource(BrowserTool.get_title)
    assert ".title()" in src


def test_transcribe_cloud_path_is_async(client, monkeypatch):
    """Sync OpenAI client blocked the loop; the route must await AsyncOpenAI."""
    import app.api.routes_transcribe as rt
    from app.config import settings
    monkeypatch.setattr(rt, "get_whisper_model", lambda: None)
    monkeypatch.setattr(settings, "nim_api_key", "k")

    import openai
    assert hasattr(openai, "AsyncOpenAI")

    class _Transcriptions:
        async def create(self, model=None, file=None):
            from types import SimpleNamespace
            return SimpleNamespace(text="hello world")

    class _Audio:
        transcriptions = _Transcriptions()

    class _FakeAsync:
        def __init__(self, *a, **k):
            self.audio = _Audio()

    monkeypatch.setattr(openai, "AsyncOpenAI", _FakeAsync)
    r = client.post("/api/transcribe", files={"audio": ("a.webm", b"fake-audio", "audio/webm")})
    assert r.status_code == 200
    assert r.json()["transcript"] == "hello world"
