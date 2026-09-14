"""User preference API - the missing half of the adaptive-policy loop.

The policy engine rewrites answers based on the stored verbosity preference,
but until now nothing could ever write that row: the toolbar setting died in
browser state. This endpoint persists it so the preference actually shapes
answers.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.database import get_db, is_db_available
from app.models.preference import Preference
from app.models.user import User
from app.schemas.preference import PreferenceUpdate, PreferenceResponse

router = APIRouter(prefix="/api", tags=["preferences"])


async def _get_or_create_preference(db: AsyncSession, user: User) -> Preference:
    result = await db.execute(select(Preference).where(Preference.user_id == user.id))
    pref = result.scalar_one_or_none()
    if pref is None:
        pref = Preference(user_id=user.id)
        db.add(pref)
        await db.flush()
    return pref


def _require_db() -> None:
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running")


@router.get("/preferences", response_model=PreferenceResponse)
async def get_preferences(
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_db()
    try:
        pref = await _get_or_create_preference(db, current_user)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    return PreferenceResponse(verbosity_level=pref.verbosity_level, voice_speed=pref.voice_speed)


@router.put("/preferences", response_model=PreferenceResponse)
async def update_preferences(
    update: PreferenceUpdate,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_db()
    try:
        pref = await _get_or_create_preference(db, current_user)
        pref.verbosity_level = update.verbosity_level
        pref.voice_speed = update.voice_speed
        await db.commit()
        await db.refresh(pref)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    return PreferenceResponse(verbosity_level=pref.verbosity_level, voice_speed=pref.voice_speed)
