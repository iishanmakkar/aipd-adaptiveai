from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from uuid import UUID

from app.api.auth import get_current_user, get_current_user_optional
from app.config import settings
from app.database import get_db, is_db_available
from app.models.user import User
from app.models.session import Session
from app.models.message import Message, MessageRole
from app.models.preference import Preference
from app.schemas.query import QueryRequest, QueryResponse
from app.services.clients import classify_intent, get_agent_response
from app.services.policy_engine import adjust_response, count_clarifying_questions

router = APIRouter(prefix="/api", tags=["query"])


async def require_db(db: AsyncSession = Depends(get_db)) -> AsyncSession:
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available in demo mode. Configure SUPABASE_DB_URL to enable.")
    return db


@router.post("/query", response_model=QueryResponse)
async def process_query(
    http_request: Request,
    request: QueryRequest,
    current_user = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db)
):
    # REAL MODE: require live DB and live services - no mock fallback, real 503/404/502
    if not is_db_available():
        raise HTTPException(status_code=503, detail="Database not available - ensure postgres is running (docker compose up postgres)")
    # Verify session belongs to user - REAL ownership check (rejects cross-user)
    try:
        result = await db.execute(
            select(Session).where(Session.id == UUID(request.session_id), Session.user_id == current_user.id)
        )
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Database connection failed: {str(e)[:200]}")
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found - create one via POST /api/session first")

    # Get recent history for context
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session.id)
        .order_by(Message.created_at.desc())
        .limit(10)
    )
    recent_messages = list(reversed(result.scalars().all()))
    history = [f"{m.role.value}: {m.content}" for m in recent_messages]

    # Save user message
    user_msg = Message(
        session_id=session.id,
        role=MessageRole.user,
        content=request.input_text,
        meta={"input_source": request.input_source, "screen_context": request.screen_context}
    )
    db.add(user_msg)

    # Step 1: Call Intent & Context Engine - propagate X-Request-ID for tracing
    request_id = getattr(http_request.state, "request_id", None) or http_request.headers.get("X-Request-ID")
    try:
        intent_result = await classify_intent(
            session_id=request.session_id,
            input_text=request.input_text,
            screen_context=request.screen_context,
            history=history,
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Intent service error: {str(e)}")

    # Step 2: Call appropriate Task Agent - propagate X-Request-ID
    try:
        agent_result = await get_agent_response(
            session_id=request.session_id,
            agent=intent_result.target_agent,
            query=request.input_text,
            entity=intent_result.extracted_entity,
            extra_context=request.screen_context or "",
            request_id=request_id,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent service error: {str(e)}")

    # Step 3: Apply Policy Engine
    # Get user preferences
    result = await db.execute(select(Preference).where(Preference.user_id == current_user.id))
    prefs = result.scalar_one_or_none()
    
    clarifying_count = await count_clarifying_questions(db, request.session_id)
    
    adjusted_answer = await adjust_response(
        raw_answer=agent_result.answer,
        user_prefs=prefs,
        clarifying_count=clarifying_count,
        session_context={"message_count": len(recent_messages)},
        db=db,
        session_id=request.session_id
    )

    # Step 4: Save assistant message
    assistant_msg = Message(
        session_id=session.id,
        role=MessageRole.assistant,
        content=adjusted_answer,
        agent_used=intent_result.target_agent,
        meta={
            "intent": intent_result.intent,
            "reasoning": intent_result.reasoning,
            "sources_used": agent_result.sources_used,
            "suggested_action": agent_result.suggested_action,
            "clarifying_count": clarifying_count
        }
    )
    db.add(assistant_msg)
    await db.commit()

    # Calculate confidence (placeholder - real impl would use classifier confidence)
    confidence = 0.85

    return QueryResponse(
        response_text=adjusted_answer,
        agent_used=intent_result.target_agent,
        suggested_action=agent_result.suggested_action,
        confidence=confidence
    )


@router.post("/query-demo", response_model=QueryResponse)
async def process_query_demo(request: QueryRequest):
    """
    REAL endpoint without DB: still calls live Intent & Agents services (no mocks).
    Used for demos when postgres not available; main /api/query is DB-persisted real mode.
    """
    # Demo: create a simple in-memory history (no DB persistence, but services are live)
    history = []  # In production this would come from DB; here we keep it ephemeral
    
    # Step 1: Call Intent & Context Engine
    try:
        intent_result = await classify_intent(
            session_id=request.session_id,
            input_text=request.input_text,
            screen_context=request.screen_context,
            history=history
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Intent service error: {str(e)}")

    # Step 2: Call appropriate Task Agent
    try:
        agent_result = await get_agent_response(
            session_id=request.session_id,
            agent=intent_result.target_agent,
            query=request.input_text,
            entity=intent_result.extracted_entity,
            extra_context=request.screen_context or ""
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Agent service error: {str(e)}")

    # Step 3: Apply Policy Engine (simplified - no DB prefs)
    from app.models.preference import VerbosityLevel
    from types import SimpleNamespace
    
    # Mock preferences for demo
    prefs = SimpleNamespace(verbosity_level=VerbosityLevel.standard)
    clarifying_count = 0
    
    adjusted_answer = await adjust_response(
        raw_answer=agent_result.answer,
        user_prefs=prefs,
        clarifying_count=clarifying_count,
        session_context={"message_count": 0},
        db=None,  # type: ignore
        session_id=request.session_id
    )

    # Calculate confidence
    confidence = 0.85

    return QueryResponse(
        response_text=adjusted_answer,
        agent_used=intent_result.target_agent,
        suggested_action=agent_result.suggested_action,
        confidence=confidence
    )