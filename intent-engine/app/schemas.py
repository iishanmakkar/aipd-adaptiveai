from pydantic import BaseModel, Field
from typing import Optional, List


class ClassifyRequest(BaseModel):
    session_id: str
    input_text: str
    screen_context: str = ""
    history: List[str] = []


class ClassifyResponse(BaseModel):
    intent: str = Field(pattern="^(form_help|document_help|web_navigation_help|education_help|general_query)$")
    target_agent: str = Field(pattern="^(form_agent|document_agent|web_agent|education_agent|general_agent)$")
    extracted_entity: str
    reasoning: str
    # Self-assessed by the LLM, or computed from keyword-match strength when
    # the LLM is unreachable. Replaces the old hardcoded 0.85 the backend sent.
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)