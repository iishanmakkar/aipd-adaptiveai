"""Offline unit tests for the keyword fallback classifier.

These need no network, no NIM key and no running service, so they are the
regression net for the degradation path: when the LLM is unreachable this is
the only thing standing between the user and a wrong agent.
"""
import pytest

from app.classifier import KEYWORD_RULES, keyword_classify
from cases import BROWSER_CASES, CONTEXT_TEST_CASES, TEST_CASES

VALID_INTENTS = {"form_help", "document_help", "web_navigation_help", "education_help",
                 "general_query", "browser_inspect", "browser_act",
                 "scheduler_help", "translation_help", "ui_help",
                 "content_explain", "profile_update", "navigation_help"}
VALID_AGENTS = {"form_agent", "document_agent", "web_agent", "education_agent",
                "general_agent", "browser_agent",
                "scheduler_agent", "translator_agent", "ui_adjuster_agent",
                "content_explainer_agent", "profile_updater_agent", "navigation_agent"}
AGENT_FOR_INTENT = {
    "form_help": "form_agent",
    "document_help": "document_agent",
    "web_navigation_help": "web_agent",
    "education_help": "education_agent",
    "general_query": "general_agent",
    "browser_inspect": "browser_agent",
    "browser_act": "browser_agent",
    "scheduler_help": "scheduler_agent",
    "translation_help": "translator_agent",
    "ui_help": "ui_adjuster_agent",
    "content_explain": "content_explainer_agent",
    "profile_update": "profile_updater_agent",
    "navigation_help": "navigation_agent",
}


@pytest.mark.parametrize("text,expected_intent,expected_agent", TEST_CASES)
def test_keyword_fallback_classifies_every_case(text, expected_intent, expected_agent):
    """Every documented case must route correctly on keywords alone (20/20)."""
    intent, agent, _entity, _confidence, _reasoning = keyword_classify(text)
    assert (intent, agent) == (expected_intent, expected_agent), (
        f"'{text}' routed to {intent}/{agent}, expected {expected_intent}/{expected_agent}"
    )


@pytest.mark.parametrize("text,expected_intent,expected_agent,context", CONTEXT_TEST_CASES)
def test_keyword_fallback_uses_screen_context(text, expected_intent, expected_agent, context):
    """Bare follow-ups resolve against what is on screen."""
    intent, agent, _entity, _confidence, _reasoning = keyword_classify(text, context)
    assert (intent, agent) == (expected_intent, expected_agent)


def test_input_matches_outrank_context_matches():
    """The user's own words beat screen noise: 'submit' in context must not
    pull a pure web-navigation question into the form agent."""
    intent, agent, _, _, _ = keyword_classify(
        "Where is the submit button on this page?", ""
    )
    assert (intent, agent) == ("web_navigation_help", "web_agent")


def test_simple_terms_is_not_a_legal_document():
    """Regression: a bare 'terms' keyword sent 'in simple terms' to document_help."""
    intent, agent, _, _, _ = keyword_classify("Explain photosynthesis in simple terms")
    assert (intent, agent) == ("education_help", "education_agent")


def test_unknown_input_defaults_to_general():
    intent, agent, entity, confidence, reasoning = keyword_classify("zzz qqq blorp", "")
    assert (intent, agent) == ("general_query", "general_agent")
    assert entity == "general question"
    assert confidence == 0.3, "no keyword match must report low confidence"
    assert "defaulting" in reasoning


@pytest.mark.parametrize("text,expected_intent,expected_agent", TEST_CASES)
def test_every_output_is_schema_valid(text, expected_intent, expected_agent):
    """Output must always satisfy the ClassifyResponse regex contract, or the
    endpoint would raise on its own fallback."""
    intent, agent, entity, confidence, reasoning = keyword_classify(text)
    assert intent in VALID_INTENTS
    assert agent in VALID_AGENTS
    assert AGENT_FOR_INTENT[intent] == agent
    assert entity and reasoning
    assert 0.0 <= confidence <= 1.0


def test_confidence_tracks_match_strength():
    """Confidence is earned by evidence, not hardcoded: more input hits mean
    higher confidence; a single weak hit stays modest."""
    _, _, _, one_hit, _ = keyword_classify("read this")
    _, _, _, strong, _ = keyword_classify("help me fill the form field input")
    _, _, _, none, _ = keyword_classify("hello")
    assert one_hit < strong
    assert none == 0.3


def test_rules_cover_ten_specific_intents():
    """general_query is the default and is intentionally not a rule; the two
    browser intents live in the live-page pre-check, not in KEYWORD_RULES."""
    intents = {rule[1] for rule in KEYWORD_RULES}
    assert intents == {"form_help", "document_help", "education_help", "web_navigation_help",
                       "scheduler_help", "translation_help", "ui_help",
                       "content_explain", "profile_update", "navigation_help"}
    for keywords, _intent, _agent, _hint in KEYWORD_RULES:
        assert keywords, "a rule with no keywords can never match"


@pytest.mark.parametrize("text,expected_intent,expected_agent", [
    ("schedule my doctor appointment for tomorrow", "scheduler_help", "scheduler_agent"),
    ("translate this notice in Hindi please", "translation_help", "translator_agent"),
    ("translate this message in Telugu", "translation_help", "translator_agent"),
    ("make the font bigger", "ui_help", "ui_adjuster_agent"),
    ("explain this page simply", "content_explain", "content_explainer_agent"),
    ("update my profile to blind", "profile_update", "profile_updater_agent"),
    ("go to checkout now", "navigation_help", "navigation_agent"),
])
def test_new_agents_are_reachable_by_keyword(text, expected_intent, expected_agent):
    """6 of 11 agents were unreachable by default: the fallback only knew the
    original four intents. Each new specialist must route on keywords alone."""
    intent, agent, _entity, _confidence, _reasoning = keyword_classify(text)
    assert (intent, agent) == (expected_intent, expected_agent)


@pytest.mark.parametrize("text,expected_intent,expected_agent", [
    ("schedule my doctor appointment for tomorrow", "scheduler_help", "scheduler_agent"),
    ("translate this notice in Hindi please", "translation_help", "translator_agent"),
    ("translate this message in Telugu", "translation_help", "translator_agent"),
    ("make the font bigger", "ui_help", "ui_adjuster_agent"),
    ("explain this page simply", "content_explain", "content_explainer_agent"),
    ("update my profile to blind", "profile_update", "profile_updater_agent"),
    ("go to checkout now", "navigation_help", "navigation_agent"),
])
def test_new_agent_outputs_are_schema_valid(text, expected_intent, expected_agent):
    """New intents must satisfy the widened ClassifyResponse patterns."""
    from app.schemas import ClassifyResponse
    got_intent, got_agent, entity, confidence, reasoning = keyword_classify(text)
    assert (got_intent, got_agent) == (expected_intent, expected_agent)
    ClassifyResponse(intent=got_intent, target_agent=got_agent,
                     extracted_entity=entity, reasoning=reasoning,
                     confidence=confidence)


def test_translation_tiebreaks_beat_profile_and_scheduler():
    """'translate ... blind ...' and 'translate my schedule' tie at one hit
    each; the translator rule sits first so the translation wins the tie."""
    assert keyword_classify("translate this for a blind user")[:2] == ("translation_help", "translator_agent")
    assert keyword_classify("translate my schedule to hindi")[:2] == ("translation_help", "translator_agent")


def test_entity_extraction_prefers_specific_fields():
    _, _, entity, _, _ = keyword_classify("How do I fill the aadhaar number field?")
    assert entity == "Aadhaar number field"
    _, _, entity, _, _ = keyword_classify("What does the date of birth field want?")
    assert entity == "Date of Birth field"
    _, _, entity, _, _ = keyword_classify("How do I fill the permanent address field?")
    assert entity == "Permanent Address field"


def test_case_insensitive():
    upper = keyword_classify("SUMMARIZE THIS PDF FOR ME")
    lower = keyword_classify("summarize this pdf for me")
    assert upper[:4] == lower[:4]


@pytest.mark.parametrize("text,expected_intent,expected_agent,context", BROWSER_CASES)
def test_live_page_phrasing_routes_to_browser(text, expected_intent, expected_agent, context):
    """Action/inspect words reach the live browser ONLY with a page open."""
    intent, agent, _entity, _confidence, _reasoning = keyword_classify(text, context)
    assert (intent, agent) == (expected_intent, expected_agent)


@pytest.mark.parametrize("text,expected_intent,expected_agent,context", BROWSER_CASES)
def test_same_words_without_open_page_stay_informational(text, expected_intent, expected_agent, context):
    """The Round 8 guarantee in reverse: strip the marker and NONE of these
    may route to the browser - there is no real page to act on."""
    intent, agent, _, _, _ = keyword_classify(text, "")
    assert agent != "browser_agent", f"'{text}' routed to browser with no page open"


def test_browser_outputs_are_schema_valid():
    """New intents must satisfy the widened ClassifyResponse patterns."""
    from app.schemas import ClassifyResponse
    for text, intent, agent, context in BROWSER_CASES:
        got_intent, got_agent, entity, confidence, reasoning = keyword_classify(text, context)
        ClassifyResponse(intent=got_intent, target_agent=got_agent,
                         extracted_entity=entity, reasoning=reasoning,
                         confidence=confidence)
