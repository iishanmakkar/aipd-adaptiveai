"""Adaptive Policy Engine rules.

The engine decides how answers are reworded for the user; these lock the three
documented rules and the LLM-failure fallback, all without touching NIM.
"""
import pytest

from app.models.preference import VerbosityLevel, DisabilityProfile, LanguageComplexity
from app.services import policy_engine
from app.services.policy_engine import adjust_response, count_clarifying_questions


@pytest.fixture
def rewrites(monkeypatch):
    """Capture llm_rewrite calls and echo a marker instead of calling NIM."""
    calls = []

    async def fake(text, instruction):
        calls.append(instruction)
        return f"[rewritten] {text}"

    monkeypatch.setattr(policy_engine, "llm_rewrite", fake)
    return calls


def _prefs(verbosity):
    class P:
        verbosity_level = verbosity
        disability_profile = DisabilityProfile.none
        language_complexity = LanguageComplexity.standard
    return P()


async def test_high_clarifying_count_simplifies(rewrites):
    out = await adjust_response(
        raw_answer="Long text", user_prefs=_prefs(VerbosityLevel.standard),
        clarifying_count=3, session_context={"message_count": 10},
        db=None, session_id="s",
    )
    assert out == "[rewritten] Long text"
    assert "Simplify" in rewrites[0]


async def test_concise_preference_shortens(rewrites):
    await adjust_response(
        raw_answer="Long text", user_prefs=_prefs(VerbosityLevel.concise),
        clarifying_count=0, session_context={"message_count": 10},
        db=None, session_id="s",
    )
    assert "concise" in rewrites[0]


async def test_detailed_preference_expands(rewrites):
    await adjust_response(
        raw_answer="Long text", user_prefs=_prefs(VerbosityLevel.detailed),
        clarifying_count=0, session_context={"message_count": 10},
        db=None, session_id="s",
    )
    assert "Expand" in rewrites[0]


async def test_first_time_user_gets_welcome(rewrites):
    await adjust_response(
        raw_answer="Long text", user_prefs=_prefs(VerbosityLevel.standard),
        clarifying_count=0, session_context={"message_count": 1},
        db=None, session_id="s",
    )
    assert "welcoming" in rewrites[0].lower()


async def test_established_standard_user_is_untouched(rewrites):
    """Only an established session (>= 3 messages) skips every rule; db=None
    means 'no history', which is itself the first-time-user case."""
    from conftest import FakeResult, FakeSession
    out = await adjust_response(
        raw_answer="Plain answer", user_prefs=_prefs(VerbosityLevel.standard),
        clarifying_count=0, session_context={"message_count": 10},
        db=FakeSession([FakeResult(["m1", "m2", "m3", "m4"])]), session_id="s",
    )
    assert out == "Plain answer"
    assert rewrites == []


async def test_no_db_is_treated_as_first_time_user(rewrites):
    await adjust_response(
        raw_answer="t", user_prefs=_prefs(VerbosityLevel.standard),
        clarifying_count=0, session_context={"message_count": 10},
        db=None, session_id="s",
    )
    assert rewrites, "db=None must be read as an empty session, not 'unknown'"


async def test_confusion_rule_wins_over_verbosity(rewrites):
    """Rule ordering: a confused user is simplified even if they prefer detail."""
    await adjust_response(
        raw_answer="t", user_prefs=_prefs(VerbosityLevel.detailed),
        clarifying_count=5, session_context={"message_count": 10},
        db=None, session_id="s",
    )
    assert len(rewrites) == 1
    assert "Simplify" in rewrites[0]


async def test_llm_rewrite_returns_original_on_failure(monkeypatch):
    """A dead NIM must degrade to the original answer, never an error to the user."""
    class _Boom:
        async def create(self, **kwargs):
            raise RuntimeError("NIM unreachable")

    monkeypatch.setattr(policy_engine.client, "chat", type("C", (), {"completions": _Boom()})())
    out = await policy_engine.llm_rewrite("original text", "do something")
    assert out == "original text"


async def test_threshold_is_configurable(monkeypatch):
    monkeypatch.setattr(policy_engine.settings, "clarifying_threshold", 1)

    async def fake(text, instruction):
        return "rewritten"

    monkeypatch.setattr(policy_engine, "llm_rewrite", fake)
    out = await adjust_response(
        raw_answer="t", user_prefs=_prefs(VerbosityLevel.standard),
        clarifying_count=1, session_context={"message_count": 9},
        db=None, session_id="s",
    )
    assert out == "rewritten"


async def test_no_db_means_zero_counts():
    assert await count_clarifying_questions(None, "s") == 0
