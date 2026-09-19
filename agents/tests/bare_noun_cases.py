"""Bare-noun regression set (B1) - LIVE ONLY, never run offline.

These cases need a real LLM (the hedge being fixed lives in the model call, not
in code). The nightly CI workflow runs them; the scorer below is calibrated
against recorded runs (see b1_before/b1_after calibration in the fix log).
"""
import re

# (agent, query, check) - check: explain|nodoc|clarify
BARE_NOUN_CASES = [
    ("form_agent", "Aadhaar number field?", "explain"),
    ("form_agent", "Permanent address?", "explain"),
    ("form_agent", "Date of birth field", "explain"),
    ("document_agent", "This PDF?", "nodoc"),
    ("document_agent", "The deadline?", "nodoc"),
    ("document_agent", "Summary?", "nodoc"),
    ("web_agent", "Submit button?", "explain"),
    ("web_agent", "The menu?", "explain"),
    ("web_agent", "Where do I click?", "explain"),
    ("education_agent", "Photosynthesis?", "explain"),
    ("education_agent", "Gravity?", "explain"),
    ("education_agent", "Algebra?", "explain"),
    ("general_agent", "Hello?", "clarify"),
    ("general_agent", "Help?", "clarify"),
    ("general_agent", "What can you do?", "explain"),
]

HEDGE_PATTERNS = re.compile(
    r"i don'?t have|could you clarify|need more (information|context)|"
    r"what do you mean|which one do you|please provide (more|the)",
    re.IGNORECASE,
)


def score(check: str, answer: str) -> bool:
    """True = correct behavior for this input type."""
    low = answer.lower()
    if check == "nodoc":
        return "no document" in low
    if check == "clarify":
        return "?" in answer
    return not HEDGE_PATTERNS.search(answer)
