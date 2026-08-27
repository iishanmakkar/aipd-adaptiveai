from pydantic import BaseModel, Field
from typing import List


class AgentRespondResponse(BaseModel):
    answer: str = Field(..., description="The generated answer from the agent")
    sources_used: List[str] = Field(default_factory=list, description="List of source document IDs used")
    suggested_action: str = Field(default="none", description="Suggested follow-up action for the frontend")