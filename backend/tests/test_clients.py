"""Service clients: the outbound calls to the intent engine and agents.

These lock the shared wire contract (URL, payload shape) and the X-Request-ID
tracing propagation, with no sockets involved.
"""
import pytest

from app.services import clients


class _Response:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"Server error: {self.status_code}")

    def json(self):
        return self._payload


class _RecordingClient:
    def __init__(self, captured, response):
        self.captured = captured
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, json=None, headers=None):
        self.captured.append({"url": url, "json": json, "headers": headers})
        return self.response


@pytest.fixture
def capture(monkeypatch):
    def install(payload, status=200):
        calls = []
        client = _RecordingClient(calls, _Response(payload, status))
        monkeypatch.setattr(clients.httpx, "AsyncClient", lambda **kw: client)
        return calls
    return install


async def test_classify_intent_contract(capture, monkeypatch):
    monkeypatch.setattr(clients.settings, "intent_service_url", "http://intent:8001")
    calls = capture({
        "intent": "form_help", "target_agent": "form_agent",
        "extracted_entity": "Aadhaar number field", "reasoning": "stub",
    })

    result = await clients.classify_intent(
        session_id="s1", input_text="what is this?", screen_context="a form", history=["h"])

    assert calls[0]["url"] == "http://intent:8001/intent/classify"
    assert calls[0]["json"] == {
        "session_id": "s1", "input_text": "what is this?",
        "screen_context": "a form", "history": ["h"],
    }
    assert (result.intent, result.target_agent) == ("form_help", "form_agent")
    assert result.extracted_entity == "Aadhaar number field"


async def test_screen_context_none_becomes_empty_string(capture):
    calls = capture({"intent": "general_query", "target_agent": "general_agent",
                     "extracted_entity": "x", "reasoning": "y"})
    await clients.classify_intent(session_id="s", input_text="hi", screen_context=None, history=[])
    assert calls[0]["json"]["screen_context"] == ""


async def test_request_id_is_propagated_for_tracing(capture):
    """Regression: request ids were generated but never forwarded, so a single
    user query could not be followed across the three services."""
    calls = capture({"intent": "general_query", "target_agent": "general_agent",
                     "extracted_entity": "x", "reasoning": "y"})
    await clients.classify_intent(session_id="s", input_text="hi", screen_context="",
                                   history=[], request_id="req-123")
    assert calls[0]["headers"]["X-Request-ID"] == "req-123"


async def test_no_request_id_sends_no_header(capture):
    calls = capture({"intent": "general_query", "target_agent": "general_agent",
                     "extracted_entity": "x", "reasoning": "y"})
    await clients.classify_intent(session_id="s", input_text="hi", screen_context="", history=[])
    assert calls[0]["headers"] == {}


async def test_agent_response_contract(capture, monkeypatch):
    monkeypatch.setattr(clients.settings, "agent_service_url", "http://agents:8002")
    calls = capture({"answer": "do this", "sources_used": ["form_pan_number"],
                     "suggested_action": "highlight_field"})

    result = await clients.get_agent_response(
        session_id="s1", agent="form_agent", query="q", entity="e",
        extra_context="ctx", request_id="req-9")

    assert calls[0]["url"] == "http://agents:8002/agent/respond"
    assert calls[0]["json"] == {
        "session_id": "s1", "agent": "form_agent", "query": "q",
        "entity": "e", "extra_context": "ctx",
    }
    assert calls[0]["headers"]["X-Request-ID"] == "req-9"
    assert result.answer == "do this"
    assert result.sources_used == ["form_pan_number"]
    assert result.suggested_action == "highlight_field"


async def test_upstream_error_propagates(capture):
    """Clients must raise so the route can report 502 - never swallow it."""
    capture({"detail": "boom"}, status=500)
    with pytest.raises(RuntimeError):
        await clients.classify_intent(session_id="s", input_text="hi", screen_context="", history=[])


def test_timeouts_accommodate_real_nim_latency():
    """Regression: a 20s agent budget was shorter than a real NIM completion on
    a long RAG prompt, so /api/query intermittently died with an empty-message
    ReadTimeout."""
    from app.config import Settings
    defaults = Settings(_env_file=None)
    assert defaults.agent_timeout_seconds >= 60, "agent budget must cover real NIM latency"
    assert defaults.intent_timeout_seconds >= 20


async def test_client_uses_configured_agent_timeout(monkeypatch):
    """The configured value must actually reach httpx, not stay a hard-coded literal."""
    seen = {}

    def factory(**kw):
        seen.update(kw)
        return _RecordingClient([], _Response({"answer": "a", "sources_used": [],
                                               "suggested_action": "none"}))

    monkeypatch.setattr(clients.settings, "agent_timeout_seconds", 77.0)
    monkeypatch.setattr(clients.httpx, "AsyncClient", factory)
    await clients.get_agent_response(session_id="s", agent="form_agent", query="q",
                                      entity="e", extra_context="")
    assert seen["timeout"] == 77.0
