"""await_change: proving a click changed the page the way we predicted.

The baseline is captured and the change is triggered inside the same browser
evaluate (via setTimeout), so the test cannot accidentally record a change that
happened before the baseline existed.

Run:  python -m pytest extension/test/test_watch.py -p no:warnings
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
    pg.add_init_script(path=os.path.join(SRC, "watch.js"))
    pg.goto("about:blank")
    yield pg
    ctx.close()


def wait_for_change(page, html, trigger, expect, timeout=2500):
    """Capture baseline, fire the page's own change, then await the expectation."""
    page.set_content("<!doctype html><html><head><title>Before</title></head><body>"
                     + html + "</body></html>")
    raw = page.evaluate(
        """async ([trigger, expect, timeout]) => {
            const baseline = AdaptiveAIWatch.capture(document, null);
            new Function(trigger)();
            return await AdaptiveAIWatch.waitFor(document, baseline, expect, timeout);
        }""", [trigger, expect, timeout])
    return json.loads(json.dumps(raw))


def test_url_change_is_detected(page):
    res = wait_for_change(page, '<button id="b">Next</button>',
                          'setTimeout(() => { location.hash = "#step2"; }, 120);',
                          {"kind": "url_changed"})
    assert res["verified"] is True, res
    assert "#step2" in res["evidence"]


def test_a_handler_that_is_only_attached_is_not_a_change(page):
    """Wiring a listener and never firing it must NOT verify. Guards the fixture
    above against the mistake of attaching a handler and calling it a change."""
    res = wait_for_change(page, '<button id="b">Next</button>',
                          'document.getElementById("b").onclick = '
                          '() => { location.hash = "#never"; };',
                          {"kind": "url_changed"}, timeout=700)
    assert res["verified"] is False, res


def test_appearing_node_is_detected(page):
    html = '<div id="slot"></div>'
    trigger = ('setTimeout(() => { const d = document.createElement("div");'
               ' d.setAttribute("role","alert"); d.textContent = "Only 3 seats remain";'
               ' document.getElementById("slot").appendChild(d); }, 120);')
    res = wait_for_change(page, html, trigger,
                          {"kind": "node_appears", "role": "alert", "name": "Only 3 seats remain"})
    assert res["verified"] is True, res


def test_wrong_expectation_fails_rather_than_passing_on_any_change(page):
    """The important direction. The page DID change - an error appeared - but not in
    the way predicted, so the answer must be a failure that reports what actually
    happened. Reporting success here is the exact bug class Plan A removed on the
    server side."""
    html = '<div id="slot"></div>'
    trigger = ('setTimeout(() => { const d = document.createElement("div");'
               ' d.setAttribute("role","alert"); d.textContent = "Please choose a date";'
               ' document.getElementById("slot").appendChild(d); }, 120);')
    res = wait_for_change(page, html, trigger, {"kind": "url_changed"}, timeout=900)
    assert res["verified"] is False, res
    assert "url_changed" in res["reason"]
    assert "Please choose a date" in res["reason"], "failure should say what did change"


def test_announcement_is_treated_as_a_change_when_expected(page):
    html = ('<div aria-live="polite" id="live">Ready</div>')
    trigger = ('setTimeout(() => { document.getElementById("live").textContent'
               ' = "Seat 12A selected"; }, 120);')
    res = wait_for_change(page, html, trigger, {"kind": "announcement"})
    assert res["verified"] is True, res
    assert "Seat 12A selected" in res["evidence"]


def test_state_flip_is_detected(page):
    page.set_content('<!doctype html><html><body>'
                     '<button id="t" aria-expanded="false" aria-label="Coach options">T</button>'
                     '</body></html>')
    raw = page.evaluate(
        """async () => {
            const baseline = AdaptiveAIWatch.capture(document, { selector: '#t', ref: 'n0' });
            setTimeout(() => document.getElementById('t')
                .setAttribute('aria-expanded', 'true'), 120);
            return await AdaptiveAIWatch.waitFor(document, baseline,
                { kind: 'state_flipped', selector: '#t', state: 'expanded' }, 1500);
        }""")
    res = json.loads(json.dumps(raw))
    assert res["verified"] is True, res
    assert "expanded" in res["evidence"]


def test_title_change_is_detected(page):
    res = wait_for_change(page, "<p>x</p>",
                          'setTimeout(() => { document.title = "Payment complete"; }, 120);',
                          {"kind": "title_changed"})
    assert res["verified"] is True, res
    assert "Payment complete" in res["evidence"]


def test_silence_is_reported_as_silence(page):
    res = wait_for_change(page, '<button>Nothing happens</button>',
                          '/* no change at all */',
                          {"kind": "node_appears", "role": "alert", "name": "Never"},
                          timeout=700)
    assert res["verified"] is False
    assert "nothing observable changed" in res["reason"], res


def test_contenteditable_text_change_is_detected(page):
    html = '<div id="err"></div>'
    trigger = ('setTimeout(() => { const e = document.getElementById("err");'
               ' e.textContent = "Card declined";'
               ' e.setAttribute("role","alert"); }, 120);')
    res = wait_for_change(page, html, trigger,
                          {"kind": "node_appears", "role": "alert", "name": "Card declined"})
    assert res["verified"] is True, res
