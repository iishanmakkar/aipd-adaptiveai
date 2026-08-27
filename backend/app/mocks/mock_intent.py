"""
Mock Intent & Context Engine Service
Runs on port 8001
Returns realistic intent classifications for demo/development
"""
from fastapi import FastAPI
from pydantic import BaseModel
from typing import Optional

app = FastAPI(title="Mock Intent Service")


class ClassifyRequest(BaseModel):
    session_id: str
    input_text: str
    screen_context: str = ""
    history: list[str] = []


class ClassifyResponse(BaseModel):
    intent: str
    target_agent: str
    extracted_entity: str
    reasoning: str


# Intent classification rules (keyword-based fallback)
INTENT_RULES = [
    # form_help
    (["fill", "form", "field", "input", "submit", "application", "register", "signup", "what is this field", "how to fill"],
     "form_help", "form_agent"),
    # document_help
    (["document", "pdf", "read", "summarize", "summary", "extract", "contract", "agreement", "terms", "policy"],
     "document_help", "document_agent"),
    # web_navigation_help
    (["navigate", "website", "page", "click", "button", "link", "menu", "navigation", "find", "where is", "how to get to"],
     "web_navigation_help", "web_agent"),
    # education_help
    (["explain", "learn", "study", "concept", "topic", "course", "lesson", "tutorial", "what is", "define", "meaning"],
     "education_help", "education_agent"),
]


def classify_text(text: str) -> tuple[str, str, str]:
    """Simple keyword-based classification."""
    text_lower = text.lower()
    
    for keywords, intent, agent in INTENT_RULES:
        if any(kw in text_lower for kw in keywords):
            # Extract entity - simple heuristic
            entity = ""
            if "field" in text_lower:
                entity = "form field"
            elif "document" in text_lower or "pdf" in text_lower:
                entity = "document content"
            elif "button" in text_lower or "link" in text_lower:
                entity = "web element"
            elif "concept" in text_lower or "topic" in text_lower:
                entity = "educational concept"
            
            reasoning = f"Matched keywords for {intent}: user is asking about {entity or 'general topic'}"
            return intent, agent, entity, reasoning
    
    # Default
    return "general_query", "general_agent", "general question", "No specific intent matched, treating as general query"


@app.post("/intent/classify", response_model=ClassifyResponse)
async def classify_intent(request: ClassifyRequest):
    intent, target_agent, entity, reasoning = classify_text(request.input_text)
    
    # Override with context if available
    if request.screen_context:
        if "form" in request.screen_context.lower() and intent == "general_query":
            intent, target_agent, entity = "form_help", "form_agent", "form field"
            reasoning = "Screen context shows a form, reclassifying as form_help"
        elif "document" in request.screen_context.lower() and intent == "general_query":
            intent, target_agent, entity = "document_help", "document_agent", "document content"
            reasoning = "Screen context shows a document, reclassifying as document_help"
    
    return ClassifyResponse(
        intent=intent,
        target_agent=target_agent,
        extracted_entity=entity,
        reasoning=reasoning
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": "mock-intent"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)