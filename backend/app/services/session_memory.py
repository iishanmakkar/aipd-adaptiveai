"""Phase 2.3 — Redis-backed shared store with in-memory TTL fallback.

Single-instance dev boots with no REDIS_URL (old behavior preserved);
with REDIS_URL set (compose provides redis://redis:6379/0) pending
confirmations, narration cursors and session flags survive backend restarts
and work across replicas.
"""
from __future__ import annotations

import json
import math
import os
import time
from collections import OrderedDict

_REDIS_URL = os.getenv("REDIS_URL", "")
_client = None

if _REDIS_URL:
    try:
        import redis  # type: ignore

        _client = redis.Redis.from_url(_REDIS_URL, decode_responses=True)
        _client.ping()
    except Exception:
        _client = None


class SharedStore:
    """get/set/delete with TTL; local OrderedDict fallback with LRU+TTL."""

    def __init__(self, max_entries: int = 1000, namespace: str = "adaptiveai"):
        self.max_entries = max_entries
        self.namespace = namespace
        self._local: OrderedDict[str, tuple[str, float, float | None]] = OrderedDict()

    def _key(self, key: str) -> str:
        return f"{self.namespace}:{key}"

    def set(self, key: str, value: dict | str, ttl_seconds: float | None = None) -> None:
        payload = value if isinstance(value, str) else json.dumps(value)
        if _client is not None:
            try:
                if ttl_seconds:
                    # Redis takes whole seconds: ceil (min 1) so sub-second
                    # TTLs survive instead of int() truncating them to 0.
                    _client.setex(self._key(key), max(1, math.ceil(ttl_seconds)), payload)
                else:
                    _client.set(self._key(key), payload)
            except Exception:
                pass
        # Write-through: the local fallback is refreshed on every set, even
        # when Redis succeeded. Without this, a Redis-only write goes stale
        # locally and resurrects after the Redis key expires (get falls back
        # to the local copy on a Redis miss).
        exp = (time.time() + ttl_seconds) if ttl_seconds else None
        self._local[key] = (payload, time.time(), exp)
        self._local.move_to_end(key)
        while len(self._local) > self.max_entries:
            self._local.popitem(last=False)

    def get(self, key: str) -> str | None:
        if _client is not None:
            try:
                hit = _client.get(self._key(key))
                if hit is not None:
                    return hit  # type: ignore[return-value]
                # Redis miss: a write during an outage went to the local
                # fallback below, so keep reading there instead of reporting
                # the outage-window value as lost now that Redis is back.
            except Exception:
                pass
        entry = self._local.get(key)
        if entry is None:
            return None
        payload, _, exp = entry
        if exp is not None and time.time() > exp:
            self._local.pop(key, None)
            return None
        self._local.move_to_end(key)
        return payload

    def delete(self, key: str) -> None:
        if _client is not None:
            try:
                _client.delete(self._key(key))
            except Exception:
                pass
        self._local.pop(key, None)

    def ttl_remaining(self, key: str) -> float | None:
        """Seconds left on key's absolute expiry, None if no expiry set."""
        if _client is not None:
            try:
                ttl = _client.ttl(self._key(key))
                if ttl is not None and ttl > 0:
                    return float(ttl)
                if ttl == -1:
                    return None
                # ttl 0/-2 (expiring this second or gone): fall through to the
                # local fallback, which reports None for missing/expired keys.
            except Exception:
                pass
        entry = self._local.get(key)
        if entry is None:
            return None
        _, _, exp = entry
        if exp is None:
            return None
        remaining = exp - time.time()
        if remaining <= 0:
            # Expired: evict and report no expiry (None), so
            # save_preserving_ttl falls back to the default TTL instead of
            # resurrecting the key with a full TTL on a 0.0 reading.
            self._local.pop(key, None)
            return None
        return remaining


# Shared instances used by query/monitor/share routes when they opt in.
pending_store = SharedStore(namespace="pending")
live_pages_store = SharedStore(namespace="live_pages")
monitor_store = SharedStore(namespace="monitor")
session_flags = SharedStore(namespace="session")
share_store = SharedStore(namespace="share")


class SharedDict:
    """Drop-in mapping replacement for the old module-level dicts.

    Behaves like a dict (getitem/setitem/delitem/contains/get/pop/
    setdefault) but persists every write through a SharedStore, so state
    survives backend restarts and works across replicas when REDIS_URL is
    set. Values must be JSON-serializable (all current callers qualify:
    held confirmations, live-page urls, monitor cursors, share tokens).
    Nested in-place mutation (d[k]["x"] = ...) does NOT persist - callers
    must read-modify-write via get + set instead.
    """

    def __init__(self, store: SharedStore, default_ttl: float | None = None):
        self._store = store
        self._ttl = default_ttl

    def __getitem__(self, key: str):
        raw = self._store.get(key)
        if raw is None:
            raise KeyError(key)
        return json.loads(raw)

    def __setitem__(self, key: str, value) -> None:
        self._store.set(key, json.dumps(value), ttl_seconds=self._ttl)

    def save_preserving_ttl(self, key: str, value) -> None:
        """Rewrite without refreshing the absolute expiry (no sliding TTL)."""
        remaining = self._store.ttl_remaining(key)
        # `is not None`: an exactly-expired key reads 0.0, which is falsy -
        # the old truthiness check resurrected it with a full default TTL.
        ttl = remaining if remaining is not None else self._ttl
        self._store.set(key, json.dumps(value), ttl_seconds=ttl)

    def __delitem__(self, key: str) -> None:
        if self._store.get(key) is None:
            raise KeyError(key)
        self._store.delete(key)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and self._store.get(key) is not None

    def get(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def pop(self, key: str, *default):
        try:
            value = self[key]
        except KeyError:
            if default:
                return default[0]
            raise
        self._store.delete(key)
        return value

    def setdefault(self, key: str, default=None):
        try:
            return self[key]
        except KeyError:
            self[key] = default if default is not None else {}
            return self[key]
