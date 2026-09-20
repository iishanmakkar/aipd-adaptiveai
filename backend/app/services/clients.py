import httpx
from app.config import settings
from app.schemas.query import QueryRequest


class IntentResponse:
    def __init__(self, intent: str, target_agent: str, extracted_entity: str, reasoning: str,
                 confidence: float = 0.5):
        self.intent = intent
        self.target_agent = target_agent
        self.extracted_entity = extracted_entity
        self.reasoning = reasoning
        # Classifier-reported certainty (LLM self-assessment or keyword-match
        # strength). The API used to send a hardcoded 0.85 for every answer.
        self.confidence = confidence


class AgentResponse:
    def __init__(self, answer: str, sources_used: list[str], suggested_action: str):
        self.answer = answer
        self.sources_used = sources_used
        self.suggested_action = suggested_action


def _browser_headers(request_id: str | None) -> dict:
    headers = {}
    if request_id:
        headers["X-Request-ID"] = request_id
    return headers


async def _browser_post(path: str, payload: dict, request_id: str | None = None):
    """POST to the browser-agent session API. HTTP errors propagate so the
    route can report honest 502/409/423/429 statuses to the user."""
    async with httpx.AsyncClient(timeout=settings.browser_timeout_seconds) as client:
        response = await client.post(
            f"{settings.browser_service_url}{path}",
            json=payload,
            headers=_browser_headers(request_id),
        )
        response.raise_for_status()
        return response.json()


async def _browser_get(path: str, request_id: str | None = None):
    async with httpx.AsyncClient(timeout=settings.browser_timeout_seconds) as client:
        response = await client.get(
            f"{settings.browser_service_url}{path}",
            headers=_browser_headers(request_id),
        )
        response.raise_for_status()
        return response.json()


async def browser_open_session(session_id: str, url: str,
                               request_id: str | None = None) -> dict:
    return await _browser_post("/session/open",
                               {"session_id": session_id, "url": url}, request_id)


async def browser_navigate(session_id: str, url: str,
                           request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/navigate",
                               {"url": url}, request_id)


async def browser_inspect(session_id: str, target: str,
                          request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/inspect",
                               {"target": target}, request_id)


async def browser_act(session_id: str, kind: str, label: str | None = None,
                      selector: str | None = None, value: str = "",
                      request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/act",
                               {"kind": kind, "label": label,
                                "selector": selector, "value": value}, request_id)


async def browser_confirm(session_id: str, proposal_id: str,
                          request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/confirm",
                               {"proposal_id": proposal_id}, request_id)


async def browser_snapshot(session_id: str, request_id: str | None = None) -> dict:
    return await _browser_get(f"/session/{session_id}/snapshot", request_id)


async def browser_monitor_start(session_id: str, requested_by: str = "voice",
                                request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/monitor/start",
                               {"requested_by": requested_by}, request_id)


async def browser_monitor_stop(session_id: str,
                               request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/monitor/stop", {}, request_id)


async def browser_monitor_interrupt(session_id: str,
                                    request_id: str | None = None) -> dict:
    return await _browser_post(f"/session/{session_id}/monitor/interrupt", {}, request_id)


async def browser_monitor_status(session_id: str,
                                 request_id: str | None = None) -> dict:
    return await _browser_get(f"/session/{session_id}/monitor/status", request_id)


async def browser_monitor_narrations(session_id: str, since: int = 0,
                                     request_id: str | None = None) -> dict:
    return await _browser_get(
        f"/session/{session_id}/monitor/narrations?since={int(since)}", request_id)


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
    async with httpx.AsyncClient(timeout=settings.intent_timeout_seconds) as client:
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
    async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
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