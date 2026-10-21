"""A browser request with no page open must not be answered as if it were an
informational question.

`_demote_browser_intent` silently rerouted `browser_act`/`browser_inspect` to
`form_agent`/`web_agent` when nothing was open. The user asked "click the book
button" and a chat agent answered *about* buttons, while the user reasonably
believed an action had been attempted. The demotion is still the right routing
(the agents registry has no browser_agent, so the alternative is a 502) - what
was missing is the caller knowing it happened and saying so out loud.
"""
from app.api.routes_query import _demote_browser_intent
from app.services.clients import IntentResponse


def browser_intent(label):
    return IntentResponse(intent=label, target_agent="browser_agent",
                          extracted_entity="x", reasoning="r", confidence=0.9,
                          ambiguous=False)


def test_act_with_no_page_is_flagged_demoted():
    result, demoted = _demote_browser_intent(browser_intent("browser_act"),
                                             page_present=False)
    assert demoted is True
    assert result.target_agent == "form_agent"


def test_inspect_with_no_page_is_flagged_demoted():
    result, demoted = _demote_browser_intent(browser_intent("browser_inspect"),
                                             page_present=False)
    assert demoted is True
    assert result.target_agent == "web_agent"


def test_no_demotion_when_a_page_is_present():
    src = browser_intent("browser_act")
    result, demoted = _demote_browser_intent(src, page_present=True)
    assert demoted is False
    assert result is src


def test_non_browser_intent_is_never_demoted():
    src = IntentResponse(intent="form_help", target_agent="form_agent",
                         extracted_entity="x", reasoning="r", confidence=0.9)
    result, demoted = _demote_browser_intent(src, page_present=False)
    assert demoted is False
    assert result is src


def test_demotion_reasoning_stays_auditable():
    result, _ = _demote_browser_intent(browser_intent("browser_act"), page_present=False)
    assert "no live page" in result.reasoning


def test_query_demo_speaks_the_limitation_instead_of_answering_about_it(client, monkeypatch):
    """End-to-end guard: an action request with nothing open must return the
    limitation and must NOT reach a specialist that would answer as if the
    action had been attempted."""
    import app.api.routes_query as rq

    async def fake_intent(**kwargs):
        return IntentResponse(intent="browser_act", target_agent="browser_agent",
                              extracted_entity="the book button", reasoning="r",
                              confidence=0.9)

    reached_agent = {"yes": False}

    async def fake_agent(**kwargs):
        reached_agent["yes"] = True
        return None

    monkeypatch.setattr(rq, "classify_intent", fake_intent)
    monkeypatch.setattr(rq, "get_agent_response", fake_agent)
    monkeypatch.setattr(rq._live_pages, "get", lambda *a, **k: None)

    r = client.post("/api/query-demo", json={
        "session_id": "s", "input_text": "click the book button",
        "input_source": "text", "screen_context": ""})

    assert r.status_code == 200
    body = r.json()
    assert body["agent_used"] == "limitation"
    assert "I have not clicked" in body["response_text"]
    assert reached_agent["yes"] is False, "demoted action still reached a text agent"
