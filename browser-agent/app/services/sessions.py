"""Per-chat-session live browser contexts (Round 8).

The old /browse + /fill endpoints were stateless: one URL in, one snapshot
out, browser closed. That made "this page" meaningless across conversation
turns. A LiveSession keeps ONE real Chromium page open per chat session_id so
follow-ups ("where's the submit button", "fill this in") act on the SAME live
page instead of re-navigating every time.

Safety is structural, not advisory:
- sessions open ONLY on explicit user-supplied URLs (the backend only ever
  forwards URLs from user messages, never from RAG output), and every URL
  still passes url_guard (SSRF: no file/internal/metadata targets);
- sensitive domains (banking/login/payment) and irreversible actions
  (submit/pay/confirm/delete clicks) are held as proposals until the user
  explicitly confirms - the confirmation rule from Round 8;
- robots.txt is consulted before ACTING on real http(s) hosts;
- CAPTCHA/bot-challenge markers refuse acts honestly instead of evading;
- per-session rate budgets bound navigations and submits;
- every navigation and every submit is JSON-logged with session + time +
  target, so the logs answer "what did this do on the internet";
- idle sessions are swept (browser closed, resources freed), proven by timer.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger("adaptiveai.browser")

# Irreversible-action verbs: clicking these does something in the real world
# (submit a form, spend money, delete data), so they always need confirmation.
SUBMIT_PATTERNS = (
    "submit", "pay", "confirm", "book", "purchase", "place order",
    "delete", "pay now", "checkout", "reserve",
)

# Domains in this list get an extra confirmation step before even navigating:
# opening them is reversible, but ending up logged-in somewhere sensitive by
# accident is not a mistake worth risking silently.
SENSITIVE_PATTERNS = (
    "bank", "login", "signin", "sign-in", "password", "otp",
    "pay", "payment", "checkout", "wallet",
)

# Markers that mean "this page is actively resisting automation". Acting anyway
# would be evasion; refusing honestly is the feature.
CAPTCHA_MARKERS = (
    "recaptcha", "g-recaptcha", "captcha", "verify you are human",
    "are you a robot", "cloudflare", "challenge-platform", "data-sitekey",
    "just a moment",
)

PROPOSAL_TTL_SECONDS = 300.0


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def is_sensitive_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(p in host for p in SENSITIVE_PATTERNS)


def is_submit_text(label: str, tag: str = "", input_type: str = "") -> bool:
    text = (label or "").lower()
    if tag == "input" and input_type == "submit":
        return True
    return any(p in text for p in SUBMIT_PATTERNS)


def page_text_markers(snapshot: Dict[str, Any]) -> str:
    """Searchable text of a snapshot (title + labels) for CAPTCHA detection."""
    parts = [str(snapshot.get("title", ""))]
    for node in snapshot.get("nodes", []) or []:
        parts.append(str(node.get("label", "")))
    return " ".join(parts).lower()


def detect_captcha(snapshot: Dict[str, Any]) -> Optional[str]:
    blob = page_text_markers(snapshot)
    for marker in CAPTCHA_MARKERS:
        if marker in blob:
            return marker
    return None


class RateBudget:
    """Sliding-window counter: at most `limit` events per `window_seconds`."""

    def __init__(self, limit: int, window_seconds: float = 3600.0):
        self.limit = limit
        self.window = window_seconds
        self._hits: List[float] = []

    def check_and_spend(self, now: Optional[float] = None) -> bool:
        now = time.time() if now is None else now
        self._hits = [t for t in self._hits if now - t < self.window]
        if len(self._hits) >= self.limit:
            return False
        self._hits.append(now)
        return True

    @property
    def used(self) -> int:
        now = time.time()
        self._hits = [t for t in self._hits if now - t < self.window]
        return len(self._hits)


class LiveSession:
    """One chat session's live page: persistent driver + safety state."""

    def __init__(self, session_id: str, driver,
                 nav_per_hour: int = 30, submits_per_hour: int = 5):
        self.session_id = session_id
        self.driver = driver
        self.url: str = ""
        self.title: str = ""
        self.created_at = time.time()
        self.last_active = time.time()
        self.pending: Optional[Dict[str, Any]] = None
        self.nav_budget = RateBudget(nav_per_hour)
        self.submit_budget = RateBudget(submits_per_hour)
        self.action_log: List[Dict[str, Any]] = []
        self.lock = asyncio.Lock()
        # Round 9: page monitoring. None until the user explicitly opts in;
        # a monitor is never created at page load or session open by default.
        self.monitor = None

    def touch(self) -> None:
        self.last_active = time.time()

    def log(self, event: str, **fields) -> None:
        entry = {"event": event, "session_id": self.session_id,
                 "ts": time.time(), **fields}
        self.action_log.append(entry)
        if len(self.action_log) > 200:
            self.action_log = self.action_log[-200:]
        logger.info(json.dumps(entry))

    def propose(self, kind: str, summary: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        proposal = {
            "proposal_id": uuid.uuid4().hex[:12],
            "kind": kind,  # "navigate" | "submit"
            "summary": summary,
            "payload": payload,
            "created_at": time.time(),
        }
        self.pending = proposal
        return proposal

    def take_proposal(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        """Pop the pending proposal iff id matches and it hasn't expired."""
        prop = self.pending
        if prop is None or prop.get("proposal_id") != proposal_id:
            return None
        if time.time() - prop.get("created_at", 0) > PROPOSAL_TTL_SECONDS:
            self.pending = None
            return None
        self.pending = None
        return prop


class RobotsCache:
    """Minimal robots.txt handling: honor Disallow prefixes for the path.

    Deliberately lite (User-agent groups collapsed to `*`): this is an
    accessibility assistant, not a crawler fleet, and the check runs per
    session host. Unfetchable robots => fail CLOSED for acts (refuse), while
    read-only inspect may proceed (logged) so one DNS blip can't brick help.
    """

    def __init__(self, ttl_seconds: float = 3600.0,
                 fetch: Optional[Callable] = None):
        self.ttl = ttl_seconds
        self._cache: Dict[str, Any] = {}
        self._fetch = fetch  # injectable for offline tests

    async def _download(self, host: str, scheme: str) -> Optional[str]:
        if self._fetch is not None:
            return await self._fetch(host, scheme)
        import httpx
        try:
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(f"{scheme}://{host}/robots.txt")
                if resp.status_code != 200:
                    return None
                return resp.text
        except Exception:
            return None

    @staticmethod
    def _parse_disallows(text: str) -> List[str]:
        """Collect Disallow prefixes from `*` groups (plus any group: the
        simple, conservative reading - if ANY group disallows our path and we
        can't tell groups apart reliably, the path is treated as disallowed
        only when the `*` group says so; named groups are ignored)."""
        disallows: List[str] = []
        in_star = False
        seen_ua = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            field, _, value = line.partition(":")
            field, value = field.strip().lower(), value.strip()
            if field == "user-agent":
                seen_ua = True
                in_star = (value == "*")
            elif field == "disallow" and ((in_star) or not seen_ua) and value:
                if value not in disallows:
                    disallows.append(value)
        return disallows

    async def allowed(self, url: str) -> tuple[bool, str]:
        """(allowed, reason). data:/file: URLs have no host: always allowed."""
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return True, "no host to check"
        host = parsed.hostname.lower()
        scheme = parsed.scheme
        now = time.time()
        cached = self._cache.get(host)
        if cached and now - cached[1] < self.ttl:
            disallows = cached[0]
        else:
            text = await self._download(host, scheme)
            if text is None:
                return False, f"robots.txt unfetchable for {host} - refusing to act"
            disallows = self._parse_disallows(text)
            self._cache[host] = (disallows, now)
        path = parsed.path or "/"
        for prefix in disallows:
            if path.startswith(prefix):
                return False, f"disallowed by robots.txt ({prefix})"
        return True, "allowed by robots.txt"


class SessionManager:
    """Registry of live sessions with idle sweep and capacity cap."""

    def __init__(self, driver_factory=None,
                 ttl_seconds: float = 600.0, max_sessions: int = 20,
                 nav_per_hour: int = 30, submits_per_hour: int = 5,
                 robots: Optional[RobotsCache] = None):
        if ttl_seconds is None:
            ttl_seconds = _env_float("SESSION_TTL_SECONDS", 600.0)
        self.ttl = ttl_seconds
        self.max_sessions = max_sessions
        self.nav_per_hour = nav_per_hour
        self.submits_per_hour = submits_per_hour
        self.robots = robots or RobotsCache()
        self._sessions: Dict[str, LiveSession] = {}
        self._lock = asyncio.Lock()
        if driver_factory is None:
            from app.tools.driver import Driver
            driver_factory = Driver
        self._driver_factory = driver_factory

    def get(self, session_id: str) -> Optional[LiveSession]:
        return self._sessions.get(session_id)

    async def open(self, session_id: str) -> LiveSession:
        """Get or create the session (browser starts lazily on first navigate)."""
        async with self._lock:
            existing = self._sessions.get(session_id)
            if existing is not None:
                existing.touch()
                return existing
            if len(self._sessions) >= self.max_sessions:
                oldest = min(self._sessions.values(), key=lambda s: s.last_active)
                await self._close_locked(oldest.session_id, reason="capacity-evict")
            session = LiveSession(
                session_id, self._driver_factory(),
                nav_per_hour=self.nav_per_hour, submits_per_hour=self.submits_per_hour)
            self._sessions[session_id] = session
            session.log("session_open")
            return session

    async def close(self, session_id: str, reason: str = "explicit") -> bool:
        async with self._lock:
            return await self._close_locked(session_id, reason)

    async def _close_locked(self, session_id: str, reason: str) -> bool:
        session = self._sessions.pop(session_id, None)
        if session is None:
            return False
        if session.monitor is not None and session.monitor.enabled:
            # Monitoring must never outlive its session - and its unsent
            # descriptions are discarded, not delivered posthumously.
            session.monitor.stop(reason=f"session-closed:{reason}")
        try:
            await session.driver.stop()
        except Exception as e:
            logger.warning(json.dumps({"event": "session_close_driver_error",
                                       "session_id": session_id, "error": str(e)[:150]}))
        session.log("session_close", reason=reason)
        return True

    async def sweep_once(self, now: Optional[float] = None) -> List[str]:
        """Close sessions idle past TTL. Returns closed ids (test seam)."""
        now = time.time() if now is None else now
        async with self._lock:
            idle = [sid for sid, s in self._sessions.items()
                    if now - s.last_active > self.ttl]
            closed = []
            for sid in idle:
                if await self._close_locked(sid, reason="idle-timeout"):
                    closed.append(sid)
            return closed

    async def sweep_loop(self, interval_seconds: float = 60.0) -> None:
        """Background task: run from the app lifespan, cancelled on shutdown."""
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                closed = await self.sweep_once()
                for sid in closed:
                    logger.info(json.dumps({"event": "session_idle_timeout",
                                           "session_id": sid}))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(json.dumps({"event": "sweep_error",
                                          "error": str(e)[:150]}))

    def active_ids(self) -> List[str]:
        return list(self._sessions.keys())

    def all_sessions(self) -> List[LiveSession]:
        """Snapshot of live sessions (monitor loop iterates this)."""
        return list(self._sessions.values())
