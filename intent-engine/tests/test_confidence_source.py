"""Confidence must carry its provenance.

When the LLM is unreachable the classifier scores keywords and computes
`min(0.9, 0.4 + 0.1 * score)`. That number is not a model judgment, but it
travelled to the UI in the same field as a model's self-assessment, so a keyword
hit could be quoted as "conf 0.9" evidence. The fallback itself is honest and
useful; only the missing label was the problem.
"""
import pytest
from fastapi.testclient import TestClient

import app.main as service
from app.schemas import ClassifyRequest, ClassifyResponse


@pytest.fixture(autouse=True)
def _clean_state():
    service._rate_limit_store.clear()
    yield
    service._rate_limit_store.clear()


@pytest.fixture
def client():
    with TestClient(service.app) as c:
        yield c


def payload(text, session="s1"):
    return {"session_id": session, "input_text": text,
            "screen_context": "", "history": []}


def _llm_down(monkeypatch):
    async def boom(request):
        raise RuntimeError("NIM unreachable")
    monkeypatch.setattr(service, "llm_classify", boom)


def test_endpoint_labels_keyword_fallback_confidence(client, monkeypatch):
    _llm_down(monkeypatch)
    r = client.post("/intent/classify", json=payload("help me fill the form field input"))
    assert r.status_code == 200
    body = r.json()
    assert body["confidence_source"] == "keyword"
    assert body["confidence"] >= 0.4


def test_endpoint_labels_the_no_match_default(client, monkeypatch):
    _llm_down(monkeypatch)
    r = client.post("/intent/classify", json=payload("zzz qqq blorp nothing"))
    body = r.json()
    assert body["confidence_source"] == "default"
    assert body["confidence"] == pytest.approx(0.3)
    assert body["ambiguous"] is True


def test_llm_path_declares_a_model_self_assessment(client, monkeypatch):
    async def fake(request):
        return ClassifyResponse(intent="form_help", target_agent="form_agent",
                                extracted_entity="x", reasoning="r", confidence=0.92)
    monkeypatch.setattr(service, "llm_classify", fake)
    r = client.post("/intent/classify", json=payload("fill my aadhaar field"))
    assert r.json()["confidence_source"] == "llm"


@pytest.mark.asyncio
async def test_classifier_internal_fallback_is_not_reported_as_llm(monkeypatch):
    """llm_classify has its OWN keyword fallback inside the except block. It must
    not return a keyword score carrying the default 'llm' label."""
    from app import classifier

    class _Boom:
        def __init__(self, *a, **k):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(*a, **k):
                    raise RuntimeError("NIM unreachable")

    monkeypatch.setattr(classifier, "AsyncOpenAI", _Boom)
    out = await classifier.llm_classify(ClassifyRequest(
        session_id="s", input_text="help me fill the form field input",
        screen_context="", history=[]))
    assert out.confidence_source == "keyword"
    assert out.confidence >= 0.4


@pytest.mark.asyncio
async def test_model_payload_cannot_claim_its_own_source(monkeypatch):
    """The source is set by the code that knows which path ran, not taken from
    model output - a model that replies {"confidence_source": "keyword"} must not
    be able to relabel itself. llm_classify parses
    `response.choices[0].message.content` as JSON, so the fake is shaped that way
    rather than guessed at."""
    from app import classifier

    content = ('{"intent": "form_help", "target_agent": "form_agent", '
               '"extracted_entity": "x", "reasoning": "r", "confidence": 0.9, '
               '"confidence_source": "keyword"}')
    msg = type("M", (), {"content": content})()
    choice = type("C", (), {"message": msg})()
    reply = type("R", (), {"choices": [choice]})()

    class _Ok:
        def __init__(self, *a, **k):
            pass

        class chat:
            class completions:
                @staticmethod
                async def create(*a, **k):
                    return reply

    monkeypatch.setattr(classifier, "AsyncOpenAI", _Ok)
    out = await classifier.llm_classify(ClassifyRequest(
        session_id="s", input_text="fill my aadhaar field", screen_context="", history=[]))
    assert out.confidence_source == "llm"
    assert out.confidence == pytest.approx(0.9)
