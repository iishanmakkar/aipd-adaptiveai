"""Actor tests, against a real Chromium.

These exist to prove one rule: no action reports success without a fact read back
off the page. The most important test here is the controlled-input pair, because
that is the failure mode that makes form-filling assistants useless in practice -
`el.value = 'x'` looks correct to a naive check, and the framework then overwrites
it on the next render.

Run:  python -m pytest extension/test/test_actor.py -p no:warnings
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
    pg.add_init_script(path=os.path.join(SRC, "actor.js"))
    pg.goto("about:blank")   # init scripts only run on navigation
    yield pg
    ctx.close()


def load(page, html):
    page.set_content("<!doctype html><html><head><title>A</title></head><body>"
                     + html + "</body></html>")


def node_named(page, name):
    snap = json.loads(json.dumps(page.evaluate("() => AdaptiveAIAX.computeSnapshot(document)")))
    for n in snap["nodes"]:
        if n.get("name") == name:
            return n
    raise AssertionError(f"fixture produced no {name!r}; got {[n.get('name') for n in snap['nodes']]}")


def act(page, node, action, value=None):
    raw = page.evaluate(
        """([node, action, value]) => {
            const A = window.AdaptiveAIActor;
            if (action === 'fill')   return A.fill(node, value, document);
            if (action === 'select') return A.select(node, value, document);
            if (action === 'click')  return A.click(node, document);
            if (action === 'focus')  return A.focus(node, document);
            throw new Error('unknown action ' + action);
        }""", [node, action, value])
    return json.loads(json.dumps(raw))


CONTROLLED_FIXTURE = """
<input id="c" aria-label="Seat preference">
<div id="shown" aria-live="polite" aria-label="Confirmed by the site"></div>
<script>
  const el = document.getElementById('c');
  const shown = document.getElementById('shown');
  let state = '';
  el.addEventListener('input', () => { state = el.value; shown.textContent = state; });
  // A framework that owns the value: anything written without an input event is
  // reverted, which is what React/Vue/Angular controlled inputs do.
  window.__naiveWrite = (v) => { el.value = v; shown.textContent = state; };
  window.__state = () => state;
</script>
"""


def test_fill_plain_input_reads_the_value_back(page):
    load(page, '<label for="pname">Passenger name</label><input id="pname">')
    out = act(page, node_named(page, "Passenger name"), "fill", "Asha Sharma")
    assert out["status"] == "verified", out
    assert out["readback"] == "Asha Sharma"
    assert page.input_value("#pname") == "Asha Sharma"


def test_naive_value_write_is_rejected_by_a_controlled_input(page):
    """Baseline for the next test: proves the fixture actually behaves like a
    framework-owned field, so 'the actor works' would be a real result rather
    than a tautology."""
    load(page, CONTROLLED_FIXTURE)
    page.evaluate("() => window.__naiveWrite('window seat')")
    assert page.evaluate("() => document.getElementById('shown').textContent") == ""
    assert page.evaluate("() => window.__state()") == ""


def test_fill_lands_in_a_controlled_input(page):
    load(page, CONTROLLED_FIXTURE)
    out = act(page, node_named(page, "Seat preference"), "fill", "window seat")
    assert out["status"] == "verified", out
    # The site's own state, not just the DOM attribute, must hold the value.
    assert page.evaluate("() => window.__state()") == "window seat"
    assert page.evaluate("() => document.getElementById('shown').textContent") == "window seat"


def test_over_long_value_is_refused_before_it_is_written(page):
    """maxlength is the page refusing a value. Reporting it as entered would make
    the assistant say "done" about something the site cannot accept, and the
    earlier version of this actor did exactly that by falling back to a
    prototype-setter write that bypasses the limit."""
    load(page, '<label for="m">Short code</label><input id="m" maxlength="3">')
    out = act(page, node_named(page, "Short code"), "fill", "ABCDEFG")
    assert out["status"] == "failed", out
    assert "at most 3" in out["reason"]
    assert page.input_value("#m") == "", "a rejected value must not be left in the field"


def test_a_handler_that_vetoes_the_value_is_reported_failed(page):
    load(page, '<label for="v">Reference code</label><input id="v">'
               '<script>document.getElementById("v").addEventListener("input",'
               ' e => { e.target.value = ""; });</script>')
    out = act(page, node_named(page, "Reference code"), "fill", "PNR101017")
    assert out["status"] == "failed", out
    assert out["readback"] == ""


def test_password_is_refused_and_left_alone(page):
    load(page, '<label for="pw">Password</label><input id="pw" type="password" value="keepme">')
    out = act(page, node_named(page, "Password"), "fill", "hunter2")
    assert out["status"] == "refused", out
    assert page.input_value("#pw") == "keepme"
    assert "hunter2" not in json.dumps(out)


def test_disabled_field_fails_with_a_tellable_reason(page):
    load(page, '<label for="d">Coupon code</label><input id="d" disabled>')
    out = act(page, node_named(page, "Coupon code"), "fill", "SAVE10")
    assert out["status"] == "failed"
    assert "disabled" in out["reason"]


def test_select_accepts_the_visible_label(page):
    load(page, '<label for="c">Travel class</label><select id="c">'
               '<option value="s">Sleeper</option><option value="ac">AC 3-tier</option></select>')
    out = act(page, node_named(page, "Travel class"), "select", "AC 3-tier")
    assert out["status"] == "verified", out
    assert out["readback"] == "AC 3-tier"


def test_missing_option_lists_what_is_actually_available(page):
    load(page, '<label for="c">Travel class</label><select id="c">'
               '<option value="s">Sleeper</option><option value="ac">AC 3-tier</option></select>')
    out = act(page, node_named(page, "Travel class"), "select", "First class")
    assert out["status"] == "failed"
    assert "Sleeper" in out["reason"] and "AC 3-tier" in out["reason"]


def test_stale_reference_refuses_and_does_not_touch_the_replacement(page):
    """The safety case: the position the user agreed to now holds a different
    control. Acting on it would spend money or press the wrong thing."""
    load(page, '<button id="go">Book tickets</button>')
    node = node_named(page, "Book tickets")
    page.evaluate("""() => {
        const el = document.getElementById('go');
        el.replaceWith(Object.assign(document.createElement('button'), {id:'go', textContent:'Pay ₹640'}));
        document.getElementById('go').addEventListener('click',
            () => { window.__clicked = true; });
    }""")
    out = act(page, node, "click")
    assert out["status"] == "stale_ref", out
    assert page.evaluate("() => window.__clicked === undefined"), "replacement was clicked anyway"


def test_removed_control_is_not_found(page):
    load(page, '<label for="gone">Loyalty number</label><input id="gone">')
    node = node_named(page, "Loyalty number")
    page.evaluate("() => document.getElementById('gone').remove()")
    out = act(page, node, "fill", "1234")
    assert out["status"] == "not_found", out


def test_checkbox_click_is_verified_by_state(page):
    load(page, '<label><input type="checkbox"> I accept insurance</label>')
    out = act(page, node_named(page, "I accept insurance"), "click")
    assert out["status"] == "verified"
    assert out["readback"] == "checked"
    assert page.locator("input[type=checkbox]").is_checked()


def test_checkbox_that_will_not_check_is_reported_failed(page):
    """A handler that vetoes the change is common (terms must be accepted after
    scrolling, etc). Reporting it as done would leave the user believing they
    agreed to something the page refused."""
    load(page, '<label><input type="checkbox" id="cb"> I accept terms</label>'
               '<script>document.getElementById("cb").addEventListener("click", '
               'e => { e.target.checked = false; });</script>')
    out = act(page, node_named(page, "I accept terms"), "click")
    assert out["status"] == "failed", out
    assert "unchecked" in out["reason"]


def test_radio_click_is_verified(page):
    load(page, '<label><input type="radio" name="cls" value="ac"> AC 2-tier</label>')
    out = act(page, node_named(page, "AC 2-tier"), "click")
    assert out["status"] == "verified"


def test_plain_button_reports_pressed_not_verified(page):
    """A button has no state of its own; only await_change can say the page
    reacted. Claiming verified here would be the Plan A bug wearing new clothes."""
    load(page, '<button>Book tickets</button><script>window.__hits=0;'
               'document.querySelector("button").addEventListener("click",'
               '()=>{window.__hits++;});</script>')
    out = act(page, node_named(page, "Book tickets"), "click")
    assert out["status"] == "pressed", out
    assert page.evaluate("() => window.__hits") == 1


def test_focus_reports_where_focus_actually_went(page):
    load(page, '<label for="f">Passenger name</label><input id="f">')
    out = act(page, node_named(page, "Passenger name"), "focus")
    assert out["status"] == "verified"
    assert out["readback"] == "focused"

    load(page, '<label for="f2">Second passenger</label><input id="f2">'
               '<script>document.getElementById("f2").addEventListener("focus",'
               '()=>{ window.__trap = document.createElement("button");'
               ' document.body.appendChild(window.__trap); window.__trap.focus(); });</script>')
    hijacked = act(page, node_named(page, "Second passenger"), "focus")
    assert hijacked["status"] == "failed", hijacked


def test_contenteditable_fill_is_verified(page):
    load(page, '<div contenteditable="true" role="textbox" aria-label="Grievance details"></div>')
    out = act(page, node_named(page, "Grievance details"), "fill", "Street light out")
    assert out["status"] == "verified", out
    assert "Street light out" in page.inner_text('[contenteditable]')


def test_verified_always_carries_a_readback(page):
    """The project rule, asserted once over several actions rather than trusted
    in each branch: a verified status with no evidence is a bug by definition."""
    load(page, '<label for="a">Passenger name</label><input id="a">'
               '<label><input type="checkbox"> I accept terms</label>'
               '<label for="c">Travel class</label><select id="c"><option>Sleeper</option></select>')
    outcomes = [
        act(page, node_named(page, "Passenger name"), "fill", "Asha"),
        act(page, node_named(page, "I accept terms"), "click"),
        act(page, node_named(page, "Travel class"), "select", "Sleeper"),
        act(page, node_named(page, "Passenger name"), "focus"),
    ]
    for out in outcomes:
        assert out["status"] in ("verified", "pressed", "failed", "refused"), out
        if out["status"] == "verified":
            assert out["readback"] not in (None, ""), f"verified with no evidence: {out}"
