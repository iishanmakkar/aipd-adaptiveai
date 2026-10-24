import asyncio
import json
import re
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


# Action/inspect verbs that ONLY route to the live browser when a page is
# actually open. The open page is signalled by the "Live page:" marker the
# backend puts in screen_context when a browser session exists for the chat
# session. Gating on the marker (not just the verbs) is what keeps every
# pre-existing case routing exactly as before: "Click it" with no page open
# stays informational, because there is nothing real to act on.
BROWSER_ACT_VERBS = (
    "fill in", "fill this", "fill out", "fill the", "click the", "press the",
    "submit", "book", "type ", "enter ", "select the", "choose ",
)
# Bare action verbs (word-boundary matched): "Select option 2" and "Fill my
# name" carry no "the", and the raw-substring "book" above also fired inside
# "facebook"/"bookmark".
BROWSER_ACT_WORDS = (
    "fill", "click", "select", "type", "enter", "choose", "book", "submit",
    "press",
)
BROWSER_INSPECT_VERBS = (
    "where is", "find", "locate", "what does this", "describe",
    "show me", "which ",
)


_LIVE_MARKER_RE = re.compile(r"(?m)^live page:", re.IGNORECASE)


def _browser_route(text_lower: str, context_lower: str):
    """(intent, agent, entity_hint) or None. Live-page marker is mandatory.

    Inspect is checked first on purpose: when phrasing is ambiguous ("find
    the submit button and click it"), the read-only path wins and the user
    confirms the action explicitly on the next turn.
    """
    # The marker is the backend's own emitted line ("Live page: <title> (url)"),
    # anchored to a line start. As a bare substring, any page whose VISIBLE
    # text contained "live page:" (a news live-blog, help copy) minted the
    # consent marker out of page content.
    if not _LIVE_MARKER_RE.search(context_lower):
        return None
    if any(_kw_in(text_lower, v) for v in BROWSER_INSPECT_VERBS):
        return ("browser_inspect", "browser_agent", "live page element")
    if any(_kw_in(text_lower, v) for v in BROWSER_ACT_VERBS):
        return ("browser_act", "browser_agent", "live page element")
    if any(_kw_in(text_lower, w) for w in BROWSER_ACT_WORDS):
        return ("browser_act", "browser_agent", "live page element")
    return None


def _kw_in(haystack: str, keyword: str) -> bool:
    """Single words match on word boundaries; phrases match as substrings.

    Bare `in` let "form" match "information" and "read" match "already",
    hijacking unrelated questions into the wrong agent. Phrases keep substring
    matching (their internal spacing already anchors them).
    """
    if " " in keyword:
        return keyword in haystack
    return re.search(r"\b" + re.escape(keyword) + r"\b", haystack) is not None


# Keyword-based fallback classifier
KEYWORD_RULES = [
    # (keywords, intent, target_agent, entity_hint)
    # Priority order for exact score ties: more common intents first.
    (["fill", "form", "field", "fields", "input", "submit", "application", "register", "signup", "what is this field", "how to fill", "field asking"],
     "form_help", "form_agent", "form field"),
    # NOTE: deliberately no bare "terms" - it matched "in simple terms" and
    # hijacked education questions into document_help.
    (["document", "documents", "pdf", "read", "summarize", "summary", "extract", "contract", "agreement", "terms and conditions", "terms of service", "policy", "document content", "section", "clause", "article", "paragraph"],
     "document_help", "document_agent", "document content"),
    (["explain", "teach", "learn", "study", "concept", "topic", "course", "lesson", "tutorial", "photosynthesis", "what is", "define", "meaning"],
     "education_help", "education_agent", "educational concept"),
    (["navigate", "website", "webpage", "page", "click", "button", "buttons", "link", "links", "menu", "menus", "navigation", "find", "where is", "how to get to", "go to", "dropdown", "options"],
     "web_navigation_help", "web_agent", "web element"),
    # New specialists sit after the incumbents so best-score ties keep the old
    # winner (existing routing is unchanged); each rule outscores the
    # incumbents only on its own phrasing. Translator precedes profile and
    # scheduler: "translate ... blind ..." and "translate my schedule" tie at
    # one hit each, and the translation request must win the tie.
    (["translate", "translation", "in hindi", "in tamil", "in telugu", "in spanish", "to telugu", "to hindi", "to tamil", "telugu", "hindi", "tamil", "spanish", "తెలుగు"],
     "translation_help", "translator_agent", "text to translate"),
    (["profile", "verbosity", "voice speed", "blind", "low vision", "update my profile"],
     "profile_update", "profile_updater_agent", "user profile"),
    (["go to", "navigate", "take me to", "take me", "checkout", "contact form", "go to checkout", "navigate to checkout"],
     "navigation_help", "navigation_agent", "navigation target"),
    (["schedule", "scheduled", "remind", "appointment", "calendar", "plan my day"],
     "scheduler_help", "scheduler_agent", "scheduled task"),
    (["contrast", "font", "font size", "bigger", "bigger text", "larger", "increase", "text size", "layout", "focus", "high contrast"],
     "ui_help", "ui_adjuster_agent", "display setting"),
    (["simplify", "simply", "what does this say", "in simple terms", "explain this", "easier to understand"],
     "content_explain", "content_explainer_agent", "content to explain"),
]


# The keyword classifier's no-match score. Every scored match is 0.4 or higher
# (0.4 base + 0.1 per hit), so this value uniquely identifies "nothing matched" -
# which the backend already treats as ambiguous, and which now gets labelled
# "default" rather than passing as a measured confidence.
NO_MATCH_CONFIDENCE = 0.3


def keyword_confidence_source(confidence: float) -> str:
    """Provenance for a confidence produced by keyword scoring."""
    return "default" if confidence <= NO_MATCH_CONFIDENCE else "keyword"


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

    # Live browser routing comes first and needs the page marker: without an
    # open page there is nothing real to inspect or act on, so every old case
    # below scores exactly as it always has.
    browser_hit = _browser_route(text_lower, context_lower)
    if browser_hit is not None:
        intent, agent, entity_hint = browser_hit
        return (intent, agent, entity_hint, 0.85,
                f"Live page open and action/inspect phrasing detected: {intent}")

    # The "Live page:" marker itself contains scoring words ("page",
    # "dropdown", field labels); strip it before keyword scoring so the
    # marker cannot vote for an intent - only the user's words and the real
    # screen description may.
    context_lower = re.sub(r"live page:.*", "", context_lower)

    # Document words win over explain/simplify phrasing ("Explain this
    # document in simple terms" is a document request, not content_explain):
    # the document rule gets a decisive bonus when the INPUT names a
    # document, so content_explain can only win on screen-pointing phrasing.
    document_named = any(
        _kw_in(text_lower, kw)
        for kw in ("document", "documents", "pdf", "contract", "agreement",
                   "terms and conditions", "terms of service", "policy",
                   "section", "clause", "article", "paragraph"))
    how_do_question = re.search(r"\bhow (do|to|can|should|would)\b", text_lower) is not None

    best_score = 0
    best_rule = None
    for keywords, intent, agent, entity_hint in KEYWORD_RULES:
        # "How do I go to checkout?" asks for guidance (web), it is not an
        # imperative destination command (navigation).
        if intent == "navigation_help" and how_do_question:
            continue
        score = sum(2 for kw in keywords if _kw_in(text_lower, kw))
        score += sum(1 for kw in keywords if _kw_in(context_lower, kw))
        if intent == "document_help" and document_named:
            score += 100
        if score > best_score:
            best_score = score
            best_rule = (intent, agent, entity_hint)

    combined = f"{text_lower} {context_lower}"

    if best_rule is None:
        # Nothing matched: this is a low-confidence default, and saying so is
        # more useful to the caller than pretending certainty.
        return ("general_query", "general_agent", "general question", NO_MATCH_CONFIDENCE,
                "No specific intent keywords matched, defaulting to general query")

    intent, agent, entity_hint = best_rule

    # Confidence from match strength: each input hit weighs double a context
    # hit, so a single weak screen-context match cannot look certain.
    confidence = min(0.9, round(0.4 + 0.1 * best_score, 2))

    # Try to extract a more specific entity - but only for a routed intent.
    # On the general-query default these overrides misfired ("birthday card"
    # -> "Date of Birth field"), dressing an unrouted question as a form one.
    entity = entity_hint
    if intent != "general_query":
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
        elif "machine learning" in combined or re.search(r"\bml\b", combined):
            entity = "machine learning"

    reasoning = f"Keyword match for {intent}: detected relevant terms in input"
    return intent, agent, entity, confidence, reasoning


# LLM-based classifier
SYSTEM_PROMPT = """You are an intent classification system for AdaptiveAI, an accessibility assistant for visually impaired users.

Classify the user's input into ONE of these intents and pick the corresponding target agent:

1. form_help -> form_agent: User needs help with a form field (what it means, how to fill, validation)
2. document_help -> document_agent: User wants to understand, READ, summarize, or extract info from a document/PDF/contract/terms
3. web_navigation_help -> web_agent: Guidance about a website: finding/understanding pages, links, menus, buttons ("where is X", "find the login link", "what does this menu item do", "how do I navigate to X")
4. education_help -> education_agent: Learning or explaining an educational CONCEPT, especially named topics (photosynthesis, machine learning, water cycle, Newton's laws, DNA)
5. general_query -> general_agent: General questions, greetings, or unclear intent
6. browser_inspect -> browser_agent: User asks about elements ON THE OPEN LIVE PAGE
   (screen context contains a "Live page:" marker) - "where is X", "what does
   this field mean", "find/describe/show me X". The page is real and open; the
   answer must come from its live DOM, never from generic advice.
7. browser_act -> browser_agent: User asks to DO something on the open live
   page ("fill in", "click the X", "submit", "book", "type", "select") - again
   ONLY when the "Live page:" marker is present. Without an open page, the
   same words are informational (form_help/web_navigation_help) instead.
   When phrasing is ambiguous between looking and doing, prefer
   browser_inspect: reading is safe, acting needs a second explicit turn.

8. scheduler_help -> scheduler_agent: User wants to schedule, plan their day, set a reminder, or manage appointments/calendar
9. translation_help -> translator_agent: User wants text translated into another language (Hindi, Tamil, Telugu, Spanish, ...)
10. ui_help -> ui_adjuster_agent: User wants display changes (contrast, font size, layout, focus, high contrast)
11. content_explain -> content_explainer_agent: User wants content simplified or explained in plain words ("explain this", "what does this say", "simplify")
12. profile_update -> profile_updater_agent: User wants their profile updated (verbosity, voice speed, blind/low-vision settings)
13. navigation_help -> navigation_agent: Imperative destination commands in a site/app ("go to checkout", "navigate to X", "take me to the contact form"). NOT "how do I ..." questions and NOT destination-less phrases ("go there", "click it")

    DISAMBIGUATION RULES (apply in order):
    1. Live-page marker (hard rule): the "Live page: <title> (<url>)" line in
       the screen context is the ONLY thing that makes browser_inspect/
       browser_act legal.
       - With the marker: "fill in my name as Asha" -> browser_act; "where is
         the submit button" -> browser_inspect. Ambiguous between looking and
         doing -> browser_inspect.
       - WITHOUT the marker: "click it" / "click the X" / "go there" ->
         web_navigation_help; "fill in my name" / "submit" -> form_help;
         NEVER browser_*.
    2. Named academic topic vs text on screen: explaining a NAMED concept
       (photosynthesis, machine learning, DNA, the water cycle) is
       education_help even when phrased with "in simple terms" / "simply" /
       "this concept". content_explain is ONLY for text the user points at on
       screen ("what does this say", "simplify this paragraph", "explain this
       page").
    3. Document words win over reading phrasing: document/PDF/contract/
       agreement/terms and conditions/terms of service/section/clause ->
       document_help even when phrased as "read ... to me", "summarize",
       "explain", or "in simple terms".
    4. Resolve short anaphoric inputs ("What is this?", "Explain this
       concept", "Summarize it", "Click it", "Go there", "What about this
       one?") from the SCREEN CONTEXT:
       form fields -> form_help; PDF/document/contract/terms -> document_help;
       textbook/lesson/educational content -> education_help;
       webpage/menu/link/button -> web_navigation_help.

Also extract the specific entity (field name, document section, web element, concept) the user is asking about.

Return ONLY valid JSON with these exact fields:
{
  "intent": "one_of_the_13_intents",
  "target_agent": "corresponding_agent",
  "extracted_entity": "specific thing user is asking about",
  "reasoning": "brief explanation of why this classification was chosen",
  "confidence": 0.85,
  "ambiguous": false
}

"confidence" is your own certainty that the intent label is right, as a number
from 0.0 to 1.0. Use values below 0.5 when the input is ambiguous, mixed, or
could plausibly belong to two intents.

"ambiguous" is true ONLY when the input is not an actionable request at all:
gibberish, an unrelated word salad, or so vague that no specialist could help
even after using the screen context and history. A real question — even a
short or informal one — is never ambiguous. When ambiguous is true, still
pick the closest intent so the field is always filled."""


async def llm_classify(request: ClassifyRequest) -> ClassifyResponse:
    """Classify using LLM via NVIDIA NIM (OpenAI-compatible)."""
    # Explicit timeout BELOW the backend's 45s intent budget: the openai SDK
    # defaults to a 600s timeout with retries, so a hung NIM call used to blow
    # straight through the fallback window and surface as a 502 upstream. With
    # a bounded client, a NIM hang raises here and the keyword fallback answers.
    # max_retries=0 (not 1): timeout x (1 + retries) is the worst case, and
    # 30s x 2 = 60s already exceeds the 45s budget the comment above promises.
    client = AsyncOpenAI(base_url=settings.nim_base_url, api_key=settings.nim_api_key,
                         timeout=30.0, max_retries=0)
    
    # Build context from history. Session history stores TWO items per turn
    # (User + System), so the turn-count setting must be doubled to slice
    # turns; otherwise the prompt gets ~2.5 turns and can start mid-pair with
    # an orphaned "System:" line whose "User:" line was trimmed off.
    history_context = "\n".join(request.history[-settings.max_history_turns * 2:]) if request.history else "No prior conversation."
    
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

        # The model sometimes emits null/None for extracted_entity on vague
        # input; a null there must not kill the whole classification.
        if not isinstance(result.get("extracted_entity"), str):
            result["extracted_entity"] = str(result.get("extracted_entity") or "unspecified")

        # Confidence is self-reported; missing or out-of-range values fall back
        # to a neutral 0.5 rather than failing the whole classification.
        try:
            confidence = min(1.0, max(0.0, float(result.get("confidence", 0.5))))
        except (TypeError, ValueError):
            confidence = 0.5

        payload = {**result, "confidence": confidence}
        payload["ambiguous"] = bool(result.get("ambiguous", False))
        # Set here rather than inherited: this ran the model, so it is a model
        # judgment. A response body that included its own "confidence_source"
        # must not be able to relabel itself as a keyword match, or a fallback
        # claim as a model score.
        payload["confidence_source"] = "llm"
        return ClassifyResponse(**payload)

    except Exception as e:
        # Fallback to keyword classifier. NOTE: keyword_classify returns a
        # 5-tuple (with confidence) - unpack all five so the keyword match
        # strength survives instead of resetting to the 0.5 default.
        intent, agent, entity, confidence, reasoning = keyword_classify(request.input_text, request.screen_context)
        reasoning += f" (LLM failed: {str(e)[:100]}, using keyword fallback)"
        return ClassifyResponse(
            intent=intent,
            target_agent=agent,
            extracted_entity=entity,
            reasoning=reasoning,
            confidence=confidence,
            confidence_source=keyword_confidence_source(confidence),
            # 0.3 is the keyword classifier's explicit no-match default: the
            # only score low enough to mean "nothing actionable was found".
            ambiguous=confidence <= NO_MATCH_CONFIDENCE,
        )


# One in-flight turn per session: the classify endpoint awaits the LLM
# between reading the history and appending the turn, so two overlapping
# requests for one session (a blind user's natural double-submit while the
# model is slow) both read the same base history and the second write
# overwrote the first - that turn silently vanished from all future LLM
# context. Bounded with the same sweep shape as the rate-limit keys.
_session_turn_locks: "OrderedDict[str, asyncio.Lock]" = OrderedDict()
_SESSION_LOCK_MAX_KEYS = 5000


def session_turn_lock(session_id: str) -> asyncio.Lock:
    lock = _session_turn_locks.get(session_id)
    if lock is None:
        if len(_session_turn_locks) > _SESSION_LOCK_MAX_KEYS:
            for _ in range(500):
                if not _session_turn_locks:
                    break
                _sid, _lk = _session_turn_locks.popitem(last=False)
                if _lk.locked():
                    _session_turn_locks[_sid] = _lk
                    _session_turn_locks.move_to_end(_sid)
        lock = asyncio.Lock()
        _session_turn_locks[session_id] = lock
    return lock


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