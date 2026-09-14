"""HTTP contract for the agents service (offline: stubbed embedder + LLM)."""
import pytest

from tests.conftest import StubLLM


@pytest.fixture
def client(monkeypatch, stub_embeddings, tmp_path):
    import main as agents_main
    from config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "api-vs"))

    class FakeLLMClient(StubLLM):
        def __init__(self, *a, **k):
            super().__init__("grounded stub answer")

    monkeypatch.setattr(agents_main, "LLMClient", FakeLLMClient)

    from fastapi.testclient import TestClient
    with TestClient(agents_main.app) as c:
        yield c


def _body(**over):
    payload = {"session_id": "s1", "agent": "form_agent",
               "query": "What is the aadhaar number field?", "entity": "Aadhaar number",
               "extra_context": ""}
    payload.update(over)
    return payload


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "agents"


def test_agents_listing(client):
    data = client.get("/agents").json()["agents"]
    assert len(data) == 5


def test_respond_returns_the_shared_contract(client):
    r = client.post("/agent/respond", json=_body())
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"answer", "sources_used", "suggested_action"}
    assert data["answer"] == "grounded stub answer"


def test_respond_is_rag_grounded(client):
    """Sources must name real knowledge-base documents, proving retrieval ran."""
    data = client.post("/agent/respond", json=_body()).json()
    assert "form_aadhar_number" in data["sources_used"]


def test_knowledge_base_is_seeded_on_startup(client):
    """29 docs means seeding happened exactly once (the idempotency guard)."""
    from rag.vector_store import VectorStore
    assert VectorStore().count() == 29


@pytest.mark.parametrize("agent", [
    "form_agent", "document_agent", "web_agent", "education_agent", "general_agent",
])
def test_all_agents_respond_over_http(client, agent):
    r = client.post("/agent/respond", json=_body(agent=agent, query="what is the aadhaar number field?"))
    assert r.status_code == 200
    assert r.json()["sources_used"]


def test_unknown_agent_is_rejected_before_handling(client):
    """The Literal schema rejects this, so a typo from the intent engine can
    never reach an arbitrary code path."""
    r = client.post("/agent/respond", json=_body(agent="sql_agent"))
    assert r.status_code == 422


def test_missing_field_is_422(client):
    body = _body()
    body.pop("query")
    assert client.post("/agent/respond", json=body).status_code == 422


def test_llm_failure_surfaces_as_500_not_a_fake_answer(client, monkeypatch):
    import main as agents_main

    broken = StubLLM()

    def boom(messages):
        raise RuntimeError("NIM unreachable")
    broken.chat = boom

    agent = agents_main.agent_registry.get("form_agent")
    agent.llm = broken

    r = client.post("/agent/respond", json=_body())
    assert r.status_code == 500
    assert "Agent error" in r.json()["detail"]
