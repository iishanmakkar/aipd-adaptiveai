"""Real-time page monitoring for live sessions (Round 9).

Watches ONE live browser-agent page (the same LiveSession the chat already
drives - no second session concept) and narrates meaningful changes through
the NIM vision model. Consent is structural: a PageMonitor only exists after
an explicit start call, never at page load, and every stop path is one action.

Cost/rate discipline is the correctness core, in this order:

1. DOM-mutation signal (cheap, local): one page.evaluate per poll reads a
   MutationObserver counter plus innerText. If the counter is unchanged and
   the text is unchanged, NOTHING else happens - no screenshot, no model call.
   Cursor movement and a blinking caret are not DOM mutations, so they cannot
   trigger anything by construction.
2. Stability debounce: text that keeps changing (typing bursts, animations)
   waits until it has been stable for STABLE_SECONDS before it can fire.
3. Minor-change filter: a text delta below MIN_CHANGE_RATIO vs the last
   described text is cosmetic (a ticking clock digit, a flicker) - ignored.
4. Interruption quiet window: user input sets quiet_until; during it change
   detection still counts but narration is deferred, never spoken over the
   user. The newest deferred state wins (coalesced).
5. Hard rate ceiling: at most one NIM vision call per MIN_CALL_SECONDS per
   session no matter how much the page churns; deferred changes coalesce into
   the next allowed call.

Frames are never stored: the screenshot exists only in memory for the duration
of the NIM request (same endpoint + model as the existing VLMAnalysisTool),
and after narration only the short text description and the counters remain
(in a bounded deque; everything is discarded when the session closes).
"""
from __future__ import annotations

import asyncio
import difflib
import json
import logging
import os
import re
import time
from typing import Any, Callable, Deque, Dict, List, Optional
from collections import deque

logger = logging.getLogger("adaptiveai.monitor")

WS_RE = re.compile(r"\s+")
NO_MEANINGFUL_CHANGE = "no meaningful change"


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


class PageMonitor:
    """Monitor state + gating pipeline for one live session."""

    def __init__(self, session_id: str, driver,
                 describe_fn: Optional[Callable] = None, **overrides: float):
        self.session_id = session_id
        self.driver = driver
        self.describe_fn = describe_fn  # injectable for offline tests
        self.started_at = time.time()
        self.last_poll: float = 0.0

        # Tunables (env-overridable so proofs can shorten windows without
        # changing code; constructor overrides for offline tests).
        self.poll_seconds = _env_float("MONITOR_POLL_SECONDS", 1.5)
        self.stable_seconds = _env_float("MONITOR_STABLE_SECONDS", 2.0)
        self.max_pending_seconds = _env_float("MONITOR_MAX_PENDING_SECONDS", 6.0)
        self.min_call_seconds = _env_float("MONITOR_MIN_CALL_SECONDS", 20.0)
        self.quiet_seconds = _env_float("MONITOR_QUIET_SECONDS", 15.0)
        self.max_duration_seconds = _env_float("MONITOR_MAX_DURATION_SECONDS", 1800.0)
        self.min_change_ratio = _env_float("MONITOR_MIN_CHANGE_RATIO", 0.98)
        self.max_events = _env_int("MONITOR_MAX_EVENTS", 50)
        for key, value in overrides.items():
            if not hasattr(self, key) or not isinstance(getattr(self, key), (int, float)):
                raise TypeError(f"unknown monitor tunable: {key!r}")
            setattr(self, key, value)

        # Gating state.
        self.last_mutations: Optional[int] = None
        self.last_text: str = ""
        self.stable_text: str = ""
        self.described_text: str = ""
        self.baseline_set = False
        self.pending_since: Optional[float] = None
        self.pending_text: str = ""
        self.deferred_text: Optional[str] = None
        self.last_call_ts: float = 0.0
        self.quiet_until: float = 0.0

        self.enabled = True
        self.events: Deque[Dict[str, Any]] = deque(maxlen=self.max_events)
        self._event_seq = 0
        self._delivery_cursor = 0  # next event id the backend has not pulled

        # Measured counters (the proof numbers for section B).
        self.counters: Dict[str, int] = {
            "polls": 0, "polls_idle": 0, "baseline_polls": 0, "raw_activity": 0,
            "changes_detected": 0, "minor_ignored": 0, "forced_evaluations": 0,
            "deferred_by_quiet": 0, "rate_blocked": 0,
            "nim_calls": 0, "narrations": 0, "errors": 0,
        }

    # ---- lifecycle -------------------------------------------------------

    def stop(self, reason: str) -> None:
        self.enabled = False
        self.events.clear()  # privacy: unsent descriptions die with the session
        logger.info(json.dumps({"event": "monitor_stopped", "session_id": self.session_id,
                                "reason": reason, "nim_calls": self.counters["nim_calls"]}))

    def interrupt(self) -> None:
        """User input has priority: hold narrations for a quiet window."""
        self.quiet_until = time.time() + self.quiet_seconds
        logger.info(json.dumps({"event": "monitor_interrupted",
                                "session_id": self.session_id,
                                "quiet_until": self.quiet_until}))

    # ---- signal pipeline ---------------------------------------------------

    @staticmethod
    def _normalize(text: str) -> str:
        return WS_RE.sub(" ", (text or "")).strip()

    def _meaningful(self, new_text: str) -> bool:
        if not self.described_text:
            return True  # first description of the session
        sm = difflib.SequenceMatcher(None, self.described_text, new_text)
        return sm.quick_ratio() < self.min_change_ratio

    async def poll_once(self, now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        """Run one poll cycle. Returns a narration event when a NIM call fired.

        Never raises for page errors - counts them and keeps the loop alive.
        """
        if not self.enabled:
            return None
        now = time.time() if now is None else now
        # Hard lifetime cap: monitoring never outlives MAX_DURATION even if
        # the page keeps changing.
        if now - self.started_at > self.max_duration_seconds:
            self.stop(reason="max-duration")
            return None
        self.counters["polls"] += 1
        self.last_poll = now
        try:
            signal = await self.driver.monitor_signal()
        except Exception:
            self.counters["errors"] += 1
            return None

        mutations = signal.get("mutations")
        text = self._normalize(str(signal.get("text", "")))[:6000]

        if not self.baseline_set:
            # First look at a page that was already open when the user opted
            # in: record it as the known state. It is not a "change" and must
            # not narrate (the user has already been told what is on screen).
            self.baseline_set = True
            self.last_mutations = mutations
            self.last_text = self.stable_text = self.described_text = text
            self.counters["baseline_polls"] += 1
            return None

        self.last_mutations = mutations
        if text != self.last_text:
            # Something changed. Wait for stability before judging it - but
            # never wait forever: a page that keeps changing (live dashboard,
            # ticker) must still be evaluated, or it would never narrate.
            # Forcing evaluation hands the change to the same gates below
            # (minor filter, quiet window, hard rate ceiling), which is what
            # caps the call rate on churning pages.
            forced = (self.pending_since is not None
                      and now - self.pending_since >= self.max_pending_seconds)
            self.last_text = text
            self.counters["raw_activity"] += 1
            if forced:
                self.counters["forced_evaluations"] += 1
                self.pending_since = None
                self.stable_text = text
                event = await self._gate_and_describe(text, now)
                if event is not None:
                    return event
            elif self.pending_since is None:
                # Mark when this unstable episode BEGAN (not the latest
                # change): a page that changes every poll must eventually be
                # evaluated instead of pending forever.
                self.pending_since = now
                self.pending_text = text
        elif (self.pending_since is not None
              and now - self.pending_since >= self.stable_seconds):
            # Unchanged since the poll that saw the change, and stable past
            # the debounce window: this is a settled, real change.
            self.counters["changes_detected"] += 1
            self.stable_text = text
            self.pending_since = None
            self.pending_text = ""
            event = await self._gate_and_describe(text, now)
            if event is not None:
                return event
        else:
            self.counters["polls_idle"] += 1
        return await self._fire_deferred(now)

    async def _gate_and_describe(self, text: str, now: float) -> Optional[Dict[str, Any]]:
        """Apply the minor/quiet/ceiling gates; describe or defer."""
        if not self._meaningful(text):
            self.counters["minor_ignored"] += 1
            return None
        if now < self.quiet_until:
            self.counters["deferred_by_quiet"] += 1
            self.deferred_text = text  # newest state wins
            return None
        if now - self.last_call_ts < self.min_call_seconds:
            self.counters["rate_blocked"] += 1
            self.deferred_text = text
            return None
        return await self._describe(text, now, trigger="change")

    async def _fire_deferred(self, now: float) -> Optional[Dict[str, Any]]:
        """A rate-blocked or user-deferred change fires once gates allow it."""
        if self.deferred_text is None or not self.enabled:
            return None
        if now < self.quiet_until:
            return None
        if now - self.last_call_ts < self.min_call_seconds:
            return None
        text, self.deferred_text = self.deferred_text, None
        self.counters["changes_detected"] += 1
        return await self._describe(text, now, trigger="deferred")

    async def _describe(self, text: str, now: float,
                        trigger: str = "change") -> Optional[Dict[str, Any]]:
        """Call the NIM vision model (same endpoint as the existing VLM tool),
        delta-aware: the prompt carries the previous description so the model
        reports what changed, not the whole page from scratch."""
        self.last_call_ts = now
        self.counters["nim_calls"] += 1
        try:
            if self.describe_fn is not None:
                raw = await self.describe_fn(text, self.described_text)
            else:
                raw = await self._nim_describe(text)
        except Exception as e:
            self.counters["errors"] += 1
            self.last_call_ts = 0.0  # a failed call must not consume the ceiling
            logger.warning(json.dumps({"event": "monitor_nim_error",
                                       "session_id": self.session_id,
                                       "error": str(e)[:150]}))
            return None
        if not raw or self._normalize(raw).lower() == NO_MEANINGFUL_CHANGE:
            self.described_text = text
            return None
        self.described_text = text
        self._event_seq += 1
        event = {
            "id": self._event_seq, "ts": now, "trigger": trigger,
            "raw_description": raw, "session_id": self.session_id,
        }
        self.events.append(event)
        self.counters["narrations"] += 1
        logger.info(json.dumps({"event": "monitor_narration",
                                "session_id": self.session_id, "id": event["id"],
                                "nim_calls": self.counters["nim_calls"]}))
        return event

    async def _nim_describe(self, text: str) -> str:
        from app.tools.base import VLMAnalysisTool
        prev = (self.described_text or "this is the first look at the page")[:800]
        prompt = (
            "You are a screen-change narrator for a visually impaired user who "
            "is filling a form in a browser. This page is being watched "
            "continuously. Previous description: \"" + prev + "\". "
            "The page's visible text has just changed. New visible text: \""
            + text[:2500] + "\". "
            "Describe ONLY what changed and matters to the user (an error "
            "appearing, a new field or message, a page finishing loading, a "
            "confirmation). 1-3 short sentences. Do not re-describe the whole "
            "page. If nothing in the new text is meaningfully different, reply "
            "exactly: no meaningful change"
        )
        tool = VLMAnalysisTool(self.driver)
        result = await tool.execute("describe", prompt=prompt)
        if result.get("status") != "completed":
            raise RuntimeError(result.get("detail", "vlm call failed"))
        return str(result.get("details", "")).strip()

    # ---- delivery ---------------------------------------------------------

    def narrations_since(self, since_id: int) -> List[Dict[str, Any]]:
        """Undelivered events after since_id (backend pulls, then marks)."""
        return [e for e in self.events if e["id"] > since_id]

    def mark_delivered(self, last_id: int) -> None:
        self._delivery_cursor = max(self._delivery_cursor, last_id)

    def stats(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "enabled": self.enabled,
            "started_at": self.started_at,
            "quiet_until": self.quiet_until,
            "undelivered": sum(1 for e in self.events if e["id"] > self._delivery_cursor),
            "counters": dict(self.counters),
        }


class MonitorLoop:
    """Single background loop driving all enabled monitors, app-lifespan owned."""

    def __init__(self, get_sessions: Callable[[], List[Any]]):
        self.get_sessions = get_sessions

    async def run(self, interval: float = 0.5) -> None:
        last_beat = 0.0
        while True:
            await asyncio.sleep(interval)
            now = time.time()
            if now - last_beat >= 10.0:
                last_beat = now
                monitored = [s.session_id for s in self.get_sessions()
                             if getattr(s, "monitor", None) is not None
                             and s.monitor.enabled]
                logger.info(json.dumps({"event": "monitor_loop_beat",
                                        "sessions": len(self.get_sessions()),
                                        "monitored": monitored}))
            for session in self.get_sessions():
                monitor = getattr(session, "monitor", None)
                if monitor is None or not monitor.enabled:
                    continue
                if now - monitor.last_poll < monitor.poll_seconds:
                    continue
                if session.lock.locked():
                    logger.info(json.dumps({
                        "event": "monitor_skip_locked",
                        "session_id": session.session_id}))
                    continue  # a user action holds the page; never fight it
                try:
                    t0 = time.time()
                    async with session.lock:
                        if not monitor.enabled:
                            continue
                        await monitor.poll_once()
                    waited = time.time() - t0
                    if waited > 2.0:
                        logger.info(json.dumps({
                            "event": "monitor_poll_slow", "session_id": session.session_id,
                            "seconds": round(waited, 1)}))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(json.dumps({"event": "monitor_poll_error",
                                               "session_id": session.session_id,
                                               "error": str(e)[:150]}))
