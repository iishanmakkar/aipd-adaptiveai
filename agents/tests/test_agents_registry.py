"""Agent wiring: registry, prompts, suggested actions, concurrency."""
import asyncio
import time

import pytest

from tests.conftest import StubLLM
from llm.prompts import (
    DOCUMENT_AGENT_PROMPT,
    EDUCATION_AGENT_PROMPT,
    FORM_AGENT_PROMPT,
    GENERAL_AGENT_PROMPT,
    WEB_AGENT_PROMPT,
)
from rag.seed_data import SEED_DOCUMENTS


@pytest.fixture
def seeded(store):
    store.add_documents(SEED_DOCUMENTS)
    return store


@pytest.fixture
def registry(store, seeded):
    from agents.registry import AgentRegistry
    from rag.retriever import Retriever
    return AgentRegistry(Retriever(), StubLLM())


def test_registry_exposes_all_five_agents(registry):
    assert set(registry.get_all_names()) == {
        "form_agent", "document_agent", "web_agent", "education_agent", "general_agent",
    }


def test_unknown_agent_returns_none(registry):
    assert registry.get("sql_agent") is None


@pytest.mark.parametrize("name,prompt", [
    ("form_agent", FORM_AGENT_PROMPT),
    ("document_agent", DOCUMENT_AGENT_PROMPT),
    ("web_agent", WEB_AGENT_PROMPT),
    ("education_agent", EDUCATION_AGENT_PROMPT),
    ("general_agent", GENERAL_AGENT_PROMPT),
])
def test_each_agent_uses_its_own_prompt(registry, name, prompt):
    assert registry.get(name).system_prompt_template == prompt
    assert prompt.strip(), f"{name} has an empty system prompt"


def test_prompts_are_distinct():
    prompts = {FORM_AGENT_PROMPT, DOCUMENT_AGENT_PROMPT, WEB_AGENT_PROMPT,
               EDUCATION_AGENT_PROMPT, GENERAL_AGENT_PROMPT}
    assert len(prompts) == 5, "two agents share a prompt - routing to them would be pointless"


async def test_handle_retrieves_grounding_sources(registry, seeded):
    result = await registry.get("form_agent").handle(
        "What is the aadhaar number field?", "Aadhaar number", "")
    assert result["sources_used"], "answer must be RAG-grounded, not ungrounded"
    assert "form_aadhar_number" in result["sources_used"]
    assert result["answer"] == "stubbed answer"


async def test_prompt_reaches_llm_with_context(registry, seeded):
    llm = StubLLM()
    from agents.registry import AgentRegistry
    from rag.retriever import Retriever
    reg = AgentRegistry(Retriever(), llm)

    await reg.get("form_agent").handle("What is the aadhaar number field?", "Aadhaar number", "form open")

    messages = llm.calls[0]
    assert messages[0]["role"] == "system"
    assert "Aadhaar number" in messages[1]["content"]
    assert "form open" in messages[1]["content"]
    assert "Retrieved Knowledge" in messages[1]["content"]


async def test_suggested_actions_are_intent_specific(registry, seeded):
    form = registry.get("form_agent")
    assert form._get_suggested_action("where is this field?", "x") == "highlight_field"
    assert form._get_suggested_action("give me an example", "x") == "show_example"
    assert form._get_suggested_action("what does this mean?", "x") == "none"


@pytest.mark.parametrize("name", [
    "form_agent", "document_agent", "web_agent", "education_agent", "general_agent",
])
async def test_every_agent_answers_end_to_end(registry, seeded, name):
    result = await registry.get(name).handle("what is the aadhaar number field", "Aadhaar", "")
    assert set(result) == {"answer", "sources_used", "suggested_action"}


async def test_sync_llm_does_not_block_the_event_loop(registry, seeded):
    """Regression: LLM.chat and embedding inference are blocking calls. Run on
    the event loop they serialise every concurrent user, so they must be
    offloaded to threads."""
    class SlowLLM:
        def chat(self, messages):
            time.sleep(0.4)  # deliberately blocking, like the real HTTP client
            return "done"

    from agents.registry import AgentRegistry
    from rag.retriever import Retriever
    reg = AgentRegistry(Retriever(), SlowLLM())
    agent = reg.get("form_agent")

    start = time.perf_counter()
    await asyncio.gather(*(agent.handle("aadhaar number", "e", "") for _ in range(3)))
    elapsed = time.perf_counter() - start

    # Serial would be >= 1.2s; offloaded should be close to a single 0.4s call.
    assert elapsed < 0.9, f"3 concurrent requests took {elapsed:.2f}s - calls are serialising"
