import httpx
from app.config import settings
from app.schemas.query import QueryRequest


class IntentResponse:
    def __init__(self, intent: str, target_agent: str, extracted_entity: str, reasoning: str):
        self.intent = intent
        self.target_agent = target_agent
        self.extracted_entity = extracted_entity
        self.reasoning = reasoning


class AgentResponse:
    def __init__(self, answer: str, sources_used: list[str], suggested_action: str):
        self.answer = answer
        self.sources_used = sources_used
        self.suggested_action = suggested_action


async def classify_intent(
    session_id: str,
    input_text: str,
    screen_context: str | None,
    history: list[str],
    request_id: str | None = None,
) -> IntentResponse:
    # REAL MODE: direct call to Intent Engine (no mock fallback - 100% real), propagate X-Request-ID
    headers = {}
    if request_id:
        headers["X-Request-ID"] = request_id
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            f"{settings.intent_service_url}/intent/classify",
            json={
                "session_id": session_id,
                "input_text": input_text,
                "screen_context": screen_context or "",
                "history": history
            },
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return IntentResponse(**data)


async def get_agent_response(
    session_id: str,
    agent: str,
    query: str,
    entity: str,
    extra_context: str,
    request_id: str | None = None,
) -> AgentResponse:
    # REAL MODE: direct call to Agents RAG service (no mock fallback - 100% real), propagate X-Request-ID
    headers = {}
    if request_id:
        headers["X-Request-ID"] = request_id
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{settings.agent_service_url}/agent/respond",
            json={
                "session_id": session_id,
                "agent": agent,
                "query": query,
                "entity": entity,
                "extra_context": extra_context
            },
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        return AgentResponse(**data)