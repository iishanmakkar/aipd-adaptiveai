"""Live bare-noun regression (B1) - runs only with -m live in the nightly CI job.

Scores each probe with bare_noun_cases.score and fails below threshold, so a
prompt regression that reintroduces hedging breaks the build loudly.
"""
import pytest

from tests.bare_noun_cases import BARE_NOUN_CASES, score

pytestmark = pytest.mark.live

PASS_THRESHOLD = 13  # of 15; LLM sampling noise allowance, calibrated vs b1 runs


def test_bare_noun_accuracy():
    """Hits a running agents service on :8002 (nightly job starts the stack)."""
    import httpx
    passed, failed = [], []
    for agent, query, check in BARE_NOUN_CASES:
        r = httpx.post("http://localhost:8002/agent/respond",
                       json={"session_id": "b1-nightly", "agent": agent,
                             "query": query, "entity": "", "extra_context": ""},
                       timeout=120)
        assert r.status_code == 200, f"{agent}/{query}: HTTP {r.status_code}"
        ok = score(check, r.json().get("answer", ""))
        (passed if ok else failed).append(f"{agent}: {query}")
    print(f"\nbare-noun: {len(passed)}/15 passed")
    for f in failed:
        print("  MISS:", f)
    assert len(passed) >= PASS_THRESHOLD, f"{len(failed)} misses: {failed}"
