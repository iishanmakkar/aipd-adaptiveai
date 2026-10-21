"""The wire contract for POST /api/extension/step.

These tests stub the model, on purpose. The planner's judgement is not what is
under test here - what is under test is what the server does with an answer it
did not choose: a ref that is not on the page, a value nobody spoke, a password
field, a card number that arrived because a redaction step was skipped. Each of
those must be refused by the server, because a rule that only holds when the
model behaves is not a rule.
"""
import json
from pathlib import Path

import pytest

import app.services.step_planner as planner

GOAL = "Book two tickets to the 7pm showing of Jawan and give me my email"

NODES = [
    {"ref": "a1", "tag": "input", "role": "textbox", "name": "Email address",
     "nameSource": "label", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": "email", "hasValue": False, "sensitive": False,
     "states": {"focusable": True}, "inShadow": False, "disabled": False},
    {"ref": "a2", "tag": "input", "role": "textbox", "name": "Passenger name",
     "nameSource": "label", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": "text", "hasValue": False, "sensitive": False,
     "states": {}, "inShadow": False, "disabled": False},
    {"ref": "a3", "tag": "input", "role": "textbox", "name": "Password",
     "nameSource": "label", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": "password", "hasValue": False, "sensitive": True,
     "states": {}, "inShadow": False, "disabled": False},
    {"ref": "a4", "tag": "select", "role": "combobox", "name": "Showtime",
     "nameSource": "label", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": "select-one", "hasValue": False, "sensitive": False,
     "states": {}, "inShadow": False, "disabled": False,
     "options": [{"text": "19:00"}, {"text": "21:30"}]},
    {"ref": "a5", "tag": "button", "role": "button", "name": "Pay ₹640",
     "nameSource": "contents", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": None, "hasValue": False, "sensitive": False,
     "states": {}, "inShadow": False, "disabled": False},
    {"ref": "a6", "tag": "button", "role": "button", "name": "Continue",
     "nameSource": "contents", "unnamed": False, "lowConfidenceName": False,
     "interactive": True, "kind": None, "hasValue": False, "sensitive": False,
     "states": {}, "inShadow": False, "disabled": True},
]


def body(**overrides):
    payload = {"goal": GOAL, "url": "https://books.example.com/checkout",
               "title": "Checkout", "nodes": NODES,
               "available_labels": ["email", "full name", "phone"],
               "history": [], "verbosity": "blind_concise"}
    payload.update(overrides)
    return payload


@pytest.fixture(autouse=True)
def _offline_db(client):
    """Offline mode makes `get_db` 503 before any handler runs, and this
    endpoint's auth dependency is the thing that needs it. Overridden with the
    same fake the hardening tests use, so DEBUG's demo identity resolves and the
    forged-token test still exercises real token logic instead of skipping it."""
    from app.database import get_db
    from app.main import app
    from tests.conftest import FakeSession

    async def _fake_db():
        yield FakeSession()

    app.dependency_overrides[get_db] = _fake_db
    yield
    app.dependency_overrides.pop(get_db, None)


def stub_reply(monkeypatch, payload):
    """Make the model answer exactly this object (as JSON text)."""
    text = payload if isinstance(payload, str) else json.dumps(payload)

    async def _complete(_messages):
        return text

    monkeypatch.setattr(planner, "complete", _complete)


def act(ref, **overrides):
    reply = {"status": "act", "action": "click", "ref": ref, "value_from": "none",
             "value_label": None, "value_literal": None, "expect": "none",
             "narration": "Pressing Continue.", "why": None}
    reply.update(overrides)
    return reply


def test_act_on_a_real_redacted_node(client, monkeypatch):
    stub_reply(monkeypatch, act("a2", action="fill", value_from="profile",
                                value_label="full name", expect="none",
                                narration="Entering your full name."))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "act"
    assert data["action"] == "fill" and data["ref"] == "a2"
    assert data["value_from"] == "profile" and data["value_label"] == "full name"
    assert data["confidence_source"] == "llm"


def test_a_node_carrying_a_value_is_refused_not_ignored(client):
    """extra="forbid" is the boundary. Dropping the field quietly would still
    mean a card number arrived, and no log would ever say so."""
    leaked = dict(NODES[0])
    leaked["value"] = "asha@example.com"
    r = client.post("/api/extension/step", json=body(nodes=[leaked]))
    assert r.status_code == 422
    assert "value" in json.dumps(r.json()).lower()


@pytest.mark.parametrize("forbidden", ["selector", "identity", "bounds"])
def test_other_local_only_fields_are_refused(client, forbidden):
    node = dict(NODES[0])
    node[forbidden] = "whatever"
    assert client.post("/api/extension/step",
                       json=body(nodes=[node])).status_code == 422


def test_a_card_number_in_an_accessible_name_is_refused(client):
    """The positive control for the redaction check: a client that skipped
    redactSnapshot() must be stopped here, not trusted because it looked like a
    name."""
    node = dict(NODES[1], name="Card number 4111 1111 1111 1111")
    r = client.post("/api/extension/step", json=body(nodes=[node]))
    assert r.status_code == 422
    assert "redactSnapshot" in json.dumps(r.json())


def test_an_ordinary_long_reference_is_not_a_card_number(client, monkeypatch):
    """Booking reference 1234567890123 is page text a blind user needs spoken;
    the guard must not shout at every digit run."""
    node = dict(NODES[1], name="Booking reference 1234567890123")
    stub_reply(monkeypatch, act("a2", action="fill", value_from="profile",
                                value_label="full name"))
    assert client.post("/api/extension/step",
                       json=body(nodes=[node])).json()["status"] == "act"


def test_hallucinated_ref_becomes_cannot(client, monkeypatch):
    stub_reply(monkeypatch, act("a999"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "cannot"
    assert data["ref"] is None and data["action"] is None
    assert "not on this page" in data["narration"]


def test_password_fields_are_never_targeted(client, monkeypatch):
    stub_reply(monkeypatch, act("a3", action="fill", value_from="profile",
                                value_label="password"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "cannot"
    assert "password" in data["narration"].lower()


def test_disabled_target_is_refused(client, monkeypatch):
    stub_reply(monkeypatch, act("a6"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "cannot"
    assert "disabled" in data["why"]


def test_profile_label_the_vault_does_not_have_asks_the_user(client, monkeypatch):
    stub_reply(monkeypatch, act("a2", action="fill", value_from="profile",
                                value_label="passport number"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "ask_user"
    assert "setup" in data["narration"]


def test_a_value_the_user_never_said_is_never_returned(client, monkeypatch):
    """The invention test: the model puts a passenger name in the reply that the
    goal does not contain. The answer must not carry it, in any field."""
    stub_reply(monkeypatch, act("a2", action="fill", value_from="literal",
                                 value_literal="Asha Sharma"))
    data = client.post("/api/extension/step", json=body())
    raw = json.dumps(data.json()).lower()
    assert "asha sharma" not in raw, raw
    assert data.json()["status"] == "ask_user"


def test_a_value_the_user_did_say_is_passed_through(client, monkeypatch):
    """Verbatim, not paraphrased: the model has to copy the user's own spelling,
    because "7 pm" and "7pm" are the same words and only one of them is a rule
    anybody can check."""
    stub_reply(monkeypatch, act("a4", action="select", value_from="literal",
                                 value_literal="7pm"))
    data = client.post("/api/extension/step",
                       json=body(goal="Book the 7pm showing of Jawan")).json()
    assert data["status"] == "act" and data["value_literal"] == "7pm"


def test_a_reformatted_value_the_user_said_is_still_refused(client, monkeypatch):
    stub_reply(monkeypatch, act("a4", action="select", value_from="literal",
                                 value_literal="7 pm"))
    data = client.post("/api/extension/step",
                       json=body(goal="Book the 7pm showing")).json()
    assert data["status"] == "ask_user"


def test_a_value_only_field_is_accepted_because_it_carries_no_value(client, monkeypatch):
    """An unlabeled textbox that the user has already filled arrives as an empty
    name plus `hasValue` (AccName gives a textbox no name from its own value, and
    `ax.js` records that as `value-only`). The alternative - naming the field by
    what was typed - is the leak this contract must never accept, so the shape is
    pinned on both sides: the device produces it, and the prompt shows it."""
    box = dict(NODES[1], name="", nameSource="value-only", hasValue=True)
    stub_reply(monkeypatch, act("a2", action="fill", value_from="profile",
                                value_label="full name"))

    seen = {}

    async def _capture(messages):
        seen["text"] = "\n".join(m["content"] for m in messages)
        return json.dumps(act("a2", action="fill", value_from="profile",
                               value_label="full name"))

    monkeypatch.setattr(planner, "complete", _capture)
    data = client.post("/api/extension/step", json=body(nodes=[box])).json()
    assert data["status"] == "act"
    assert "name=UNNAMED" in seen["text"] and "has-value" in seen["text"]
    assert "asha" not in seen["text"].lower()


def test_click_never_carries_a_value(client, monkeypatch):
    stub_reply(monkeypatch, act("a5", value_from="literal", value_literal="₹640"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["action"] == "click"
    assert data["value_from"] == "none" and data["value_literal"] is None


def test_unknown_expect_degrades_to_none(client, monkeypatch):
    stub_reply(monkeypatch, act("a5", expect="money_left_account"))
    assert client.post("/api/extension/step", json=body()).json()["expect"] == "none"


def test_narration_is_bounded(client, monkeypatch):
    stub_reply(monkeypatch, act("a5", narration="x" * 5000))
    data = client.post("/api/extension/step", json=body()).json()
    assert len(data["narration"]) <= planner.MAX_NARRATION_CHARS


def test_the_reply_carries_no_gate_verdict():
    """The local predicate in extension/src/gate.js decides whether a press is
    irreversible. A second implementation of it in Python - even an "advisory"
    one - gives a blind user two answers, and the one they cannot override is a
    copy that drifts. So the contract has no gate field at all."""
    source = (Path(__file__).resolve().parents[2] / "extension" / "src" /
              "gate.js").read_text(encoding="utf-8")
    assert "COMMIT_PATTERNS" in source, "the local gate is gone; this test must move"
    response = json.dumps(sorted(planner.validate_plan(
        {"status": "done", "narration": "Booked."}, goal=GOAL, nodes=NODES,
        available_labels=[])))
    assert "gate" not in response.lower(), response


def test_a_gated_button_still_gets_an_action(client, monkeypatch):
    """Refusing to guess about the gate must not stop the planner proposing a
    payment button - the device is the one that pauses and asks."""
    stub_reply(monkeypatch, act("a5"))
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "act" and data["ref"] == "a5"


def test_unparseable_model_reply_is_reported_not_retried(client, monkeypatch):
    stub_reply(monkeypatch, "I think we should press Continue!")
    data = client.post("/api/extension/step", json=body()).json()
    assert data["status"] == "cannot"
    assert data["confidence_source"] == "none"
    assert data["action"] is None


def test_an_unreachable_planner_is_503_and_never_a_guess(client, monkeypatch):
    async def _down(_messages):
        raise planner.PlannerUnavailable("APIConnectionError: connect refused")

    monkeypatch.setattr(planner, "complete", _down)
    r = client.post("/api/extension/step", json=body())
    assert r.status_code == 503
    assert "unavailable" in r.json()["detail"].lower()


def test_forged_token_is_401(client):
    r = client.post("/api/extension/step", json=body(),
                    headers={"Authorization": "Bearer nonsense"})
    assert r.status_code == 401


def test_oversized_snapshot_is_refused(client):
    nodes = [dict(n, ref=f"z{i}") for i, n in enumerate(NODES * 70)]
    assert len(nodes) > 400
    assert client.post("/api/extension/step", json=body(nodes=nodes)).status_code == 422


def test_rate_limit_covers_the_task_loop(client, monkeypatch):
    """40 steps a minute is the declared budget; the 41st must be a 429 with
    Retry-After, not a slower answer."""
    stub_reply(monkeypatch, act("a1"))
    codes = [client.post("/api/extension/step", json=body()).status_code
             for _ in range(41)]
    assert codes[:40] == [200] * 40
    assert codes[40] == 429


def test_prompt_sees_structure_and_labels_not_values(client, monkeypatch):
    """What the model is actually shown - the privacy boundary is only real if
    somebody reads it out."""
    seen = {}

    async def _capture(messages):
        seen["text"] = "\n".join(m["content"] for m in messages)
        return json.dumps(act("a1"))

    monkeypatch.setattr(planner, "complete", _capture)
    nodes = [dict(NODES[0], hasValue=True),
             dict(NODES[3], name="Showtime", nameSource="label")]
    client.post("/api/extension/step", json=body(nodes=nodes))
    prompt = seen["text"]
    assert "ref=a1" in prompt and "kind=email" in prompt
    assert "has-value" in prompt
    assert "options=19:00 / 21:30" in prompt
    # Structural words the actor needs and the model must never see.
    for absent in ("selector", "bounds", "identity", "value="):
        assert absent not in prompt, absent
