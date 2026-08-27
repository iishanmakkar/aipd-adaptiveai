from pydantic import BaseModel, Field
from typing import Literal


class QueryRequest(BaseModel):
    session_id: str
    input_text: str
    input_source: Literal["voice", "text"] = "text"
    screen_context: str | None = None


class QueryResponse(BaseModel):
    response_text: str
    agent_used: str
    suggested_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)