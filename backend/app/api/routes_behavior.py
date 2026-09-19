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
    listen_time: Optional[float] = Field(default=None, ge=0)


@router.post("/behavior-event")
async def record_behavior_event(
    event: BehaviorEvent,
    request: Request,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running")
    session_uuid: UUID = parse_session_uuid(event.session_id)
    try:
        result = await db.execute(
            select(Session).where(Session.id == session_uuid, Session.user_id == current_user.id)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Session not found - create one via POST /api/session first")
    try:
        result = await db.execute(
            select(BehaviorSignal).where(BehaviorSignal.session_id == session_uuid)
        )
        signals = result.scalar_one_or_none()
        if signals is None:
            # Explicit zeros: SQLAlchemy column/server defaults only apply at
            # INSERT, so a fresh object holds None until flushed - and None + 1
            # would 503 the very first event of every session.
            signals = BehaviorSignal(
                session_id=session_uuid, replay_count=0, skip_count=0,
                listen_count=0, listen_seconds=0.0,
            )
            db.add(signals)
        if event.event_type == "replay":
            signals.replay_count += 1
        elif event.event_type == "skip":
            signals.skip_count += 1
        else:
            signals.listen_count += 1
            signals.listen_seconds += event.listen_time or 0.0
        await db.commit()
        await db.refresh(signals)
    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    logger.info(
        "behavior_event session_id=%s event=%s replay=%d skip=%d request_id=%s",
        event.session_id, event.event_type,
        signals.replay_count, signals.skip_count,
        getattr(request.state, "request_id", "-"),
    )
    return {"status": "accepted", "replay_count": signals.replay_count,
            "skip_count": signals.skip_count}
