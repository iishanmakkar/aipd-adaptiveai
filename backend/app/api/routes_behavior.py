"""Behavior-event intake, WIRED into the adaptive policy (B2).

The frontend's `useBehaviorTracking` hook POSTs replay/skip/listen signals.
Unlike the first version (accepted + only logged), this endpoint:
  - requires the session to exist AND belong to the caller (same ownership
    check as /api/query - nobody can poison another user's adaptation),
  - persists per-session counts in behavior_signals (upsert),
  - returns the counts so the UI can observe what the policy will see.

The policy engine consumes the counts as its LOWEST-priority rule and only
while the user keeps default preferences - any explicit preference wins.
"""
import logging
from typing import Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.api.deps import parse_session_uuid
from app.database import get_db, is_db_available
from app.models.behavior import BehaviorSignal
from app.models.session import Session

logger = logging.getLogger("adaptiveai.behavior")

router = APIRouter(prefix="/api", tags=["behavior"])


class BehaviorEvent(BaseModel):
    session_id: str = Field(..., min_length=1)
    event_type: Literal["replay", "skip", "listen"]
    listen_time: Optional[float] = Field(default=None, ge=0, le=86400)


@router.post("/behavior-event")
async def record_behavior_event(
    event: BehaviorEvent,
    request: Request,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running")
    if current_user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    session_uuid: UUID = parse_session_uuid(event.session_id)
    try:
        result = await db.execute(
            select(Session).where(Session.id == session_uuid, Session.user_id == current_user.id)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Session not found - create one via POST /api/session first")
    # Atomic increment-or-insert: a single statement, so two concurrent first
    # events (or two increments) cannot lose one to a read-modify-write race.
    # The old select-then-insert + IntegrityError-retry path is gone.
    if event.event_type == "replay":
        inc = {"replay_count": BehaviorSignal.replay_count + 1}
    elif event.event_type == "skip":
        inc = {"skip_count": BehaviorSignal.skip_count + 1}
    else:
        inc = {"listen_count": BehaviorSignal.listen_count + 1,
               "listen_seconds": (BehaviorSignal.listen_seconds
                                  + (event.listen_time or 0.0))}
    stmt = (
        pg_insert(BehaviorSignal)
        .values(session_id=session_uuid, replay_count=0, skip_count=0,
                listen_count=0, listen_seconds=0.0)
        .on_conflict_do_update(index_elements=["session_id"], set_=inc)
        .returning(BehaviorSignal)
    )
    try:
        result = await db.execute(stmt)
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=404, detail="Session not found - create one via POST /api/session first")
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    signals = result.scalar_one_or_none()
    if signals is None:  # unreachable on Postgres (RETURNING always yields the row)
        raise HTTPException(status_code=503, detail="Behavior signal row could not be created")
    logger.info(
        "behavior_event session_id=%s event=%s replay=%d skip=%d request_id=%s",
        event.session_id, event.event_type,
        signals.replay_count, signals.skip_count,
        getattr(request.state, "request_id", "-"),
    )
    return {"status": "accepted", "replay_count": signals.replay_count,
            "skip_count": signals.skip_count}
