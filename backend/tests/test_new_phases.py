"""New phases: UnifiedContext fusion, shared store fallback, braille, share validation."""
from app.schemas.query import QueryRequest, UnifiedContext
from app.api.routes_query import _effective_screen_context
from app.services.session_memory import SharedDict, SharedStore
from app.services.braille_formatter import to_braille_text, ascii_to_braille


def test_unified_context_flattens_into_screen_ctx():
    req = QueryRequest(
        session_id="s1",
        input_text="hello",
        screen_context="Live page: demo",
        unified_context=UnifiedContext(screen_text="Name field here", dom_snapshot="<input>", disability_profile="blind"),
    )
    fused = _effective_screen_context(req)
    assert fused is not None and "Live page: demo" in fused and "Name field here" in fused


def test_unified_context_absent_preserves_legacy():
    req = QueryRequest(session_id="s1", input_text="hi", screen_context="plain")
    assert _effective_screen_context(req) == "plain"


def test_shared_store_memory_fallback_with_ttl():
    store = SharedStore(namespace="test")
    store.set("k", {"v": 1}, ttl_seconds=0.05)
    assert store.get("k") is not None
    import time

    time.sleep(0.06)
    assert store.get("k") is None
    store.set("a", "x")
    store.delete("a")
    assert store.get("a") is None


def test_braille_shaping_wraps_and_strips_visual_refs():
    lines = to_braille_text("Click here to continue as shown in the image. " + "word " * 30)
    assert all(len(line) <= 40 for line in lines)
    assert not any("click here" in line.lower() for line in lines)
    assert "⠁" in ascii_to_braille("abc")


def test_braille_chunks_overlong_words_to_display_width():
    """A pasted URL must not leak a >40-cell line to a 40-cell display."""
    lines = to_braille_text("see " + "x" * 90)
    assert all(len(line) <= 40 for line in lines)
    assert "".join(lines) == "see" + "x" * 90  # content kept, only wrapping added


def test_unified_context_fusion_respects_intent_limit():
    """Fused context over the intent engine's 5000-char cap came back as a
    400 misreported as 502 - the fusion point caps it instead."""
    from app.api.routes_query import INTENT_SCREEN_CONTEXT_LIMIT
    req = QueryRequest(
        session_id="s1",
        input_text="hello",
        screen_context="x" * 4000,
        unified_context=UnifiedContext(screen_text="y" * 8000, dom_snapshot="z" * 8000),
    )
    fused = _effective_screen_context(req)
    assert fused is not None and len(fused) <= INTENT_SCREEN_CONTEXT_LIMIT
    assert "xxx" in fused  # user context kept, tail truncated


def test_shared_store_redis_miss_reads_outage_window_local(monkeypatch):
    """A write during a Redis outage lives in the local fallback; when Redis
    recovers and misses, the value must still read back (not report lost)."""
    import app.services.session_memory as sm

    store = sm.SharedStore(namespace="probe-fallback")
    store.set("k", {"v": 1})

    class _RedisMiss:
        def get(self, key):
            return None

    monkeypatch.setattr(sm, "_client", _RedisMiss())
    assert store.get("k") == '{"v": 1}'

    class _RedisHit:
        def get(self, key):
            return '{"v": 2}'

    monkeypatch.setattr(sm, "_client", _RedisHit())
    assert store.get("k") == '{"v": 2}'


def test_shared_dict_round_trips_and_expires():
    store = SharedStore(namespace="test-dict")
    d = SharedDict(store, default_ttl=0.05)
    d["k"] = {"kind": "submit", "n": 1}
    assert d["k"]["kind"] == "submit"
    assert "k" in d
    assert d.get("missing") is None
    assert d.get("missing", "fallback") == "fallback"
    d["t"] = {"created_at": 0.0}
    import time

    time.sleep(0.06)
    assert "t" not in d
    # "k" shared the same 0.05s TTL and expired during the sleep above.
    d["k"] = {"kind": "submit", "n": 1}
    assert d.pop("k")["n"] == 1
    assert d.pop("gone", None) is None


def test_query_pending_and_live_pages_are_store_backed():
    import app.api.routes_query as rq

    assert isinstance(rq._pending, SharedDict)
    assert isinstance(rq._live_pages, SharedDict)
    rq._pending["s"] = {"kind": "submit", "created_at": 9999999999.0}
    assert rq._get_pending("s")["kind"] == "submit"
    rq._pending.pop("s", None)
    rq._live_pages["s"] = "http://example.com/"
    assert rq._live_pages.get("s") == "http://example.com/"
    rq._live_pages.pop("s", None)


def test_monitor_cursor_and_share_store_are_backed():
    import app.api.routes_monitor as rm
    import app.api.routes_share as rs

    assert isinstance(rm._monitor_state, SharedDict)
    assert isinstance(rs._SHARES, SharedDict)
    state = rm._cursor("probe")
    assert state["since"] == 0 and state["active"] is False
    assert "created_at" in state  # absolute-expiry anchor for TTL preservation
    state["active"] = True
    rm._save_cursor("probe", state)
    assert rm._cursor("probe")["active"] is True
    rm._monitor_state.pop("probe", None)


def test_invalid_email_is_422_not_503(client):
    """Regression (seen live): a .local address returned 503 'Database
    connection failed' because body validation raised inside the yielded
    get_db session context and got wrapped. Invalid input must stay 422."""
    from app.main import app
    import app.api.routes_auth as routes_auth
    import app.database as dbmod
    from tests.conftest import FakeSession

    class _FakeMaker:
        def __call__(self):
            return self

        async def __aenter__(self):
            return FakeSession()

        async def __aexit__(self, *exc):
            return False

    # Exercise the REAL get_db (not an override): body validation raises
    # inside its yielded session context.
    real_maker, real_flag = dbmod.async_session_maker, dbmod._db_available
    dbmod.async_session_maker = _FakeMaker()
    dbmod._db_available = True
    routes_auth.is_db_available = lambda: True
    try:
        r = client.post("/auth/register", json={"email": "nobody@test.local", "password": "x" * 12})
    finally:
        dbmod.async_session_maker = real_maker
        dbmod._db_available = real_flag
        routes_auth.is_db_available = dbmod.is_db_available
    assert r.status_code == 422, r.text
