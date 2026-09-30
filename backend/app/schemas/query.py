from pydantic import BaseModel, Field, field_validator
from typing import Literal


class UnifiedContext(BaseModel):
    """Phase 2.2 — one fused context object replacing the bare screen_ctx string."""
    screen_text: str = ""
    dom_snapshot: str = ""
    screenshot_b64: str | None = None
    vlm_description: str | None = None
    user_intent: str | None = None
    disability_profile: str = "none"

    def flattened(self) -> str:
        parts = []
        if self.screen_text:
            parts.append(f"Screen text: {self.screen_text[:4000]}")
        if self.dom_snapshot:
            parts.append(f"DOM: {self.dom_snapshot[:4000]}")
        if self.vlm_description:
            parts.append(f"Vision: {self.vlm_description[:2000]}")
        if self.user_intent:
            parts.append(f"Intent: {self.user_intent}")
        return "\n".join(parts)


class QueryRequest(BaseModel):
    session_id: str
    input_text: str = Field(..., min_length=1)
    input_source: Literal["voice", "text"] = "text"
    screen_context: str | None = None
    unified_context: UnifiedContext | None = None
    # Phase 2.1: route via POST /agent/orchestrate (goal -> plan -> specialist)
    # instead of the intent classifier's single target agent. Browser intents
    # always keep the confirm-gated live-session path regardless of this flag.
    autonomous: bool = False

    @field_validator("input_text")
    @classmethod
    def _non_blank_input(cls, value: str) -> str:
        # min_length=1 lets "   " through; blank input would burn an intent
        # LLM call plus an agent call on nothing.
        if not value.strip():
            raise ValueError("input_text must not be blank")
        return value


class QueryResponse(BaseModel):
    response_text: str
    agent_used: str
    suggested_action: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    # Knowledge-base documents that grounded this answer (from the RAG layer),
    # surfaced so the UI can show *why* an answer can be trusted.
    sources_used: list[str] = []