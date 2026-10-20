"""LLM-based orchestrator: goal -> plan -> specialist execution.

Routes to all 11 RAG agents (form, document, web, education, general plus
ui_adjuster, content_explainer, profile_updater, navigation, scheduler,
translator). Falls back to keyword routing when the LLM is unreachable so the
endpoint never 502s just for planning.
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger("adaptiveai.orchestrator")


def _kw_hit(lowered: str, keyword: str) -> bool:
    """Single words match on word boundaries; phrases match as substrings.

    Bare `in` let "pan" match "company"/"expand" and "form" match
    "information"/"platform", hijacking unrelated goals into form_agent.
    Phrases keep substring matching (their internal spacing already anchors them).
    """
    if " " in keyword:
        return keyword in lowered
    return re.search(r"\b" + re.escape(keyword) + r"\b", lowered) is not None


KEYWORD_ROUTES: list[tuple[str, tuple[str, ...]]] = [
    ("ui_adjuster_agent", ("contrast", "font", "font size", "text size", "bigger text", "larger", "increase", "layout", "focus", "high contrast", "dark mode", "zoom", "brightness", "theme")),
    # An explicit translate verb wins over profile/document wording: "translate
    # this for a blind user" and "translate this document" are translation
    # requests, not profile updates or summaries.
    ("translator_agent", ("translate", "translation", "in hindi", "in tamil", "in telugu", "in kannada", "in malayalam", "in bengali", "in marathi", "in english", "in spanish", "to hindi", "to telugu", "to tamil", "into hindi")),
    # profile_updater deliberately has NO bare "language": it hijacked
    # translator queries ("what language is this, translate it to hindi").
    # Genuine profile goals still match via "profile"/"verbosity"/etc, and the
    # translator above wins any explicit-translate tie by first-match order.
    # Likewise NO bare "blind"/"low vision": "I am blind, explain this chart"
    # is a content request, not a profile change - those nouns alone must
    # never route here.
    ("profile_updater_agent", ("profile", "verbosity", "voice speed",
                               "update my profile", "update my verbosity",
                               "change my voice", "set my voice")),
    # navigation keeps only site-navigation phrasing: bare "find the"/"where is"
    # hijacked generic lookup questions ("find the submit button" -> web_agent).
    ("navigation_agent", ("go to", "navigate", "take me to", "take me", "open", "checkout", "contact form")),
    # document_agent sits above content_explainer_agent on purpose: "summarize
    # this doc" contains "summarize" and first-match-wins would otherwise send
    # every document summary to the explainer.
    ("document_agent", ("document", "documents", "pdf", "summarize this doc")),
    ("content_explainer_agent", ("explain", "summarize", "what does this say", "simplify", "simply", "explain this", "describe", "read this", "what is this")),
    ("form_agent", ("form", "forms", "field", "fill", "filling", "address", "aadhaar", "aadhar", "pan")),
    ("web_agent", ("button", "buttons", "page", "pages", "website", "websites", "link", "links", "menu", "menus")),
    # NOTE: no bare "explain" here - it is subsumed by content_explainer_agent
    # above and would be dead; education is reached via learn/tutorial/topic.
    ("education_agent", ("learn", "learning", "photosynthesis", "tutorial", "tutorials", "what is", "define", "concept", "course", "lesson", "meaning")),
    # New specialists sit last so every existing route keeps priority
    # (first-match-wins): none of these keywords collide with the above.
    ("scheduler_agent", ("schedule", "scheduled", "remind", "reminder",
                         "reminders", "reminds", "appointment", "calendar",
                         "plan my day")),
]


def keyword_route(goal: str) -> str:
    lowered = goal.lower()
    for agent, keywords in KEYWORD_ROUTES:
        if any(_kw_hit(lowered, k) for k in keywords):
            return agent
    return "general_agent"


def llm_route(goal: str, llm_client) -> tuple[str, str]:
    """Ask the LLM for one agent name; validate, else keyword fallback.

    Returns (agent_name, via) where via is "llm" or "keyword", so callers can
    report honestly which router actually decided (the plan used to claim an
    LLM route even on silent fallback).
    """
    valid = {a for group in KEYWORD_ROUTES for a in [group[0]]} | {"general_agent"}
    try:
        answer = llm_client.chat([
            {"role": "system", "content": (
                "Pick exactly one of: form_agent, document_agent, web_agent, "
                "education_agent, general_agent, ui_adjuster_agent, "
                "content_explainer_agent, profile_updater_agent, navigation_agent, "
                "scheduler_agent, translator_agent. "
                "Reply with only the name."
            )},
            {"role": "user", "content": goal[:1000]},
        ])
        # Models rarely obey "only the name": extract the first known name
        # from prose/punctuation ("document_agent.", "`form_agent`", ...).
        match = re.search(r"\b(" + "|".join(sorted(valid)) + r")\b",
                          str(answer).strip().lower())
        if match:
            return match.group(1), "llm"
        logger.warning("llm_route: unparseable answer %r; keyword fallback", answer)
    except Exception as e:
        logger.warning("llm_route failed (%s); keyword fallback", e)
    return keyword_route(goal), "keyword"
