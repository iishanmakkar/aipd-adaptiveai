from openai import AsyncOpenAI
from app.config import settings
from app.models.preference import VerbosityLevel
from app.models.message import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


client = AsyncOpenAI(base_url=settings.nim_base_url, api_key=settings.nim_api_key)


async def count_clarifying_questions(db: AsyncSession | None, session_id: str, window: int = 5) -> int:
    """Count user questions in recent history."""
    if db is None:
        return 0
    result = await db.execute(
        select(Message)
        .where(Message.session_id == session_id, Message.role == "user")
        .order_by(Message.created_at.desc())
        .limit(window)
    )
    messages = result.scalars().all()
    return sum(1 for m in messages if m.content.strip().endswith("?"))


async def get_message_count(db: AsyncSession | None, session_id: str) -> int:
    """Get total message count for session."""
    if db is None:
        return 0
    result = await db.execute(
        select(Message).where(Message.session_id == session_id)
    )
    return len(result.scalars().all())


async def adjust_response(
    raw_answer: str,
    user_prefs,
    clarifying_count: int,
    session_context: dict,
    db: AsyncSession | None,
    session_id: str
) -> str:
    """
    Apply adaptive accessibility policy to adjust response style.
    
    This is designed to be extended with a proper ML-based adaptation model later.
    Currently uses simple rule-based logic with optional LLM rewrite.
    """
    
    # Rule 1: High confusion → simplify
    if clarifying_count >= settings.clarifying_threshold:
        return await llm_rewrite(raw_answer, "Simplify this explanation for a confused user. Use plain language, short sentences, and avoid jargon.")

    # Rule 2: Verbosity preference
    if user_prefs.verbosity_level == VerbosityLevel.concise:
        return await llm_rewrite(raw_answer, "Make this response concise - maximum 2 sentences, direct and to the point.")
    elif user_prefs.verbosity_level == VerbosityLevel.detailed:
        return await llm_rewrite(raw_answer, "Expand this response with examples, context, and thorough explanation.")

    # Rule 3: First-time user (few messages in session)
    msg_count = await get_message_count(db, session_id)
    if msg_count < 3:
        return await llm_rewrite(raw_answer, "Add a brief welcoming orientation. Be encouraging and explain any next steps.")

    # Default: return as-is
    return raw_answer


async def llm_rewrite(text: str, instruction: str) -> str:
    """Rewrite text using NVIDIA NIM LLM."""
    try:
        response = await client.chat.completions.create(
            model=settings.nim_model,
            messages=[
                {"role": "system", "content": f"You are an accessibility assistant. {instruction}"},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            max_tokens=500
        )
        return response.choices[0].message.content.strip()
    except Exception:
        # Fallback: return original text if LLM fails
        return text