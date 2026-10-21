"""Gate tests: what gets stopped, and just as importantly what does not.

Run in the same real Chromium as the rest of the suite so the classification is
exercised against actual snapshot nodes rather than dictionaries I typed by hand.

Over-gating is a failure mode, not a safe default: a user who is asked to confirm
"Next" and "Add to cart" four times a session answers yes without listening by the
fifth, and then the gate protects nothing. So half of this file asserts that
ordinary navigation is NOT stopped.
"""
import json
import os

import pytest
from playwright.sync_api import sync_playwright

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


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
    pg.add_init_script(path=os.path.join(SRC, "ax.js"))
    pg.add_init_script(path=os.path.join(SRC, "gate.js"))
    pg.goto("about:blank")
    yield pg
    ctx.close()


def verdict(page, html, name, context=None):
    page.set_content("<!doctype html><html><body>" + html + "</body></html>")
    snap = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    node = next((n for n in snap["nodes"] if n.get("name") == name), None)
    assert node is not None, f"fixture produced no {name!r}"
    return json.loads(json.dumps(
        page.evaluate("([node, ctx]) => AdaptiveAIGate.classify(node, ctx)", [node, context or {}])))


def test_money_comitting_labels_are_gated(page):
    html = "".join(f'<button>{label}</button>' for label in (
        "Pay ₹640", "Proceed to payment", "Confirm booking", "Place order",
        "Book now", "Submit application", "Add card", "Cancel ticket"))
    for label in ("Pay ₹640", "Proceed to payment", "Confirm booking", "Place order",
                  "Book now", "Submit application", "Add card", "Cancel ticket"):
        v = verdict(page, html, label)
        assert v["gated"] is True, (label, v)
        assert v["reason"], label


def test_ordinary_navigation_is_not_gated(page):
    html = "".join(f'<button>{label}</button>' for label in (
        "Next", "Continue", "Search", "Select seats", "Apply filter",
        "Add to cart", "Save draft", "Preview ticket"))
    for label in ("Next", "Continue", "Search", "Select seats", "Apply filter",
                  "Add to cart", "Save draft", "Preview ticket"):
        v = verdict(page, html, label)
        assert v["gated"] is False, f"{label} should not gate: {v}"


def test_amount_is_parsed_for_the_announcement(page):
    v = verdict(page, '<button>Pay now — ₹1,299.50</button>', "Pay now — ₹1,299.50")
    assert v["gated"] is True
    assert v["amount"]["value"] == pytest.approx(1299.5)
    assert v["amount"]["currency"] == "INR"


def test_ceiling_needs_a_second_confirmation(page):
    v = verdict(page, '<button>Pay ₹640</button>', "Pay ₹640", {"spendCeiling": 500})
    assert v["gated"] is True
    assert v["exceedsCeiling"] is True
    below = verdict(page, '<button>Pay ₹640</button>', "Pay ₹640", {"spendCeiling": 5000})
    assert below["exceedsCeiling"] is False


def test_no_ceiling_means_no_stronger_requirement(page):
    """Without a user-set limit the gate must not invent one: a made-up ceiling
    would be a policy the user never agreed to."""
    v = verdict(page, '<button>Pay ₹99999</button>', "Pay ₹99999", {})
    assert v["gated"] is True
    assert v["exceedsCeiling"] is False


def test_innocuous_label_inside_a_payment_frame_is_gated(page):
    v = verdict(page, '<button>Continue</button>', "Continue",
                {"frameUrl": "https://api.razorpay.com/v1/checkout"})
    assert v["gated"] is True, v
    assert "payment" in v["reason"]


def test_top_frame_is_not_treated_as_a_payment_frame(page):
    v = verdict(page, '<button>Continue</button>', "Continue",
                {"frameUrl": "", "origin": "https://in.bookmyshow.com"})
    assert v["gated"] is False, v


def test_fill_is_never_gated(page):
    """Typing into the passenger-name field is not a commitment. Gating every
    interaction would make the assistant unusable and teach dismissal."""
    page.set_content('<html><body><label for="n">Passenger name</label>'
                     '<input id="n"></body></html>')
    snap = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    node = snap["nodes"][0]
    v = json.loads(json.dumps(page.evaluate("([n]) => AdaptiveAIGate.classify(n, {})", [node])))
    assert v["gated"] is False


# ---------------------------------------------------------------------------
# Fail-closed enforcement. This one cannot live in the extension-load suite:
# the content script runs in an isolated world, so `delete window.AdaptiveAIGate`
# from a page script would not actually remove it from where runAction reads it.
# Loading ax.js + actor.js + content.js without gate.js reproduces the real
# condition - a page where the gate never loaded - in the same world the code runs.

@pytest.fixture
def no_gate_page(browser):
    ctx = browser.new_context()
    pg = ctx.new_page()
    pg.add_init_script(path=os.path.join(SRC, "ax.js"))
    pg.add_init_script(path=os.path.join(SRC, "actor.js"))
    pg.add_init_script(path=os.path.join(SRC, "content.js"))
    pg.goto("about:blank")
    yield pg
    ctx.close()


def test_missing_gate_script_refuses_every_click(no_gate_page):
    no_gate_page.set_content("""<!doctype html><html><body>
        <button id="pay">Pay ₹640</button>
        <script>window.__paid=0;document.getElementById('pay')
            .addEventListener('click',()=>{window.__paid++;});</script>
        </body></html>""")
    result = json.loads(json.dumps(no_gate_page.evaluate("""() => {
        const snap = window.__adaptiveai.snapshot(true);
        const node = snap.nodes.find(n => n.name && n.name.indexOf('Pay') === 0);
        // confirm: true on purpose - a missing gate must not be waved through by
        // the same flag that a real confirmation sets.
        return window.__adaptiveai.act({ ref: node.ref, action: 'click', confirm: true });
    }""")))
    assert result["status"] == "refused", result
    assert "gate" in result["reason"], result
    assert no_gate_page.evaluate("() => window.__paid") == 0, "clicked without the gate"
