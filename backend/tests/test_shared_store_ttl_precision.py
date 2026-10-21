"""Sub-second TTL precision across the Redis + local layers.

`set()` used `setex(max(1, ceil(ttl_seconds)))`, so a 0.05 s TTL became a full
second in Redis while the local fallback copy expired at 0.05 s. `get()` reads
Redis first, so it returned state the local layer had already declared dead -
two answers to one question, in the store that holds pending confirmations and
share tokens. Found by running the suite with Redis actually present: the same
tests passed silently whenever Redis was down, which is exactly how the claim
"all green" stayed true for so long.
"""
import pytest

import app.services.session_memory as sm


class RecordingClient:
    """Minimal Redis stand-in that records how a write was timed."""

    def __init__(self):
        self.writes = []

    def set(self, key, value, ex=None, px=None):
        self.writes.append({"key": key, "ex": ex, "px": px})
        return True

    def setex(self, key, seconds, value):
        # Present so a regression to the seconds-only call is visible.
        self.writes.append({"key": key, "ex": seconds, "px": None})
        return True

    def get(self, key):
        return None

    def delete(self, key):
        return 1

    def ttl(self, key):
        return -2


@pytest.fixture
def redis_client(monkeypatch):
    client = RecordingClient()
    monkeypatch.setattr(sm, "_client", client)
    return client


def test_subsecond_ttl_writes_milliseconds_not_ceil_to_one_second(redis_client):
    store = sm.SharedStore(namespace="px-test")
    store.set("k", {"v": 1}, ttl_seconds=0.05)

    assert len(redis_client.writes) == 1
    write = redis_client.writes[0]
    assert write["px"] == 50, f"expected 50ms lifetime, got {write}"
    assert write["ex"] is None, "seconds-granularity SETEX is what lost the precision"


def test_whole_second_ttl_also_uses_px(redis_client):
    store = sm.SharedStore(namespace="px-test")
    store.set("k", {"v": 1}, ttl_seconds=90)
    assert redis_client.writes[0]["px"] == 90_000


def test_ttl_below_one_millisecond_never_becomes_no_expiry(redis_client):
    """0.0001 s must not round down to 0, which Redis rejects / treats oddly."""
    store = sm.SharedStore(namespace="px-test")
    store.set("k", {"v": 1}, ttl_seconds=0.0001)
    assert redis_client.writes[0]["px"] >= 1


def test_no_ttl_writes_without_expiry(redis_client):
    store = sm.SharedStore(namespace="px-test")
    store.set("k", {"v": 1})
    write = redis_client.writes[0]
    assert write["px"] is None and write["ex"] is None


def test_local_copy_and_redis_agree_on_lifetime(redis_client):
    """The local fallback must not expire before Redis says the value is gone."""
    import time

    store = sm.SharedStore(namespace="agree")
    store.set("k", {"v": 1}, ttl_seconds=0.05)
    time.sleep(0.08)
    # RecordingClient.get() returns None (mirrors Redis expiry), and the local
    # copy is past its 0.05 s - both layers must now report the same thing.
    assert store.get("k") is None
