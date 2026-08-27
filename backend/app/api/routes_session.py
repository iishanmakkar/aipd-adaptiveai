from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.auth import get_current_user, get_current_user_optional
from app.config import settings
from app.database import get_db, is_db_available
from app.models.session import Session
from app.models.message import Message
from app.models.user import User
from app.schemas.session import SessionResponse, HistoryResponse, MessageResponse
from uuid import uuid4
from datetime import datetime, timezone

router = APIRouter(prefix="/api", tags=["session"])


async def require_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available in demo mode. Configure SUPABASE_DB_URL to enable.")
    return db


@router.post("/session", response_model=SessionResponse, status_code=201)
async def create_session(
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    # REAL MODE: require live DB - real 503 if down (not fake-success, not 500)
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running (docker compose up postgres)")
    try:
        session = Session(user_id=current_user.id)
        db.add(session)
        await db.commit()
        await db.refresh(session)
        return {"session_id": str(session.id), "created_at": session.created_at}
    except Exception as e:
        try:
            await db.rollback()
        except Exception:
            pass
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")


@router.get("/history/{session_id}", response_model=HistoryResponse)
async def get_history(
    session_id: str,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    # REAL MODE: require live DB - real 503 if down
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running")
    try:
        result = await db.execute(
            select(Session).where(Session.id == session_id, Session.user_id == current_user.id)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # Get total count
    count_result = await db.execute(
        select(func.count(Message.id)).where(Message.session_id == session_id)
    )
    total = count_result.scalar_one()

    # Get paginated messages
    offset = (page - 1) * page_size
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id)
        .order_by(Message.created_at)
        .offset(offset)
        .limit(page_size)
    )
    messages = result.scalars().all()

    return HistoryResponse(
        session_id=session_id,
        messages=[
            MessageResponse(
                id=str(m.id),
                role=m.role.value,
                content=m.content,
                agent_used=m.agent_used,
                created_at=m.created_at
            )
            for m in messages
        ],
        total=total,
        page=page,
        page_size=page_size
    )