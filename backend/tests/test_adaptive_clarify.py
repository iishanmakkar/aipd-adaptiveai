"""Adaptive behavior: deterministic clarifying questions.

The decision must be a pure offline-testable rule: only a genuinely unsure
classification (keyword no-match default 0.3, or an LLM self-report below
settings.clarify_confidence_threshold) triggers one clarifying question —
never a confident match, never autonomous orchestration, never browser turns.
"""
import pytest

from app.api.routes_query import _should_clarify
from app.config import settings
from app.schemas.query import QueryRequest
from app.services.clients import IntentResponse


def _request(**overrides) -> QueryRequest:
    base = {
        "session_id": "00000000-0000-0000-0000-000000000001",
        "input_text": "asdfqwerty",
        "input_source": "text",
        "screen_context": "",
    }
    base.update(overrides)
    return QueryRequest(**base)


def _intent(confidence: float, target_agent: str = "general_agent",
            ambiguous: bool = False) -> IntentResponse:
    return IntentResponse(
        intent="general_query",
        target_agent=target_agent,
        extracted_entity="general question",
        reasoning="test",
        confidence=confidence,
        ambiguous=ambiguous,
    )


def test_keyword_no_match_confidence_triggers_clarify():
    # The classifier's explicit no-match default is 0.3 — below the threshold.
    assert settings.clarify_confidence_threshold > 0.3
    assert _should_clarify(_request(), _intent(0.3))


def test_classifier_judged_ambiguity_triggers_clarify():
    # LLM self-confidence is useless for this (it reports 0.9 on gibberish),
    # so ambiguity travels as the classifier's own explicit judgment.
    assert _should_clarify(_request(), _intent(0.9, ambiguous=True))


def test_confident_matches_never_clarify():
    # Real keyword matches score >= 0.5; LLM self-reports that are sure are
    # >= 0.85. Neither may be second-guessed with a question.
    assert not _should_clarify(_request(), _intent(0.5))
    assert not _should_clarify(_request(), _intent(0.85))
    assert not _should_clarify(_request(), _intent(0.9, ambiguous=False))


def test_autonomous_mode_opts_out():
    # An orchestrated plan already expresses the user's goal.
    assert not _should_clarify(_request(autonomous=True), _intent(0.3))
    assert not _should_clarify(_request(autonomous=True), _intent(0.9, ambiguous=True))


def test_browser_turns_never_clarify():
    # Live-browser intents are handled (or demoted) before this rule runs.
    assert not _should_clarify(_request(), _intent(0.3, target_agent="browser_agent"))


def test_threshold_is_tunable_via_settings(monkeypatch):
    monkeypatch.setattr(settings, "clarify_confidence_threshold", 0.0)
    assert not _should_clarify(_request(), _intent(0.3))
