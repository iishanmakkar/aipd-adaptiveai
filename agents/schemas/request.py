from pydantic import BaseModel, Field, field_validator
from typing import Literal


class AgentRespondRequest(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    agent: Literal["form_agent", "document_agent", "web_agent", "education_agent", "general_agent", "ui_adjuster_agent", "content_explainer_agent", "profile_updater_agent", "navigation_agent", "scheduler_agent", "translator_agent"] = Field(
        ..., description="Target agent to handle the query"
    )
    # Bounded: raw query/entity flow into both the retrieval query and the
    # prompt twice (system + user turn); unbounded, a 1MB query reached
    # NIM as a multi-MB prompt and 500'd or burned tokens per call.
    query: str = Field(..., max_length=4000, description="User's question or request")
    entity: str = Field(..., max_length=1000, description="Specific entity/field/concept being asked about")
    extra_context: str = Field(default="", max_length=8000, description="Additional context (screen description, document text, etc.)")

    @field_validator("query")
    @classmethod
    def _non_blank_query(cls, value: str) -> str:
        # A blank query would burn retrieval + an LLM call on nothing (and
        # 500'd offline before this guard existed).
        if not value.strip():
            raise ValueError("query must not be blank")
        return value


class OrchestrateRequest(BaseModel):
    session_id: str = Field(..., description="Unique session identifier")
    goal: str = Field(..., min_length=1, max_length=4000, description="Natural-language goal to plan + execute")
    entity: str = Field(default="", description="Optional entity hint")
    extra_context: str = Field(default="", max_length=8000, description="Optional unified/page context")

    @field_validator("goal")
    @classmethod
    def _non_blank_goal(cls, value: str) -> str:
        # min_length=1 lets "   " through; an empty goal would burn an LLM
        # planning call on nothing.
        if not value.strip():
            raise ValueError("goal must not be blank")
        return value