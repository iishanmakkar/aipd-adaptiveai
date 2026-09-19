"""Behavior-event intake (FEATURE_PLAN 1.2, first step).

The frontend's `useBehaviorTracking` hook POSTs replay/skip/listen signals here.
This endpoint validates the event and emits a structured log line so the signals
are observable today; the policy engine does NOT consume them yet (that is the
follow-up: aggregate per-session signals into verbosity/speech-rate adaptation).
Accepting-and-logging is stated, not oversold: the response is `accepted`, and
nothing is persisted.
"""
import logging
from typing import Literal, Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

logger = logging.getLogger("adaptiveai.behavior")

router = APIRouter(prefix="/api", tags=["behavior"])


class BehaviorEvent(BaseModel):
    session_id: str = Field(..., min_length=1)
    event_type: Literal["replay", "skip", "listen"]
    listen_time: Optional[float] = Field(default=None, ge=0)


@router.post("/behavior-event")
async def record_behavior_event(event: BehaviorEvent, request: Request):
    logger.info(
        "behavior_event session_id=%s event=%s listen_time=%s request_id=%s",
        event.session_id,
        event.event_type,
        event.listen_time,
        getattr(request.state, "request_id", "-"),
    )
    return {"status": "accepted"}
