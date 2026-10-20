"""User preference API - the missing half of the adaptive-policy loop.

The policy engine rewrites answers based on the stored verbosity preference,
but until now nothing could ever write that row: the toolbar setting died in
browser state. This endpoint persists it so the preference actually shapes
answers.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_user_optional
from app.database import get_db, is_db_available
from app.models.preference import (
    Preference,
    VerbosityLevel,
    DisabilityProfile,
    LanguageComplexity,
)
from app.models.user import User
from app.schemas.preference import PreferenceUpdate, PreferenceResponse

router = APIRouter(prefix="/api", tags=["preferences"])


_PREFERENCE_DEFAULTS = {
    "verbosity_level": VerbosityLevel.standard,
    "voice_speed": 1.0,
    "disability_profile": DisabilityProfile.none,
    "language_complexity": LanguageComplexity.standard,
}


def _heal_nulls(pref: Preference) -> Preference:
    """Legacy rows (or pre-flush objects) can carry None where the response
    contract requires a value. Fill defaults so reads never 500."""
    for field, default in _PREFERENCE_DEFAULTS.items():
        if getattr(pref, field, None) is None:
            setattr(pref, field, default)
    return pref


async def _get_or_create_preference(db: AsyncSession, user: User) -> Preference:
    result = await db.execute(select(Preference).where(Preference.user_id == user.id))
    pref = result.scalar_one_or_none()
    if pref is None:
        # Explicit values, not flush-fired column defaults: attributes must be
        # present immediately (reads happen before any flush).
        pref = Preference(user_id=user.id, **_PREFERENCE_DEFAULTS)
        db.add(pref)
        try:
            await db.flush()
        except IntegrityError:
            # Two concurrent first touches both missed the row; the winner's
            # row is the one to use - never 503 this.
            await db.rollback()
            result = await db.execute(select(Preference).where(Preference.user_id == user.id))
            pref = result.scalar_one_or_none()
            if pref is None:
                raise
    return _heal_nulls(pref)


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
    return PreferenceResponse(
        verbosity_level=pref.verbosity_level,
        voice_speed=pref.voice_speed,
        disability_profile=pref.disability_profile,
        language_complexity=pref.language_complexity,
    )


@router.put("/preferences", response_model=PreferenceResponse)
async def update_preferences(
    update: PreferenceUpdate,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    _require_db()
    try:
        pref = await _get_or_create_preference(db, current_user)
        if update.verbosity_level is not None:
            pref.verbosity_level = update.verbosity_level
        if update.voice_speed is not None:
            pref.voice_speed = update.voice_speed
        if update.disability_profile is not None:
            pref.disability_profile = update.disability_profile
        if update.language_complexity is not None:
            pref.language_complexity = update.language_complexity
        await db.commit()
        await db.refresh(pref)
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    return PreferenceResponse(
        verbosity_level=pref.verbosity_level,
        voice_speed=pref.voice_speed,
        disability_profile=pref.disability_profile,
        language_complexity=pref.language_complexity,
    )
