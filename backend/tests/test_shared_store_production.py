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
import os

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
    # _REDIS_URL is read at import time from the ambient environment, so a host
    # with no Redis configured would take the "not configured" branch and every
    # test below would assert about a code path it never entered. Pin it.
    monkeypatch.setattr(sm, "_REDIS_URL", "redis://localhost:6379/0", raising=False)
    yield
    sm._client, sm._fallback = original_client, original_fallback
    monkeypatch.setattr(sm.settings, "debug", True, raising=False)


def _force_no_redis(monkeypatch):
    import redis
    monkeypatch.setattr(redis, "Redis", _Unreachable)


def test_production_refuses_a_missing_shared_store(monkeypatch):
    _force_no_redis(monkeypatch)
    monkeypatch.setattr(sm.settings, "debug", False, raising=False)

    sm._connect()

    assert "shared store unreachable" in sm.production_refusal()


def test_declared_production_also_refuses(monkeypatch):
    _force_no_redis(monkeypatch)
    monkeypatch.setenv("ADAPTIVEAI_PRODUCTION", "1")

    sm._connect()

    assert "ADAPTIVEAI_PRODUCTION" in sm.production_refusal()


def test_production_refuses_an_unconfigured_store(monkeypatch):
    """The likelier failure than an unreachable Redis: a deploy that never set
    REDIS_URL. It used to boot silently on the per-process fallback."""
    monkeypatch.setattr(sm, "_REDIS_URL", "")
    monkeypatch.setattr(sm.settings, "debug", False, raising=False)

    sm._connect()

    assert "no REDIS_URL is set" in sm.production_refusal()


def test_dev_records_no_refusal(monkeypatch):
    """The refusal must be scoped to a declared production: an offline suite that
    leaves it set would refuse to boot for the wrong reason."""
    _force_no_redis(monkeypatch)

    sm._connect()

    assert sm.production_refusal() is None


def test_declared_production_refuses_to_boot(tmp_path):
    """The recorded reason has to reach the operator as a boot refusal, in the
    same shape as the DEBUG and JWT_SECRET guards."""
    import subprocess
    import sys
    from pathlib import Path

    backend_dir = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, "-c", "from app.main import app; print('booted')"],
        cwd=backend_dir,
        env={
            **{"SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
               "PATH": os.environ.get("PATH", "")},
            "ADAPTIVEAI_PRODUCTION": "1",
            "SUPABASE_DB_URL": "",
            "DEBUG": "False",
            "JWT_SECRET": "a-real-secret-that-is-long-enough-32chars",
            "REDIS_URL": "",
        },
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode != 0, result.stdout
    assert "Refusing to start" in (result.stderr + result.stdout)
    assert "REDIS_URL" in (result.stderr + result.stdout)


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
