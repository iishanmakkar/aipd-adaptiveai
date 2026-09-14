"""Wire contracts and knowledge-base integrity for the agents service."""
import pytest
from pydantic import ValidationError

from schemas.request import AgentRespondRequest
from schemas.response import AgentRespondResponse


# --- request contract (shared with backend/app/services/clients.py) ---------

def test_valid_request_accepted():
    req = AgentRespondRequest(session_id="s", agent="form_agent", query="q", entity="e")
    assert req.extra_context == ""


@pytest.mark.parametrize("agent", [
    "form_agent", "document_agent", "web_agent", "education_agent", "general_agent",
])
def test_all_five_agents_are_accepted(agent):
    assert AgentRespondRequest(session_id="s", agent=agent, query="q", entity="e").agent == agent


def test_unknown_agent_is_rejected():
    """The intent engine must not be able to route to a non-existent agent."""
    with pytest.raises(ValidationError):
        AgentRespondRequest(session_id="s", agent="sql_agent", query="q", entity="e")


@pytest.mark.parametrize("missing", ["session_id", "agent", "query", "entity"])
def test_required_fields(missing):
    payload = {"session_id": "s", "agent": "form_agent", "query": "q", "entity": "e"}
    payload.pop(missing)
    with pytest.raises(ValidationError):
        AgentRespondRequest(**payload)


def test_response_contract_matches_backend_client():
    resp = AgentRespondResponse(answer="a", sources_used=["d1"], suggested_action="none")
    assert set(resp.model_dump()) == {"answer", "sources_used", "suggested_action"}


# --- knowledge base ---------------------------------------------------------

def test_seed_documents_present_and_unique():
    from rag.seed_data import SEED_DOCUMENTS
    assert len(SEED_DOCUMENTS) == 29
    ids = [d["id"] for d in SEED_DOCUMENTS]
    assert len(set(ids)) == len(ids), "duplicate ids would shadow retrieval results"


def test_every_seed_document_is_searchable():
    """A doc missing text or a category would be indexed but never attributable."""
    from rag.seed_data import SEED_DOCUMENTS
    for doc in SEED_DOCUMENTS:
        assert doc["text"].strip(), doc["id"]
        meta = doc["metadata"]
        assert meta.get("category") in {
            "form_glossary", "accessibility_faq",
            "education_concepts", "document_guides", "web_navigation",
        }, doc["id"]
        assert meta.get("field") or meta.get("topic"), doc["id"]


def test_seed_covers_every_agent_domain():
    """Each agent must own grounding documents - education_agent answering from
    unrelated accessibility FAQs is what 'the KB has no education docs' looked
    like in production."""
    from rag.seed_data import SEED_DOCUMENTS
    cats = {d["metadata"]["category"] for d in SEED_DOCUMENTS}
    assert cats == {"form_glossary", "accessibility_faq",
                    "education_concepts", "document_guides", "web_navigation"}


def test_initialize_is_idempotent(store):
    """Without the guard, every restart would re-add 20 docs and skew ranking."""
    from rag.seed_data import SEED_DOCUMENTS, initialize_knowledge_base
    assert initialize_knowledge_base(store) == len(SEED_DOCUMENTS)
    assert initialize_knowledge_base(store) == 0
    assert store.count() == len(SEED_DOCUMENTS)
