"""Phase 4.2 — real-time collaboration: shared read-only session view.

Owner creates a share link (random token, 24h TTL); a helper opening
/api/share/{token} sees the same chat transcript read-only and can post
annotations that arrive as system messages (voice-announced) for the owner.
No write access to preferences, auth, or browser control.
"""
from __future__ import annotations

import secrets
import time
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user
from app.api.deps import parse_session_uuid
from app.database import get_db
from app.models.message import Message
from app.models.session import Session
from app.services.session_memory import SharedDict, share_store

router = APIRouter(prefix="/api/share", tags=["share"])

_SHARES: SharedDict = SharedDict(share_store, default_ttl=24 * 3600)
SHARE_TTL_SECONDS = 24 * 3600


class ShareCreateRequest(BaseModel):
    session_id: str = Field(..., min_length=1)


class AnnotateRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=2000)


MAX_ANNOTATIONS_PER_SHARE = 200


def _get_share(token: str) -> dict:
    share = _SHARES.get(token)
    if share is None:
        raise HTTPException(status_code=404, detail="Share link not found or expired")
    # A malformed record (missing timestamp) is treated as expired: reading
    # share["created_at"] directly would KeyError into a 500.
    if not isinstance(share, dict) or time.time() - share.get("created_at", 0) > SHARE_TTL_SECONDS:
        _SHARES.pop(token, None)
        raise HTTPException(status_code=404, detail="Share link expired")
    share.setdefault("annotations", [])
    return share


@router.post("")
async def create_share(payload: ShareCreateRequest, current_user=Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    session_id = payload.session_id
    session_uuid = parse_session_uuid(session_id)
    result = await db.execute(select(Session).where(Session.id == session_uuid, Session.user_id == current_user.id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Session not found")
    token = secrets.token_urlsafe(24)
    _SHARES[token] = {"session_id": session_id, "owner_id": str(current_user.id), "created_at": time.time(), "annotations": []}
    return {"share_token": token, "watch_url": f"/shared/{token}", "expires_in_seconds": SHARE_TTL_SECONDS}


@router.get("/{token}")
async def watch_shared(token: str, db: AsyncSession = Depends(get_db)):
    """Read-only transcript + annotations for the helper (no auth needed, token is the secret)."""
    share = _get_share(token)
    try:
        session_uuid = UUID(str(share["session_id"]))
    except ValueError:
        raise HTTPException(status_code=404, detail="Session not found")
    result = await db.execute(
        select(Message).where(Message.session_id == session_uuid).order_by(Message.created_at.asc()).limit(200)
    )
    messages = [{"role": m.role.value if hasattr(m.role, "value") else str(m.role), "content": m.content} for m in result.scalars().all()]
    return {"session_id": share["session_id"], "messages": messages, "annotations": share["annotations"], "read_only": True}


@router.post("/{token}/annotate")
async def annotate_shared(token: str, payload: AnnotateRequest, db: AsyncSession = Depends(get_db)):
    """Helper highlights something -> owner gets it as a system message (voice-announced)."""
    from app.models.message import MessageRole

    share = _get_share(token)
    text = payload.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text is required")
    if len(share["annotations"]) >= MAX_ANNOTATIONS_PER_SHARE:
        raise HTTPException(status_code=429, detail="Annotation limit reached for this share link")
    annotation = {"text": text, "ts": time.time()}
    share["annotations"].append(annotation)
    _SHARES.save_preserving_ttl(token, share)  # no sliding TTL: absolute 24h expiry holds
    try:
        session_uuid = UUID(str(share["session_id"]))
        # MessageRole has no SYSTEM member (user/assistant only): the old
        # reference raised AttributeError on every call, so the owner never
        # received the note and the bare except hid it behind "annotated".
        db.add(Message(session_id=session_uuid, role=MessageRole.assistant,
                       content=f"Helper note: {text}", agent_used="share",
                       meta={"kind": "helper_note"}))
        await db.commit()
    except Exception:
        await db.rollback()
    return {"status": "annotated", "total": len(share["annotations"])}
