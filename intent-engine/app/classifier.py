import json
from typing import Dict, List, Tuple
from openai import AsyncOpenAI

from app.config import settings
from app.schemas import ClassifyRequest, ClassifyResponse

# In-memory session context store
_session_memory: Dict[str, List[str]] = {}


# Keyword-based fallback classifier
KEYWORD_RULES = [
    # (keywords, intent, target_agent, entity_hint)
    # Order matters: more common/intents first per master spec
    (["fill", "form", "field", "input", "submit", "application", "register", "signup", "what is this field", "how to fill", "field asking"],
     "form_help", "form_agent", "form field"),
    (["document", "pdf", "read", "summarize", "summary", "extract", "contract", "agreement", "terms", "policy", "document content"],
     "document_help", "document_agent", "document content"),
    (["explain", "learn", "study", "concept", "topic", "course", "lesson", "tutorial", "what is", "define", "meaning", "concept"],
     "education_help", "education_agent", "educational concept"),
    (["navigate", "website", "page", "click", "button", "link", "menu", "navigation", "find", "where is", "how to get to", "go to"],
     "web_navigation_help", "web_agent", "web element"),
]


def keyword_classify(text: str, screen_context: str = "") -> Tuple[str, str, str, str]:
    """Simple keyword-based classification fallback."""
    text_lower = text.lower()
    combined = f"{text_lower} {screen_context.lower()}"
    
    for keywords, intent, agent, entity_hint in KEYWORD_RULES:
        if any(kw in combined for kw in keywords):
            # Try to extract more specific entity
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
            return intent, agent, entity, reasoning
    
    # Default fallback
    return "general_query", "general_agent", "general question", "No specific intent keywords matched, defaulting to general query"


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
  "reasoning": "brief explanation of why this classification was chosen"
}"""


async def llm_classify(request: ClassifyRequest) -> ClassifyResponse:
    """Classify using LLM via NVIDIA NIM (OpenAI-compatible)."""
    client = AsyncOpenAI(base_url=settings.nim_base_url, api_key=settings.nim_api_key)
    
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
        
        return ClassifyResponse(**result)
        
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
    """Get conversation history for a session."""
    return _session_memory.get(session_id, [])


def add_to_history(session_id: str, user_input: str, classification: ClassifyResponse):
    """Add user input and classification to session history."""
    if session_id not in _session_memory:
        _session_memory[session_id] = []
    
    # Keep only last N turns (user + system pairs)
    history = _session_memory[session_id]
    history.append(f"User: {user_input}")
    history.append(f"System: Classified as {classification.intent} ({classification.target_agent}) - {classification.extracted_entity}")
    
    # Trim to max_turns * 2 (user + system pairs)
    max_items = settings.max_history_turns * 2
    if len(history) > max_items:
        _session_memory[session_id] = history[-max_items:]


def clear_session(session_id: str):
    """Clear session history."""
    if session_id in _session_memory:
        del _session_memory[session_id]