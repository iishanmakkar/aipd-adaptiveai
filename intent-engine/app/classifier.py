import json
import time
from collections import OrderedDict
from typing import Dict, List, Tuple
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ClassifyRequest, ClassifyResponse

# Bounded session context store: LRU eviction by last touch, plus per-session TTL.
# A plain dict grew one entry per session forever (unbounded memory in a
# long-running service), so sessions are capped and idle ones expire.
_session_memory: "OrderedDict[str, Tuple[List[str], float]]" = OrderedDict()


def _evict_expired() -> None:
    now = time.time()
    expired = [
        sid for sid, (_, touched) in _session_memory.items()
        if now - touched > settings.session_ttl_seconds
    ]
    for sid in expired:
        _session_memory.pop(sid, None)


# Keyword-based fallback classifier
KEYWORD_RULES = [
    # (keywords, intent, target_agent, entity_hint)
    # Priority order for exact score ties: more common intents first.
    (["fill", "form", "field", "input", "submit", "application", "register", "signup", "what is this field", "how to fill", "field asking"],
     "form_help", "form_agent", "form field"),
    # NOTE: deliberately no bare "terms" - it matched "in simple terms" and
    # hijacked education questions into document_help.
    (["document", "pdf", "read", "summarize", "summary", "extract", "contract", "agreement", "terms and conditions", "terms of service", "policy", "document content"],
     "document_help", "document_agent", "document content"),
    (["explain", "teach", "learn", "study", "concept", "topic", "course", "lesson", "tutorial", "what is", "define", "meaning"],
     "education_help", "education_agent", "educational concept"),
    (["navigate", "website", "page", "click", "button", "link", "menu", "navigation", "find", "where is", "how to get to", "go to"],
     "web_navigation_help", "web_agent", "web element"),
]


def keyword_classify(text: str, screen_context: str = "") -> Tuple[str, str, str, float, str]:
    """
    Keyword-based classification fallback (used when the LLM is unreachable).

    Scores every rule and keeps the best instead of returning the first match:
    first-match-wins let a single weak form keyword ("submit") outrank three
    web keywords ("where is" + "button" + "page"). Matches in the user's own
    input count double compared to matches in the screen context, since the
    input is what they actually asked.

    Returns (intent, target_agent, entity, confidence, reasoning).
    """
    text_lower = text.lower()
    context_lower = (screen_context or "").lower()

    best_score = 0
    best_rule = None
    for keywords, intent, agent, entity_hint in KEYWORD_RULES:
        score = sum(2 for kw in keywords if kw in text_lower)
        score += sum(1 for kw in keywords if kw in context_lower)
        if score > best_score:
            best_score = score
            best_rule = (intent, agent, entity_hint)

    combined = f"{text_lower} {context_lower}"

    if best_rule is None:
        # Nothing matched: this is a low-confidence default, and saying so is
        # more useful to the caller than pretending certainty.
        return "general_query", "general_agent", "general question", 0.3, "No specific intent keywords matched, defaulting to general query"

    intent, agent, entity_hint = best_rule

    # Confidence from match strength: each input hit weighs double a context
    # hit, so a single weak screen-context match cannot look certain.
    confidence = min(0.9, round(0.4 + 0.1 * best_score, 2))

    # Try to extract a more specific entity
    entity = entity_hint
    if "aadhar" in combined or "aadhaar" in combined:
        entity = "Aadhaar number field"
    elif "dob" in combined or "date of birth" in combined or "birth" in combined:
        entity = "Date of Birth field"
    elif "permanent address" in combined or "address" in combined:
        entity = "Permanent Address field"
    elif "submit" in combined or "button" in combined:
        entity = "submit button"
    elif "photosynthesis" in combined:
        entity = "photosynthesis"
    elif "machine learning" in combined or " ml " in combined:
        entity = "machine learning"

    reasoning = f"Keyword match for {intent}: detected relevant terms in input"
    return intent, agent, entity, confidence, reasoning


# LLM-based classifier
SYSTEM_PROMPT = """You are an intent classification system for AdaptiveAI, an accessibility assistant for visually impaired users.

Classify the user's input into ONE of these intents and pick the corresponding target agent:

1. form_help -> form_agent: User needs help with a form field (what it means, how to fill, validation)
2. document_help -> document_agent: User wants to understand, summarize, or extract info from a document/PDF
3. web_navigation_help -> web_agent: User needs help navigating a website, finding elements, understanding UI
4. education_help -> education_agent: User wants to learn or understand an educational concept
5. general_query -> general_agent: General questions, greetings, or unclear intent

Also extract the specific entity (field name, document section, web element, concept) the user is asking about.

Return ONLY valid JSON with these exact fields:
{
  "intent": "one_of_the_5_intents",
  "target_agent": "corresponding_agent",
  "extracted_entity": "specific thing user is asking about",
  "reasoning": "brief explanation of why this classification was chosen",
  "confidence": 0.85
}

"confidence" is your own certainty that the intent label is right, as a number
from 0.0 to 1.0. Use values below 0.5 when the input is ambiguous, mixed, or
could plausibly belong to two intents."""


async def llm_classify(request: ClassifyRequest) -> ClassifyResponse:
    """Classify using LLM via NVIDIA NIM (OpenAI-compatible)."""
    # Explicit timeout BELOW the backend's 45s intent budget: the openai SDK
    # defaults to a 600s timeout with retries, so a hung NIM call used to blow
    # straight through the fallback window and surface as a 502 upstream. With
    # a bounded client, a NIM hang raises here and the keyword fallback answers.
    client = AsyncOpenAI(base_url=settings.nim_base_url, api_key=settings.nim_api_key,
                         timeout=30.0, max_retries=1)
    
    # Build context from history
    history_context = "\n".join(request.history[-settings.max_history_turns:]) if request.history else "No prior conversation."
    
    user_prompt = f"""Current user input: "{request.input_text}"
Screen context: "{request.screen_context or 'None'}"
Conversation history (recent): {history_context}

Classify this request."""

    try:
        response = await client.chat.completions.create(
            model=settings.nim_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt}
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)

        # Validate response structure
        required = ["intent", "target_agent", "extracted_entity", "reasoning"]
        if not all(k in result for k in required):
            raise ValueError("Missing required fields in LLM response")

        # Confidence is self-reported; missing or out-of-range values fall back
        # to a neutral 0.5 rather than failing the whole classification.
        try:
            confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5

        return ClassifyResponse(**{**result, "confidence": confidence})
        
    except Exception as e:
        # Fallback to keyword classifier
        intent, agent, entity, reasoning = keyword_classify(request.input_text, request.screen_context)
        reasoning += f" (LLM failed: {str(e)[:100]}, using keyword fallback)"
        return ClassifyResponse(
            intent=intent,
            target_agent=agent,
            extracted_entity=entity,
            reasoning=reasoning
        )


def get_session_history(session_id: str) -> List[str]:
    """Get conversation history for a session, refreshing its LRU/TTL position."""
    _evict_expired()
    entry = _session_memory.get(session_id)
    if entry is None:
        return []
    history, _ = entry
    _session_memory.move_to_end(session_id)
    _session_memory[session_id] = (history, time.time())
    return list(history)


def add_to_history(session_id: str, user_input: str, classification: ClassifyResponse):
    """Add user input and classification to session history."""
    _evict_expired()
    history, _ = _session_memory.get(session_id, ([], 0.0))
    history = list(history)

    # Keep only last N turns (user + system pairs)
    history.append(f"User: {user_input}")
    history.append(f"System: Classified as {classification.intent} ({classification.target_agent}) - {classification.extracted_entity}")

    # Trim to max_turns * 2 (user + system pairs)
    max_items = settings.max_history_turns * 2
    if len(history) > max_items:
        history = history[-max_items:]

    _session_memory[session_id] = (history, time.time())
    _session_memory.move_to_end(session_id)

    # Evict least-recently-used sessions once the cap is exceeded
    while len(_session_memory) > settings.max_sessions:
        _session_memory.popitem(last=False)


def clear_session(session_id: str):
    """Clear session history."""
    _session_memory.pop(session_id, None)


def active_session_count() -> int:
    """Number of sessions currently held in memory (used by tests/metrics)."""
    _evict_expired()
    return len(_session_memory)


def clear_all_sessions() -> None:
    """Drop every session (service startup/shutdown)."""
    _session_memory.clear()