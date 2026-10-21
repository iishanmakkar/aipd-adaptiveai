"""Provenance must survive the hop from the intent engine to the caller.

The engine can now say whether a confidence came from the model or from keyword
scoring; that is only useful if the number the UI quotes carries the same
statement. Paths that report a constant or a carried-over value answer "unknown"
rather than implying a model judged them.
"""
import pytest

import app.api.routes_query as rq
from app.services.clients import AgentResponse, IntentResponse


async def _fake_intent(**kwargs):
    return IntentResponse(intent="form_help", target_agent="form_agent",
                          extracted_entity="the name field", reasoning="r",
                          confidence=0.7, confidence_source="keyword")


async def _fake_agent(**kwargs):
    return AgentResponse(answer="Sure - here is how.", sources_used=[],
                         suggested_action="none")


@pytest.fixture(autouse=True)
def _stub_services(monkeypatch):
    monkeypatch.setattr(rq, "classify_intent", _fake_intent)
    monkeypatch.setattr(rq, "get_agent_response", _fake_agent)


def test_query_demo_carries_confidence_provenance(client):
    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "help me fill the name field",
        "input_source": "text", "screen_context": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["confidence"] == pytest.approx(0.7)
    assert body["confidence_source"] == "keyword"


def test_intent_client_reports_unknown_when_the_field_is_absent():
    """An older intent engine response without the field must not be upgraded to
    "llm" by assumption."""
    from app.services import clients

    data = {"intent": "form_help", "target_agent": "form_agent",
            "extracted_entity": "x", "reasoning": "r", "confidence": 0.9}
    inferred = clients.IntentResponse(**{
        "intent": data["intent"], "target_agent": data["target_agent"],
        "extracted_entity": data["extracted_entity"], "reasoning": data["reasoning"],
        "confidence": data["confidence"]})
    assert inferred.confidence_source == "unknown"


def test_query_response_defaults_to_unknown_not_llm():
    from app.schemas.query import QueryResponse

    resp = QueryResponse(response_text="x", agent_used="form_agent", confidence=0.9)
    assert resp.confidence_source == "unknown"
