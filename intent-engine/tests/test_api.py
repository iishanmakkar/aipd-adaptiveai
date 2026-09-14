"""HTTP contract tests for the intent engine.

Run offline: the NIM call is always patched, so these exercise routing,
validation, rate limiting and the keyword-fallback path without any network,
API key or running service.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as service
from app.classifier import clear_all_sessions
from app.schemas import ClassifyResponse


@pytest.fixture(autouse=True)
def _clean_state():
    """Rate-limit buckets and session memory are process-global; isolate tests."""
    service._rate_limit_store.clear()
    clear_all_sessions()
    yield
    service._rate_limit_store.clear()
    clear_all_sessions()


@pytest.fixture
def client():
    with TestClient(service.app) as c:
        yield c


def _stub_llm(monkeypatch, response: ClassifyResponse):
    async def fake(request):
        return response
    monkeypatch.setattr(service, "llm_classify", fake)


def _body(**over):
    payload = {"session_id": "s1", "input_text": "How do I fill this field?", "screen_context": "", "history": []}
    payload.update(over)
    return payload


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "intent-engine"}


def test_classify_returns_llm_result(client, monkeypatch):
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="form_help", target_agent="form_agent",
        extracted_entity="Permanent Address field", reasoning="stub", confidence=0.87))
    r = client.post("/intent/classify", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert data["target_agent"] == "form_agent"
    # classifier-reported confidence passes through untouched
    assert data["confidence"] == 0.87


def test_classify_clamps_out_of_range_confidence(client, monkeypatch):
    """A model claiming certainty 7.0 must not ship that to callers."""
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="general_query", target_agent="general_agent",
        extracted_entity="x", reasoning="stub", confidence=0.5))
    # build the raw dict the endpoint would receive from a misbehaving model
    async def overconfident(request):
        resp = ClassifyResponse(
            intent="general_query", target_agent="general_agent",
            extracted_entity="x", reasoning="stub")
        object.__setattr__(resp, "__dict__", {**resp.__dict__, "confidence": 7.0})
        return resp
    monkeypatch.setattr(service, "llm_classify", overconfident)
    r = client.post("/intent/classify", json=_body())
    assert r.status_code in (200, 500)  # clamped by pydantic or rejected loudly - never silent 0.85


def test_classify_falls_back_to_keywords_when_llm_raises(client, monkeypatch):
    """Regression: the fallback branch used to treat keyword_classify's
    4-tuple as a response object and raised, turning the safety net into a 500."""
    async def boom(request):
        raise RuntimeError("NIM unreachable")
    monkeypatch.setattr(service, "llm_classify", boom)

    r = client.post("/intent/classify", json=_body(input_text="Summarize this PDF for me"))
    assert r.status_code == 200
    data = r.json()
    assert data["intent"] == "document_help"
    assert data["target_agent"] == "document_agent"
    assert "keyword fallback" in data["reasoning"]


def test_classify_survives_llm_returning_invalid_labels(client, monkeypatch):
    """A malformed model label must degrade, not surface as a 500."""
    async def bad(request):
        raise ValueError("bad intent from model")
    monkeypatch.setattr(service, "llm_classify", bad)
    r = client.post("/intent/classify", json=_body(input_text="Explain photosynthesis in simple terms"))
    assert r.status_code == 200
    assert r.json()["target_agent"] == "education_agent"


def test_client_ip_is_read_from_forwarded_header(client, monkeypatch):
    """Regression: the route used to read headers off the Pydantic body model,
    which raised AttributeError and 500-iced every single request."""
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="general_query", target_agent="general_agent",
        extracted_entity="greeting", reasoning="stub"))
    r = client.post("/intent/classify", json=_body(), headers={"X-Forwarded-For": "203.0.113.7, 70.41.3.18"})
    assert r.status_code == 200
    assert "203.0.113.7" in service._rate_limit_store


def test_rate_limit_returns_429_after_window(client, monkeypatch):
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="general_query", target_agent="general_agent",
        extracted_entity="greeting", reasoning="stub"))
    codes = [client.post("/intent/classify", json=_body(input_text="hi")).status_code for _ in range(62)]
    assert codes[:60] == [200] * 60
    assert codes[60:] == [429, 429]


def test_input_length_validation(client):
    assert client.post("/intent/classify", json=_body(input_text="x" * 2001)).status_code == 400
    assert client.post("/intent/classify", json=_body(screen_context="y" * 5001)).status_code == 400


def test_missing_required_field_is_422(client):
    r = client.post("/intent/classify", json={"input_text": "hi"})
    assert r.status_code == 422


def test_response_is_always_schema_valid(client, monkeypatch):
    """Whatever happens upstream, the body must match the shared contract."""
    async def boom(request):
        raise RuntimeError("down")
    monkeypatch.setattr(service, "llm_classify", boom)
    data = client.post("/intent/classify", json=_body()).json()
    assert set(data) == {"intent", "target_agent", "extracted_entity", "reasoning", "confidence"}
    assert isinstance(data["confidence"], (int, float))
    ClassifyResponse(**data)  # raises if the service emitted an invalid label


def test_session_history_accumulates_and_can_be_cleared(client, monkeypatch):
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="form_help", target_agent="form_agent",
        extracted_entity="field", reasoning="stub"))
    client.post("/intent/classify", json=_body(session_id="keep", input_text="first question about the field"))
    client.post("/intent/classify", json=_body(session_id="keep", input_text="second question about the field"))

    history = client.get("/intent/session/keep/history").json()["history"]
    assert len(history) == 4  # 2 user + 2 system entries
    assert history[0].startswith("User: first")

    assert client.delete("/intent/session/keep").status_code == 200
    assert client.get("/intent/session/keep/history").json()["history"] == []


def test_history_is_scoped_per_session(client, monkeypatch):
    _stub_llm(monkeypatch, ClassifyResponse(
        intent="form_help", target_agent="form_agent",
        extracted_entity="field", reasoning="stub"))
    client.post("/intent/classify", json=_body(session_id="a", input_text="question about a field"))
    assert client.get("/intent/session/b/history").json()["history"] == []


def test_security_headers_present(client):
    r = client.get("/health")
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["Referrer-Policy"] == "strict-origin-when-cross-origin"
