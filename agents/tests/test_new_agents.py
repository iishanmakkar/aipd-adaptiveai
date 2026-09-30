"""New specialists: routing, contracts, grounding (offline, stubbed LLM)."""
import pytest

from tests.conftest import StubLLM


def test_scheduler_and_translator_route():
    from agents.orchestrator import keyword_route
    assert keyword_route("schedule my dentist appointment tomorrow") == "scheduler_agent"
    assert keyword_route("plan my day with reminders") == "scheduler_agent"
    assert keyword_route("translate this letter in Hindi") == "translator_agent"
    assert keyword_route("translation in Tamil please") == "translator_agent"


def test_new_agents_expose_actions_and_prompts(store):
    from agents.registry import AgentRegistry
    from rag.retriever import Retriever
    from rag.seed_data import SEED_DOCUMENTS
    store.add_documents(SEED_DOCUMENTS)
    reg = AgentRegistry(Retriever(), StubLLM())
    assert reg.get("scheduler_agent")._get_suggested_action("anything", "x") == "plan_schedule"
    assert reg.get("translator_agent")._get_suggested_action("anything", "x") == "read_translation"
    assert reg.get("scheduler_agent").system_prompt_template.strip()
    assert reg.get("translator_agent").system_prompt_template.strip()


@pytest.mark.parametrize("name,query", [
    ("scheduler_agent", "schedule my doctor appointment and remind me"),
    ("translator_agent", "translate this notice in Hindi"),
])
async def test_new_agents_answer_end_to_end(store, name, query):
    from agents.registry import AgentRegistry
    from rag.retriever import Retriever
    from rag.seed_data import SEED_DOCUMENTS
    store.add_documents(SEED_DOCUMENTS)
    reg = AgentRegistry(Retriever(), StubLLM("stubbed answer"))
    result = await reg.get(name).handle(query, "e", "")
    assert set(result) == {"answer", "sources_used", "suggested_action"}
    assert result["sources_used"]


def test_new_seed_docs_ground_new_agents(store):
    from rag.seed_data import SEED_DOCUMENTS
    store.add_documents(SEED_DOCUMENTS)
    from rag.retriever import Retriever
    r = Retriever()
    sched = r.retrieve("schedule my appointment with a calendar reminder")
    assert any(d["id"].startswith("sched_") for d in sched)
    trans = r.retrieve("translate this text in Hindi translation")
    assert any(d["id"].startswith("trans_") for d in trans)
