"""Task-runner control flow, driven in real Chromium through the real action path.

The planner is stubbed on purpose: what is under test is the loop's behaviour when
a step fails, when the gate fires, and when the budget runs out - not what a model
would say. send() goes through content.js's own runAction, so the gate, the actor
and await_change are the same implementations the extension will ship with.

Run:  python -m pytest extension/test/test_runner.py -p no:warnings
"""
import json
import os

import pytest
from playwright.sync_api import sync_playwright

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

BOOKING = """
<label for="n">Passenger Name</label><input id="n">
<label for="c">Travel class</label>
<select id="c"><option value="SL">Sleeper</option><option value="AC">AC 3-tier</option></select>
<label><input type="checkbox" id="t"> I accept terms</label>
<div id="slot"></div>
<button id="go">Proceed</button>
<button id="pay">Pay ₹640</button>
<script>
  window.__paid = 0;
  document.getElementById('go').addEventListener('click', () => {
    const d = document.createElement('div');
    d.setAttribute('role', 'alert');
    d.textContent = 'Seat 12A held';
    document.getElementById('slot').appendChild(d);
  });
  document.getElementById('pay').addEventListener('click', () => {
    window.__paid++;
    const ok = document.createElement('div');
    ok.setAttribute('role', 'alert');
    ok.textContent = 'Payment accepted';
    document.getElementById('slot').appendChild(ok);
  });
</script>
"""

HARNESS = """
async ([plan, confirmBehaviour, maxSteps]) => {
    const snap = window.__adaptiveai.snapshot(true);
    const refFor = (label) => {
        const n = snap.nodes.find(x => x.name === label);
        if (!n) throw new Error('fixture has no ' + label);
        return n.ref;
    };
    const steps = plan.map(s => ({ ...s, ref: s.label ? refFor(s.label) : s.ref }));
    let i = 0;
    const questions = [];
    const lastOutcomes = [];
    const result = await AdaptiveAIRunner.run({
        goal: 'book a ticket',
        maxSteps: maxSteps,
        nextStep: async (context) => {
            lastOutcomes.push(context.lastOutcome ? context.lastOutcome.status : null);
            return i < steps.length ? steps[i++] : null;
        },
        send: async (spec) => await window.__adaptiveai.act(spec),
        snapshot: () => window.__adaptiveai.snapshot(true),
        availableLabels: async () => ['full name'],
        confirm: async (record, verdict) => {
            questions.push({ name: record.description, reason: verdict.reason,
                             amount: verdict.amount });
            if (confirmBehaviour === 'throw') throw new Error('mic unavailable');
            return confirmBehaviour === 'yes';
        },
    });
    return { result, questions, lastOutcomes };
}
"""


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    for f in ("ax.js", "gate.js", "watch.js", "actor.js", "content.js", "runner.js"):
        pg.add_init_script(path=os.path.join(SRC, f))
    pg.goto("about:blank")
    pg.set_content("<!doctype html><html><head><title>Book</title></head><body>"
                   + BOOKING + "</body></html>")
    yield pg
    ctx.close()


FILL_AND_PROCEED = [
    {"action": "fill", "label": "Passenger Name", "value": "Asha Sharma",
     "description": "enter the passenger name"},
    {"action": "select", "label": "Travel class", "value": "AC 3-tier",
     "description": "choose AC 3-tier"},
    {"action": "click", "label": "I accept terms",
     "description": "accept the terms"},
    {"action": "click", "label": "Proceed", "description": "continue",
     "expect": {"kind": "node_appears", "role": "alert", "name": "Seat 12A held"}},
]

PAY_STEP = [{"action": "click", "label": "Pay ₹640", "description": "pay the fare"}]


def run(page, plan, confirm_behaviour="no", max_steps=12):
    raw = page.evaluate(HARNESS, [plan, confirm_behaviour, max_steps])
    return json.loads(json.dumps(raw))


def test_the_loop_actually_drives_the_page(page):
    out = run(page, FILL_AND_PROCEED)
    result = out["result"]
    assert result["status"] == "completed", result
    assert result["stepsVerified"] == 4, result
    assert page.input_value("#n") == "Asha Sharma"
    assert page.input_value("#c") == "AC"
    assert page.locator("#t").is_checked()
    assert "Seat 12A held" in page.inner_text("#slot")
    # Every step records its evidence, not just a word saying it worked.
    assert all(s["status"] in ("verified", "pressed") for s in result["steps"]), result
    assert any(s.get("readback") for s in result["steps"]), result


def test_a_gated_step_is_asked_about_and_never_assumed(page):
    out = run(page, FILL_AND_PROCEED + PAY_STEP, confirm_behaviour="no")
    result = out["result"]
    assert result["status"] == "cancelled", result
    assert page.evaluate("() => window.__paid") == 0, "money spent without confirmation"
    assert len(out["questions"]) == 1
    q = out["questions"][0]
    assert q["amount"]["value"] == 640, q
    assert "spends money" in q["reason"], q
    assert any("Say yes to go ahead" in s for s in result["narration"]), result


def test_a_spoken_yes_opens_the_gate_and_the_click_lands(page):
    out = run(page, FILL_AND_PROCEED + PAY_STEP, confirm_behaviour="yes")
    result = out["result"]
    assert result["status"] == "completed", result
    assert page.evaluate("() => window.__paid") == 1, result
    pay = result["steps"][-1]
    assert pay["confirmedByUser"] is True
    # 'pressed', not 'verified': this plan gives no prediction for the payment
    # click, so nothing has proved the site took the money. A real run would
    # attach expect=... and get 'verified' or a failure - the assistant is not
    # allowed to infer success from the button having been clickable.
    assert pay["status"] == "pressed", pay


def test_a_broken_confirmation_channel_does_not_approve(page):
    """If the microphone fails at the worst moment, the answer is no."""
    out = run(page, FILL_AND_PROCEED + PAY_STEP, confirm_behaviour="throw")
    assert out["result"]["status"] == "cancelled", out["result"]
    assert page.evaluate("() => window.__paid") == 0


def test_a_confirmed_payment_that_was_predicted_becomes_verified(page):
    """Gate and verification working together: the user says yes, the click lands,
    and the status only rises to 'verified' because the page said what the plan
    predicted it would say."""
    plan = [{"action": "click", "label": "Pay ₹640", "description": "pay the fare",
             "expect": {"kind": "node_appears", "role": "alert",
                        "name": "Payment accepted"}}]
    out = run(page, plan, confirm_behaviour="yes")
    result = out["result"]
    step = result["steps"][-1]
    assert step["status"] == "verified", result
    assert "Payment accepted" in step["readback"], step
    assert page.evaluate("() => window.__paid") == 1, result


def test_a_failed_step_stops_before_the_payment(page):
    broken = FILL_AND_PROCEED[:2] + [
        {"action": "fill", "ref": "n999", "value": "x",
         "description": "enter the ticket reference"}] + PAY_STEP
    out = run(page, broken)
    result = out["result"]
    assert result["status"] == "failed", result
    assert result["steps"][-1]["status"] == "not_found", result
    assert page.evaluate("() => window.__paid") == 0, "carried on to payment after a failure"
    assert any("I have stopped here" in s for s in result["narration"]), result


def test_budget_is_reported_as_a_budget(page):
    endless = [{"action": "focus", "label": "Passenger Name", "description": "look"}]
    out = run(page, endless * 3, max_steps=2)
    result = out["result"]
    assert result["status"] == "budget", result
    assert len(result["steps"]) == 2, result
    assert any("limit of 2 steps" in s for s in result["narration"]), result


def test_after_an_approval_the_planner_sees_the_real_outcome(page):
    """The outcome handed back to the planner after a gated step must be the
    approved result, not the pre-approval 'gated': recorded as gated, the next
    history line told the model the press never happened when the user had just
    approved it - and the model would reasonably try the same step again."""
    plan = PAY_STEP + [{"action": "focus", "label": "Passenger Name",
                        "description": "focus the name field"}]
    out = run(page, plan, confirm_behaviour="yes")
    assert out["result"]["status"] == "completed", out["result"]
    assert out["lastOutcomes"][1] == "pressed", out["lastOutcomes"]


def test_a_benign_run_never_asks_for_confirmation(page):
    out = run(page, FILL_AND_PROCEED, confirm_behaviour="yes")
    assert out["questions"] == []
    assert out["result"]["status"] == "completed"
