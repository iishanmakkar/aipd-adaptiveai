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
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, HTTPException
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
from app.services.policy_engine import adjust_response

logger = logging.getLogger("adaptiveai.monitor")

router = APIRouter(prefix="/api", tags=["monitor"])

# Per-chat delivery cursor into browser-agent's narration event ids, plus
# monitor liveness, in memory like the held-proposal store: a backend restart
# forgets the cursor (events may be re-pulled at-least-once) but can never
# restart monitoring on its own - the safe default.
_monitor_state: dict[str, dict] = {}

NARRATION_TTL_SECONDS = 3600.0


class MonitorRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


def _cursor(chat_id: str) -> dict:
    return _monitor_state.setdefault(chat_id, {"since": 0, "active": False})


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


def _relay_error(exc: Exception, action: str) -> HTTPException:
    """Map a browser-agent failure to an honest user-facing error."""
    detail = getattr(exc, "detail", None) or str(exc)[:200]
    status = getattr(exc, "status_code", None)
    if status in (404, 409):
        return HTTPException(status_code=status, detail=detail)
    return HTTPException(status_code=502,
                         detail=f"Monitoring {action} failed: {detail}")


@router.post("/monitor/start")
async def monitor_start(req: MonitorRequest,
                        current_user: User = Depends(get_current_user_optional),
                        db: AsyncSession = Depends(get_db)):
    await _own_session(db, req.session_id, current_user)
    import app.api.routes_query as rq
    request_id = f"monitor-start-{req.session_id[:8]}-{int(time.time())}"
    try:
        result = await browser_monitor_start(req.session_id, "voice-or-control",
                                             request_id)
    except Exception as e:
        raise _relay_error(e, "start")
    _cursor(req.session_id)["active"] = True
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
        # A 409 (nothing active) is fine for a kill switch: the requested
        # end-state - monitoring off - already holds.
        status = getattr(e, "status_code", None)
        if status == 409:
            _cursor(req.session_id)["active"] = False
            return {"active": False, "status": "already_stopped"}
        raise _relay_error(e, "stop")
    _cursor(req.session_id)["active"] = False
    logger.info("monitor_stopped session=%s user=%s nim_calls=%s",
                req.session_id, current_user.id,
                result.get("stats", {}).get("counters", {}).get("nim_calls"))
    return {"active": False, "status": "stopped",
            "stats": result.get("stats", {})}


@router.get("/monitor/status")
async def monitor_status(session_id: str,
                         current_user: User = Depends(get_current_user_optional),
                         db: AsyncSession = Depends(get_db)):
    await _own_session(db, session_id, current_user)
    try:
        result = await browser_monitor_status(session_id)
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 404:
            raise HTTPException(status_code=404, detail="No live page session")
        raise _relay_error(e, "status")
    return {"active": result.get("active", False), "stats": result.get("stats", {})}


@router.get("/monitor/events")
async def monitor_events(session_id: str, since: int | None = None,
                         current_user: User = Depends(get_current_user_optional),
                         db: AsyncSession = Depends(get_db)):
    """Poll new narrations. Raw descriptions from browser-agent are policy-
    adapted (same engine as chat), persisted as assistant messages, and
    returned for the frontend to announce + speak. The delivery cursor is
    owned SERVER-side: a client passing a stale `since` cannot rewind it and
    re-persist the same narration twice (found live: duplicate messages)."""
    await _own_session(db, session_id, current_user)
    state = _cursor(session_id)
    cursor = state["since"]
    request_id = f"monitor-events-{session_id[:8]}-{int(time.time())}"
    session = await _own_session(db, session_id, current_user)
    try:
        pull = await browser_monitor_narrations(session_id, cursor, request_id)
    except Exception as e:
        status = getattr(e, "status_code", None)
        if status == 404:
            state["active"] = False
            return {"active": False, "narrations": [], "cursor": cursor,
                    "stats": {}}
        if status == 409:
            state["active"] = False
            return {"active": False, "narrations": [], "cursor": cursor,
                    "stats": {}}
        raise _relay_error(e, "narration pull")

    if not pull.get("active", False):
        state["active"] = False

    # Load user prefs + behavior once per poll (same inputs chat answers use).
    prefs_result = await db.execute(
        select(Preference).where(Preference.user_id == current_user.id))
    prefs = prefs_result.scalar_one_or_none()
    uuid_session = parse_session_uuid(session_id)
    sig_result = await db.execute(
        select(BehaviorSignal).where(BehaviorSignal.session_id == uuid_session))
    signals = sig_result.scalar_one_or_none()
    session_context = {
        "message_count": 0,
        "replay_count": signals.replay_count if signals else 0,
        "skip_count": signals.skip_count if signals else 0,
    }

    narrations = []
    for event in pull.get("events", []):
        raw = str(event.get("raw_description", ""))[:2000]
        try:
            adapted = await adjust_response(
                raw_answer=raw, user_prefs=prefs,
                clarifying_count=0, session_context=session_context,
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
        state["since"] = max(state["since"], int(event.get("id", 0)))
        narrations.append({"id": event.get("id"), "ts": event.get("ts"),
                           "text": adapted})
    if narrations:
        await db.commit()
    return {"active": pull.get("active", False), "narrations": narrations,
            "cursor": state["since"], "stats": pull.get("stats", {})}
