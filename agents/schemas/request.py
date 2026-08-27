from pydantic import BaseModel, Field
from typing import Literal


class AgentRespondRequest(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    agent: Literal["form_agent", "document_agent", "web_agent", "education_agent", "general_agent"] = Field(
        ..., description="Target agent to handle the query"
    )
    query: str = Field(..., description="User's question or request")
    entity: str = Field(..., description="Specific entity/field/concept being asked about")
    extra_context: str = Field(default="", description="Additional context (screen description, document text, etc.)")