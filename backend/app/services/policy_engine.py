from openai import AsyncOpenAI
from uuid import UUID
from app.config import settings
from app.models.preference import VerbosityLevel, DisabilityProfile, LanguageComplexity
from app.models.message import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession


# Explicit timeout: the openai client's default is 600 minutes, which would let
# a hung rewrite stall a request the frontend has already given up on. The
# fallback below returns the unmodified answer, so failing fast is the better
# trade for an accessibility tool.
client = AsyncOpenAI(
    base_url=settings.nim_base_url,
    api_key=settings.nim_api_key,
    timeout=settings.rewrite_timeout_seconds,
    max_retries=1,
)


DISABILITY_PROMPTS = {
    DisabilityProfile.blind: (
        "Respond with clear, step-by-step verbal instructions. "
        "Avoid visual references like 'click here', 'see above', or 'on the right'. "
        "Use spatial descriptions: 'the first field', 'the button below the form'. "
        "Announce state changes explicitly."
    ),
    DisabilityProfile.low_vision: (
        "Describe visual elements with high-contrast references. "
        "Reference sizes: 'large button', 'small text'. "
        "Mention color only with contrast context: 'red error text on white background'."
    ),
    DisabilityProfile.cognitive: (
        "Use simple language. Break information into short steps. "
        "Avoid technical jargon and complex sentences. "
        "Maximum 2 clauses per sentence. Use bullet points for lists."
    ),
    DisabilityProfile.motor: (
        "Minimize required interactions. Prefer voice-first workflows. "
        "Combine multiple steps into single actions. "
        "Indicate keyboard shortcuts when available."
    ),
    DisabilityProfile.none: "",
}


LANGUAGE_COMPLEXITY_PROMPTS = {
    LanguageComplexity.simple: "Use simple words, short sentences, and concrete terms.",
    LanguageComplexity.standard: "",
    LanguageComplexity.technical: "Use precise terminology and detailed explanations.",
}


async def count_clarifying_questions(db: AsyncSession | None, session_id: UUID | str, window: int = 5) -> int:
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


async def get_message_count(db: AsyncSession | None, session_id: UUID | str) -> int:
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
    session_id: UUID | str
) -> str:
    """
    Apply adaptive accessibility policy to adjust response style.
    
    This is designed to be extended with a proper ML-based adaptation model later.
    Currently uses simple rule-based logic with optional LLM rewrite.
    """
    
    # Build disability-specific instruction
    disability_instruction = DISABILITY_PROMPTS.get(user_prefs.disability_profile, "")
    language_instruction = LANGUAGE_COMPLEXITY_PROMPTS.get(user_prefs.language_complexity, "")
    
    combined_instruction = f"{disability_instruction} {language_instruction}".strip()
    
    # Rule 1: High confusion → simplify (highest priority)
    if clarifying_count >= settings.clarifying_threshold:
        instruction = "Simplify this explanation for a confused user. Use plain language, short sentences, and avoid jargon."
        if combined_instruction:
            instruction = f"{combined_instruction} {instruction}"
        return await llm_rewrite(raw_answer, instruction)

    # Rule 2: Disability profile + language complexity (always apply if set)
    if combined_instruction:
        return await llm_rewrite(raw_answer, combined_instruction)

    # Rule 3: Verbosity preference
    if user_prefs.verbosity_level == VerbosityLevel.concise:
        instruction = "Make this response concise - maximum 2 sentences, direct and to the point."
        if language_instruction:
            instruction = f"{language_instruction} {instruction}"
        return await llm_rewrite(raw_answer, instruction)
    elif user_prefs.verbosity_level == VerbosityLevel.detailed:
        instruction = "Expand this response with examples, context, and thorough explanation."
        if language_instruction:
            instruction = f"{language_instruction} {instruction}"
        return await llm_rewrite(raw_answer, instruction)

    # Rule 4: First-time user (few messages in session)
    msg_count = await get_message_count(db, session_id)
    if msg_count < 3:
        instruction = "Add a brief welcoming orientation. Be encouraging and explain any next steps."
        if combined_instruction:
            instruction = f"{combined_instruction} {instruction}"
        return await llm_rewrite(raw_answer, instruction)

    # Rule 5: Observed behavior - LOWEST priority, defaults only.
    # replay = the user replayed answers (didn't get it) -> simplify.
    # skip = the user cut answers off (too verbose) -> lean concise.
    # Any explicit preference (non-default verbosity/profile/complexity) wins
    # over inference: this rule fires only when the user never stated otherwise.
    if _prefs_are_defaults(user_prefs):
        replays = (session_context or {}).get("replay_count", 0)
        skips = (session_context or {}).get("skip_count", 0)
        if replays >= 2:
            return await llm_rewrite(
                raw_answer,
                "The user replayed previous answers, so they found them hard to "
                "follow. Simplify: plain words, short sentences, one idea per sentence.")
        if skips >= 2:
            return await llm_rewrite(
                raw_answer,
                "The user keeps skipping answers before they finish, so they find "
                "them too long. Be concise: maximum 2 sentences, key point first.")

    # Default: return as-is
    return raw_answer


def _prefs_are_defaults(user_prefs) -> bool:
    """True when the user never stated a non-default preference.

    Missing attributes (demo/partial prefs) count as defaults - only an
    explicitly stored non-default value opts out of behavior-driven shaping.
    """
    return (
        getattr(user_prefs, "verbosity_level", VerbosityLevel.standard) == VerbosityLevel.standard
        and getattr(user_prefs, "disability_profile", DisabilityProfile.none) == DisabilityProfile.none
        and getattr(user_prefs, "language_complexity", LanguageComplexity.standard) == LanguageComplexity.standard
    )


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