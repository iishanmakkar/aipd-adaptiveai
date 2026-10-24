"""Round 9: real-time page monitoring - consent, narrations, kill switch.

The monitor itself lives in browser-agent on the chat session's LIVE page
(same LiveSession the chat drives - no second session concept). This router
is the only user-facing door to it, and every endpoint:

- requires an authenticated user whose chat session it is (ownership check,
  same as /api/query - monitoring is per-user, never per-anonymous-visitor);
- relays the user's explicit action (voice command / button / shortcut) to
  browser-agent; monitoring never starts from anything but this explicit path;
- pulls new raw narrations from browser-agent, runs them through the SAME
  adaptive policy engine as chat answers (disability profile, verbosity),
  persists them as assistant messages (so follow-up chat questions share
  context with what was narrated), and returns the adapted text for TTS.

Security shape: the background stream here makes NO outbound calls of its own
beyond the internal browser-agent pull (per user poll, request-id traced);
the only external traffic is browser-agent -> NIM, bounded by the monitor's
hard rate ceiling, max-duration auto-stop, and the session idle sweep.
"""
import asyncio
import logging
import time
from uuid import UUID

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.api.deps import parse_session_uuid
from app.database import get_db, is_db_available
from app.models.user import User
from app.models.session import Session
from app.models.message import Message, MessageRole
from app.models.preference import Preference
from app.models.behavior import BehaviorSignal
from app.services.clients import (
    browser_monitor_start,
    browser_monitor_stop,
    browser_monitor_status,
    browser_monitor_narrations,
)
from app.services.policy_engine import adjust_response, count_clarifying_questions, get_message_count

logger = logging.getLogger("adaptiveai.monitor")

router = APIRouter(prefix="/api", tags=["monitor"])

# Per-chat delivery cursor into browser-agent's narration event ids, plus
# monitor liveness. Store-backed (Redis when set, in-memory TTL otherwise)
# so a backend restart resumes delivery instead of re-pulling everything
# at-least-once. Read-modify-write only - never mutate a fetched dict.
from app.services.session_memory import monitor_store, SharedDict

NARRATION_TTL_SECONDS = 3600.0

_monitor_state: SharedDict = SharedDict(monitor_store, default_ttl=NARRATION_TTL_SECONDS)


# Per-chat delivery locks: two concurrent /monitor/events polls for one chat
# would both read `since`, both pull the same events, both pass the dedup
# SELECT (neither has committed yet) and both persist - duplicate narrations.
# The lock serializes pull+persist+cursor per chat. Bounded with LRU sweep so
# the registry cannot grow without bound over the process lifetime.
_monitor_locks: dict[str, asyncio.Lock] = {}
_monitor_locks_used: dict[str, float] = {}


def _monitor_lock(chat_id: str) -> asyncio.Lock:
    lock = _monitor_locks.get(chat_id)
    if lock is None:
        if len(_monitor_locks) > 2000:
            for old in sorted(_monitor_locks_used,
                              key=_monitor_locks_used.__getitem__)[:500]:
                held = _monitor_locks.get(old)
                # Evicting a lock that is CURRENTLY HELD reopens the exact
                # duplicate-narration race this registry exists to prevent:
                # a poll can hold its lock across a 120s browser pull, and
                # its used-stamp goes stale while it waits. Locked entries
                # stay until they are free.
                if held is not None and held.locked():
                    continue
                _monitor_locks.pop(old, None)
                _monitor_locks_used.pop(old, None)
        lock = asyncio.Lock()
        _monitor_locks[chat_id] = lock
    _monitor_locks_used[chat_id] = time.time()
    return lock


def _translate_stats(stats, active: bool) -> dict:
    """Browser-agent stats() speaks `enabled`; the API contract is `active`."""
    s = dict(stats or {})
    s["active"] = bool(s.pop("enabled", s.get("active", active)))
    return s


class MonitorRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


def _cursor(chat_id: str) -> dict:
    state = _monitor_state.get(chat_id)
    if state is None:
        state = {"since": 0, "active": False, "created_at": time.time()}
        _monitor_state[chat_id] = state
    return state


def _save_cursor(chat_id: str, state: dict) -> None:
    # Preserve absolute expiry: a rewrite must not refresh the full TTL.
    _monitor_state.save_preserving_ttl(chat_id, state)


async def _own_session(db: AsyncSession, session_id: str,
                       user: User) -> Session:
    """404 unless the chat session exists AND belongs to this user."""
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available")
    session_uuid = parse_session_uuid(session_id)
    result = await db.execute(
        select(Session).where(Session.id == session_uuid,
                              Session.user_id == user.id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


def _browser_status(exc: Exception) -> int | None:
    """httpx raises HTTPStatusError (status at exc.response.status_code)."""
    if isinstance(exc, httpx.HTTPStatusError) and exc.response is not None:
        return exc.response.status_code
    return getattr(exc, "status_code", None)


def _relay_error(exc: Exception, action: str) -> HTTPException:
    """Map a browser-agent failure to an honest user-facing error."""
    detail = getattr(exc, "detail", None) or str(exc)[:200]
    status = _browser_status(exc)
    if status in (404, 409):
        return HTTPException(status_code=status, detail=detail)
    return HTTPException(status_code=502,
                         detail=f"Monitoring {action} failed: {detail}")


@router.post("/monitor/start")
async def monitor_start(req: MonitorRequest,
                        current_user: User = Depends(get_current_user_optional),
                        db: AsyncSession = Depends(get_db)):
    await _own_session(db, req.session_id, current_user)
    request_id = f"monitor-start-{req.session_id[:8]}-{int(time.time())}"
    try:
        result = await browser_monitor_start(req.session_id, "voice-or-control",
                                             request_id)
    except Exception as e:
        # The most common first-click failure by far: nothing is open to watch.
        # Relay that as actionable guidance (what to do next) instead of the
        # browser-agent's bare "No live page session", which read as "broken".
        if _browser_status(e) == 404:
            raise HTTPException(
                status_code=404,
                detail=("Nothing is open to watch yet. First ask me to open a "
                        "website or form — paste its link in the chat — then "
                        "press Watch my screen."))
        raise _relay_error(e, "start")
    _start_state = _cursor(req.session_id)
    _start_state["active"] = True
    # Narration ids restart at 1 for every new browser-side monitor run (a new
    # PageMonitor per start). A cursor surviving from a previous run would
    # filter every new event server-side (id <= since) and the user would hear
    # silence. Reset to 0; already-persisted events are still skipped by the
    # stored-id dedup in /monitor/events.
    _start_state["since"] = 0
    _save_cursor(req.session_id, _start_state)
    logger.info("monitor_started session=%s user=%s", req.session_id,
                current_user.id)
    return {"active": True, "status": result.get("status", "started"),
            "message": ("Watching the live page. Every meaningful change will "
                        "be narrated here. Stop anytime with the button, "
                        "Alt+W, or by saying 'stop watching my screen'.")}


@router.post("/monitor/stop")
async def monitor_stop(req: MonitorRequest,
                       current_user: User = Depends(get_current_user_optional),
                       db: AsyncSession = Depends(get_db)):
    await _own_session(db, req.session_id, current_user)
    request_id = f"monitor-stop-{req.session_id[:8]}-{int(time.time())}"
    try:
        result = await browser_monitor_stop(req.session_id, request_id)
    except Exception as e:
        # 409 (nothing active) is fine for a kill switch: the requested
        # end-state - monitoring off - already holds. 404 (no live page
        # session at all) means the same thing from the user's side - there
        # is nothing to stop - so it clears local state too instead of
        # erroring while the UI still shows "watching".
        status = _browser_status(e)
        if status in (404, 409):
            _stop_state = _cursor(req.session_id)
            _stop_state["active"] = False
            _save_cursor(req.session_id, _stop_state)
            return {"active": False, "status": "already_stopped"}
        raise _relay_error(e, "stop")
    _stopped_state = _cursor(req.session_id)
    _stopped_state["active"] = False
    _save_cursor(req.session_id, _stopped_state)
    logger.info("monitor_stopped session=%s user=%s nim_calls=%s",
                req.session_id, current_user.id,
                result.get("stats", {}).get("counters", {}).get("nim_calls"))
    return {"active": False, "status": "stopped",
            "stats": _translate_stats(result.get("stats"), False)}


@router.get("/monitor/status")
async def monitor_status(session_id: str,
                         current_user: User = Depends(get_current_user_optional),
                         db: AsyncSession = Depends(get_db)):
    await _own_session(db, session_id, current_user)
    try:
        result = await browser_monitor_status(session_id)
    except Exception as e:
        status = _browser_status(e)
        if status == 404:
            raise HTTPException(status_code=404, detail="No live page session")
        raise _relay_error(e, "status")
    return {"active": result.get("active", False), "stats": result.get("stats", {})}


@router.get("/monitor/events")
async def monitor_events(session_id: str,
                         current_user: User = Depends(get_current_user_optional),
                         db: AsyncSession = Depends(get_db)):
    """Poll new narrations. Raw descriptions from browser-agent are policy-
    adapted (same engine as chat), persisted as assistant messages, and
    returned for the frontend to announce + speak. The delivery cursor is
    owned SERVER-side (there is deliberately no client `since` param: a stale
    one could rewind delivery and re-persist the same narration twice -
    found live: duplicate messages)."""
    session = await _own_session(db, session_id, current_user)
    request_id = f"monitor-events-{session_id[:8]}-{int(time.time())}"
    # Serialized per chat (see _monitor_lock): without this, two overlapping
    # polls read the same cursor, pull the same events, both pass dedup, and
    # both persist - duplicate narrations.
    async with _monitor_lock(session_id):
        return await _pull_and_persist_events(db, session, current_user,
                                              session_id, request_id)


async def _pull_and_persist_events(db, session, current_user,
                                   session_id: str, request_id: str):
    state = _cursor(session_id)
    cursor = state["since"]
    try:
        pull = await browser_monitor_narrations(session_id, cursor, request_id)
    except Exception as e:
        status = _browser_status(e)
        if status in (404, 409):
            state["active"] = False
            _save_cursor(session_id, state)
            return {"active": False, "narrations": [], "cursor": cursor,
                    "stats": _translate_stats(None, False)}
        raise _relay_error(e, "narration pull")

    if not pull.get("active", False):
        state["active"] = False
        _save_cursor(session_id, state)

    # Load user prefs + behavior once per poll (same inputs chat answers use).
    prefs_result = await db.execute(
        select(Preference).where(Preference.user_id == current_user.id))
    prefs = prefs_result.scalar_one_or_none()
    uuid_session = parse_session_uuid(session_id)
    sig_result = await db.execute(
        select(BehaviorSignal).where(BehaviorSignal.session_id == uuid_session))
    signals = sig_result.scalar_one_or_none()
    # Real history depth and confusion level - NOT hardcoded zeros. Zeros made
    # every narration look like a first-time message, so the orientation tip
    # was appended to each one and behavior Rule 5 could never fire here.
    message_count = await get_message_count(db, uuid_session)
    clarifying_count = await count_clarifying_questions(db, uuid_session)
    session_context = {
        "message_count": message_count,
        "replay_count": signals.replay_count if signals else 0,
        "skip_count": signals.skip_count if signals else 0,
    }

    events = pull.get("events", []) or []
    seen_ids: set[int] = set()
    if events:
        # Cursor TTL expiry (or a restart without Redis) resets `since` to 0
        # and the browser re-delivers buffered events: skip ids already stored
        # or the same narration is persisted twice (the duplicate-message class
        # the server-side cursor exists to prevent).
        # Bounded to the newest 500 narration rows: a session watched for hours
        # accumulates rows forever, and this query ran on EVERY delivered
        # event - a 1 Hz poll turning into an ever-growing table scan. The
        # browser's re-delivery buffer is itself recent (cursor reset replays
        # the buffer, not history), so the newest window covers dedup.
        stored = await db.execute(
            select(Message.meta).where(Message.session_id == session.id,
                                       Message.agent_used == "browser_agent")
            .order_by(Message.created_at.desc()).limit(500))
        for row in stored.all():
            meta = row[0] if not isinstance(row, dict) else row.get("meta")
            if isinstance(meta, dict) and meta.get("kind") == "narration":
                try:
                    seen_ids.add(int(meta.get("monitor_event_id", 0)))
                except (TypeError, ValueError):
                    pass

    narrations = []
    for event in events:
        try:
            event_id = int(event.get("id", 0))
        except (TypeError, ValueError):
            event_id = 0
        if event_id in seen_ids:
            # Already persisted (stored on an earlier poll, or twice inside
            # this same pull): advance the cursor past it, persist nothing.
            if pull.get("active", False):
                state["since"] = max(state["since"], event_id)
            continue
        seen_ids.add(event_id)
        if pull.get("active", False):
            # Advance the delivery cursor only from a live monitor: persisting
            # the high-water mark of a dead run would skip that run's tail.
            state["since"] = max(state["since"], event_id)
        raw = str(event.get("raw_description", ""))[:2000]
        try:
            adapted = await adjust_response(
                raw_answer=raw, user_prefs=prefs,
                clarifying_count=clarifying_count, session_context=session_context,
                db=db, session_id=uuid_session)
        except Exception:
            adapted = raw  # narration must not die with a policy hiccup
        msg = Message(
            session_id=session.id,
            role=MessageRole.assistant,
            content=adapted,
            agent_used="browser_agent",
            meta={"kind": "narration", "trigger": event.get("trigger"),
                  "monitor_event_id": event.get("id")},
        )
        db.add(msg)
        narrations.append({"id": event.get("id"), "ts": event.get("ts"),
                           "text": adapted})
    if narrations:
        # Commit BEFORE advancing the persisted cursor: a failed commit with
        # an already-saved cursor would lose those narrations forever (never
        # stored, never re-delivered, never spoken).
        await db.commit()
    # ponytail: persist cursor whenever since advanced (dup-filtered ids too)
    _save_cursor(session_id, state)
    return {"active": pull.get("active", False), "narrations": narrations,
            "cursor": state["since"],
            "stats": _translate_stats(pull.get("stats"), pull.get("active", False))}
