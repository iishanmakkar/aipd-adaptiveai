"""Locks the B1 prompt hardening offline: every agent prompt must carry its
bare-noun / no-document / vague-input instruction, so a future edit cannot
silently drop the anti-hedge rule this round proved live (15/15 after)."""
from llm import prompts


def test_form_prompt_has_bare_noun_rule():
    assert "BARE-NOUN RULE" in prompts.FORM_AGENT_PROMPT
    assert "Never hedge" in prompts.FORM_AGENT_PROMPT


def test_document_prompt_has_no_document_rule():
    assert "NO-DOCUMENT RULE" in prompts.DOCUMENT_AGENT_PROMPT
    assert "Never" in prompts.DOCUMENT_AGENT_PROMPT and "summarize the instructions" in prompts.DOCUMENT_AGENT_PROMPT


def test_web_prompt_has_bare_noun_rule():
    assert "BARE-NOUN RULE" in prompts.WEB_AGENT_PROMPT


def test_education_prompt_has_bare_noun_rule():
    assert "BARE-NOUN RULE" in prompts.EDUCATION_AGENT_PROMPT


def test_general_prompt_has_vague_input_rule():
    assert "VAGUE-INPUT RULE" in prompts.GENERAL_AGENT_PROMPT
    assert "clarifying question" in prompts.GENERAL_AGENT_PROMPT
