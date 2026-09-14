"""Live end-to-end accuracy check against a running intent engine.

Skipped by default (`-m "not live"` in pytest.ini) because it needs the service
up on :8001 and spends real NIM quota. Opt in with:

    python -m pytest tests/test_live_accuracy.py -m live -v

The offline equivalents live in test_keyword_classifier.py and test_api.py.
"""
import pytest

httpx = pytest.importorskip("httpx")

from cases import ALL_CASES  # noqa: E402

BASE_URL = "http://localhost:8001"

# The keyword fallback is 28/28 offline; the LLM classifier is allowed a little
# slack so a single ambiguous rephrasing cannot turn CI red.
MIN_ACCURACY = 0.90


@pytest.mark.live
def test_live_classifier_accuracy():
    misses = []
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        for index, (text, expected_intent, expected_agent, context) in enumerate(ALL_CASES):
            resp = client.post("/intent/classify", json={
                "session_id": f"live-{index}",
                "input_text": text,
                "screen_context": context,
                "history": [],
            })
            assert resp.status_code == 200, f"service returned {resp.status_code} for '{text}'"
            data = resp.json()
            if (data["intent"], data["target_agent"]) != (expected_intent, expected_agent):
                misses.append(f"'{text}' -> {data['intent']}/{data['target_agent']}")

    accuracy = 1 - len(misses) / len(ALL_CASES)
    assert accuracy >= MIN_ACCURACY, (
        f"accuracy {accuracy:.0%} ({len(ALL_CASES) - len(misses)}/{len(ALL_CASES)}) "
        f"below {MIN_ACCURACY:.0%}: " + "; ".join(misses)
    )


@pytest.mark.live
def test_live_session_context_resolves_followups():
    """'What about this one?' must resolve via memory, not default to general."""
    with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
        sid = "live-followup"
        client.delete(f"/intent/session/{sid}")
        client.post("/intent/classify", json={
            "session_id": sid,
            "input_text": "How do I fill the permanent address field?",
            "screen_context": "admission form open",
            "history": [],
        })
        resp = client.post("/intent/classify", json={
            "session_id": sid, "input_text": "What about this one?",
            "screen_context": "admission form open", "history": [],
        })
        assert resp.json()["intent"] == "form_help"
