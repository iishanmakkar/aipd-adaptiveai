"""A production deployment must not silently downgrade to a per-process store.

`session_memory` falls back to an in-memory TTL dict when Redis is unreachable.
On one dev box that is harmless. On two or more replicas it silently partitions
state: a share token created by replica A is unreadable by replica B, a pending
confirmation lives on exactly one process, and nothing anywhere reports it. The
old code logged a warning and carried on - the same class of "looks fine, is not"
this pass is removing.

Production is defined the way app/main.py already defines it: ADAPTIVEAI_PRODUCTION
set, or DEBUG=False.
"""
import pytest

import app.services.session_memory as sm


class _Unreachable:
    """Stands in for a redis client that cannot be reached at all."""

    @staticmethod
    def from_url(*a, **k):
        return _Unreachable()

    def ping(self):
        raise ConnectionError("connection refused")


@pytest.fixture(autouse=True)
def _restore(monkeypatch):
    original_client, original_fallback = sm._client, sm._fallback
    yield
    sm._client, sm._fallback = original_client, original_fallback
    monkeypatch.setattr(sm.settings, "debug", True, raising=False)


def _force_no_redis(monkeypatch):
    import redis
    monkeypatch.setattr(redis, "Redis", _Unreachable)


def test_production_refuses_a_missing_shared_store(monkeypatch):
    _force_no_redis(monkeypatch)
    monkeypatch.setattr(sm.settings, "debug", False, raising=False)

    with pytest.raises(RuntimeError, match="shared store"):
        sm._connect()


def test_declared_production_also_refuses(monkeypatch):
    _force_no_redis(monkeypatch)
    monkeypatch.setenv("ADAPTIVEAI_PRODUCTION", "1")

    with pytest.raises(RuntimeError, match="shared store"):
        sm._connect()


def test_dev_still_falls_back_without_raising(monkeypatch):
    """A laptop with no Redis must stay usable - that is the whole point of the
    fallback. It just may not pretend to be shared."""
    _force_no_redis(monkeypatch)

    sm._connect()

    assert sm._client is None
    assert sm._fallback is True


def test_fallback_is_reported_on_the_store_itself(monkeypatch):
    _force_no_redis(monkeypatch)
    sm._connect()
    store = sm.SharedStore(namespace="t")
    assert store.backend == "memory"

    class _Live:
        @staticmethod
        def from_url(*a, **k):
            return _Live()

        def ping(self):
            return True

        def set(self, *a, **k):
            return True

        def get(self, *a, **k):
            return None

        def delete(self, *a, **k):
            return 1

    import redis
    monkeypatch.setattr(redis, "Redis", _Live)
    sm._connect()
    assert sm._fallback is False
    assert store.backend == "redis"
