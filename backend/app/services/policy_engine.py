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
        "Use sequential descriptions: 'the first field', 'the next button after Name'. "
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
        "Mention only keyboard shortcuts stated in the page context; never invent any."
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
    return sum(1 for m in messages if (m.content or "").strip().endswith("?"))


async def get_message_count(db: AsyncSession | None, session_id: UUID | str) -> int:
    """Get total message count for session."""
    if db is None:
        return 0
    from sqlalchemy import func
    result = await db.execute(
        select(func.count()).select_from(Message).where(Message.session_id == session_id)
    )
    return int(result.scalar_one())


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
    if user_prefs is None:
        # No preference row (legacy user, failed demo-user bootstrap): shape
        # nothing, but never crash - every rule below reads attributes.
        from types import SimpleNamespace
        user_prefs = SimpleNamespace(
            verbosity_level=VerbosityLevel.standard,
            disability_profile=DisabilityProfile.none,
            language_complexity=LanguageComplexity.standard)

    # Build disability-specific instruction
    disability_instruction = DISABILITY_PROMPTS.get(user_prefs.disability_profile, "")
    language_instruction = LANGUAGE_COMPLEXITY_PROMPTS.get(user_prefs.language_complexity, "")

    combined_instruction = f"{disability_instruction} {language_instruction}".strip()
    # Verbosity composes with EVERYTHING below (it used to die in Rule 1 and
    # never reach blind+concise users at all). Suffixes keep the historical
    # Rule-3 wording so prompt-contract tests keep passing.
    if user_prefs.verbosity_level == VerbosityLevel.concise:
        combined_instruction += " Make this response concise - maximum 2 sentences, direct and to the point."
    elif user_prefs.verbosity_level == VerbosityLevel.detailed:
        combined_instruction += " Expand this response with examples, context, and thorough explanation."

    # First-time orientation is independent of shaping: a new blind+concise
    # user gets the rewrite AND the tip (previously Rule 4 never ran for
    # explicit prefs, so they never learned repeat/simplify exist).
    if db is None:
        msg_count = 0  # no history available: treat as first-time (old contract)
    else:
        msg_count = (session_context or {}).get("message_count")
        if msg_count is None:
            msg_count = await get_message_count(db, session_id)

    def _with_tip(text: str) -> str:
        if msg_count >= 3:
            return text
        tip = "Tip: you can ask me to repeat any answer, or to make it simpler, at any time."
        stripped = text.rstrip()
        if not stripped:
            # An empty answer with a leading ". " would read as ". Tip: ...".
            return tip
        glue = " " if stripped.endswith((".", "!", "?")) else ". "
        out = stripped + glue + tip
        # Blind shaping still applies on first turns (was returned raw).
        if user_prefs.disability_profile == DisabilityProfile.blind:
            out = out.replace("click here", "activate the next button").replace("see above", "described above")
        return out

    # Rule 1: High confusion → simplify (highest priority). Returns the
    # rewrite verbatim (no orientation tip): the pinned contract is one
    # simplification pass for a confused user.
    if clarifying_count >= settings.clarifying_threshold:
        instruction = "Simplify this explanation for a confused user. Use plain language, short sentences, and avoid jargon."
        if combined_instruction:
            instruction = f"{combined_instruction} {instruction}"
        return await llm_rewrite(raw_answer, instruction)

    # Rule 2: Disability profile + language complexity + verbosity (always
    # apply if set).
    if combined_instruction:
        return _with_tip(await llm_rewrite(raw_answer, combined_instruction))

    # Rule 3: unreachable alone now (verbosity already folded into
    # combined_instruction above, which is non-empty whenever verbosity is
    # non-default) — kept as a guard for direct-call parity.
    if user_prefs.verbosity_level in (VerbosityLevel.concise, VerbosityLevel.detailed):
        return _with_tip(await llm_rewrite(raw_answer, combined_instruction))

    # Rule 4: First-time user (few messages in session). Deliberately NOT an
    # LLM rewrite: this fired a SECOND full NIM completion on nearly every
    # new-session answer (~12s of the ~28s measured query) for a nicety the
    # chat's own welcome bubble already covers. A fixed orientation sentence
    # costs zero latency and says the same thing.
    if msg_count < 3:
        return _with_tip(raw_answer)

    # Rule 5: Observed behavior - LOWEST priority, defaults only.
    # replay = the user replayed answers (didn't get it) -> simplify.
    # skip = the user cut answers off (too verbose) -> lean concise.
    # Any explicit preference (non-default verbosity/profile/complexity) wins
    # over inference: this rule fires only when the user never stated otherwise.
    if _prefs_are_defaults(user_prefs):
        replays = (session_context or {}).get("replay_count", 0)
        skips = (session_context or {}).get("skip_count", 0)
        if replays >= 2 and skips >= 2:
            # Contradictory signals (didn't get it AND too long): serve both
            # with plain short words, not one at the other's expense.
            return await llm_rewrite(
                raw_answer,
                "The user replayed previous answers (hard to follow) and also "
                "skips them (too long). Use plain words, short sentences, "
                "maximum 2 sentences, key point first.")
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
    voice_speed is deliberately excluded: it is TTS-only, so a faster voice
    must not opt the user out of text shaping they never refused.
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
            max_tokens=800
        )
        content = response.choices[0].message.content or ""
        out = content.strip() or text
    except Exception:
        # Fallback: return original text if LLM fails
        out = text
    # Deterministic blind guard: NIM-down must not leak visual refs.
    for bad, good in (("click here", "activate the next button"),
                      ("see above", "described above"),
                      ("on the right", "next in order"),
                      ("on the left", "previous in order")):
        out = out.replace(bad, good)
    return out