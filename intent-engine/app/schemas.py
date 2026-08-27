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