"""The planner client: what leaves the device, and what comes back as a step.

These run the real `ax.js`, `privacy.js` and `vault.js` in a real Chromium with a
captured `fetch`, so the assertions are about the bytes the extension would put on
the wire - not about a mock's opinion of them. The property that matters most is
asymmetric: a value must be *absent* from the request and *present* in the step
the actor gets, because that is the whole privacy design in one line.

Run:  python -m pytest extension/test/test_planner.py -p no:warnings
"""
import os

import pytest
from playwright.sync_api import sync_playwright

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")

MEMORY_STORE = """
window.__memStore = (() => {
  const data = {};
  return {
    get(keys, cb) {
      const out = {};
      (Array.isArray(keys) ? keys : [keys]).forEach(k => {
        if (Object.prototype.hasOwnProperty.call(data, k)) out[k] = data[k];
      });
      cb(out);
    },
    set(obj, cb) { Object.assign(data, obj); cb && cb(); },
    remove(keys, cb) {
      (Array.isArray(keys) ? keys : [keys]).forEach(k => delete data[k]);
      cb && cb();
    },
  };
})();
"""

FORM_PAGE = """<!doctype html><html><body>
<h1>Checkout</h1>
<label for="n">Passenger name</label><input id="n" name="n">
<label for="e">Email address</label><input id="e" name="e" type="email">
<label for="p">Password</label><input id="p" name="p" type="password" value="hunter2">
<button id="go">Continue</button>
<button id="pay">Pay \u20b9640</button>
</body></html>"""

CAPTURE_FETCH = """
window.__sent = [];
window.__reply = {status: 'cannot', narration: 'unset'};
window.__failWith = null;
window.fetch = function (url, init) {
  window.__sent.push({url: url, init: init});
  if (window.__failWith) return Promise.reject(new Error(window.__failWith));
  const body = window.__reply;
  return Promise.resolve({
    ok: body.__status ? body.__status < 400 : true,
    status: body.__status || 200,
    json: () => Promise.resolve(body),
  });
};
// The planner reads the backend URL and the bearer token out of
// chrome.storage.local - which the worker has and an ordinary page does not.
// Backed by the same in-memory store the vault uses, so a saved token is a
// storage write rather than a stubbed call.
window.chrome = window.chrome || {};
window.chrome.runtime = { lastError: null };
window.chrome.storage = { local: window.__memStore };
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
    pg.add_init_script(path=os.path.join(SRC, "ax.js"))
    pg.add_init_script(path=os.path.join(SRC, "vault.js"))
    pg.add_init_script(path=os.path.join(SRC, "privacy.js"))
    pg.add_init_script(path=os.path.join(SRC, "planner.js"))
    pg.add_init_script(MEMORY_STORE)
    pg.add_init_script(CAPTURE_FETCH)
    pg.goto("about:blank")
    pg.set_content(FORM_PAGE)
    pg.evaluate("() => AdaptiveAIVault.useStore(window.__memStore)")
    pg.evaluate("""async () => {
        await AdaptiveAIVault.set('Email address', 'asha@example.com');
        await AdaptiveAIVault.set('Passenger name', 'Asha Sharma');
    }""")
    pg.evaluate("""() => {
        window.__planner = AdaptiveAIPlanner.create({});
        window.__snap = AdaptiveAIAX.computeSnapshot(document);
    }""")
    yield pg
    ctx.close()


def step(page, reply, goal="Book a seat", outcome=None):
    """Drive one nextStep() with a canned reply and return the step the runner got.

    Playwright awaits the Promise the page function returns, so this needs no
    second round trip to read a result back out.
    """
    return page.evaluate(
        """([reply, goal, outcome]) => {
            window.__sent = [];
            window.__reply = reply;
            return window.__planner.nextStep({
                goal: goal, snapshot: window.__snap,
                availableLabels: ['email', 'full name', 'password'],
                lastOutcome: outcome,
            });
        }""", [reply, goal, outcome])


def sent_body(page):
    return page.evaluate("() => (window.__sent[0] ? JSON.parse(window.__sent[0].init.body) : null)")


def sent_raw(page):
    return page.evaluate("() => (window.__sent[0] ? window.__sent[0].init.body : '')")


def test_request_is_posted_to_the_step_path(page):
    step(page, {"status": "done", "narration": "All set."})
    target = page.evaluate("() => window.__sent[0].url")
    assert target.endswith("/api/extension/step"), target
    assert page.evaluate("() => window.__sent[0].init.method") == "POST"


def test_the_request_carries_structure_and_never_a_value(page):
    """The typed password is on the page while this request is built. If any of
    it reaches the wire, the redaction step was skipped."""
    page.evaluate("() => document.getElementById('n').value = 'Vikram Singh'")
    page.evaluate("() => { window.__snap = AdaptiveAIAX.computeSnapshot(document); }")
    step(page, {"status": "done", "narration": "All set."})
    raw = sent_raw(page)
    assert "Vikram Singh" not in raw
    assert "hunter2" not in raw
    assert "asha@example.com" not in raw
    body = sent_body(page)
    names = [n["name"] for n in body["nodes"]]
    assert "Passenger name" in names and "Email address" in names
    for node in body["nodes"]:
        assert "value" not in node
        assert "selector" not in node
        assert "bounds" not in node
        assert "identity" not in node
    assert body["available_labels"] == ["email", "full name", "password"]


def test_a_profile_reply_resolves_from_the_vault_on_device(page):
    email_node = page.evaluate(
        "() => window.__snap.nodes.find(n => n.name === 'Email address').ref")
    got = step(page, {"status": "act", "action": "fill", "ref": email_node,
                      "value_from": "profile", "value_label": "email",
                      "narration": "Entering your email."})
    assert got["action"] == "fill" and got["ref"] == email_node
    assert got["value"] == "asha@example.com"
    # The value the step now holds must NOT be in the request that produced it.
    assert "asha@example.com" not in sent_raw(page)


def test_a_missing_profile_detail_asks_the_user_instead_of_guessing(page):
    name_node = page.evaluate(
        "() => window.__snap.nodes.find(n => n.name === 'Passenger name').ref")
    page.evaluate("() => AdaptiveAIVault.wipe()")
    got = step(page, {"status": "act", "action": "fill", "ref": name_node,
                      "value_from": "profile", "value_label": "full name",
                      "narration": "Entering your name."})
    assert got["control"] == "ask"
    assert "setup" in got["say"] or "tell me" in got["say"].lower()


def test_a_reply_naming_an_absent_control_is_refused(page):
    got = step(page, {"status": "act", "action": "click", "ref": "zz9",
                      "narration": "Pressing something."})
    assert got["control"] == "cannot"
    assert "not on this page" in got["say"]


def test_a_password_field_is_refused_locally_too(page):
    """The server refuses password fields. This refuses them again, because the
    copy that presses the button is the copy that must not need to trust the
    other one."""
    pw = page.evaluate("() => window.__snap.nodes.find(n => n.kind === 'password').ref")
    got = step(page, {"status": "act", "action": "fill", "ref": pw,
                      "value_from": "literal", "value_literal": "hunter2",
                      "narration": "Signing you in."})
    assert got["control"] == "cannot"
    assert "password" in got["say"].lower()


def test_a_literal_the_user_said_passes_through(page):
    cont = page.evaluate("() => window.__snap.nodes.find(n => n.name === 'Continue').ref")
    got = step(page, {"status": "act", "action": "click", "ref": cont,
                      "expect": "url_changed", "narration": "Continuing."})
    assert got["expect"] == "url_changed"


def test_expect_none_becomes_null_so_nothing_is_awaited(page):
    cont = page.evaluate("() => window.__snap.nodes.find(n => n.name === 'Continue').ref")
    got = step(page, {"status": "act", "action": "click", "ref": cont,
                      "expect": "none", "narration": "Continuing."})
    assert got["expect"] is None


@pytest.mark.parametrize("status,control", [
    ("done", "done"), ("ask_user", "ask"), ("cannot", "cannot")])
def test_non_action_replies_become_controls_the_runner_stops_on(page, status, control):
    got = step(page, {"status": status, "narration": "Because I said so."})
    assert got["control"] == control
    assert got["say"] == "Because I said so."


def test_an_unreachable_planner_is_reported_not_replaced(page):
    page.evaluate("() => { window.__failWith = 'Failed to fetch'; }")
    got = step(page, {"status": "done", "narration": "unused"})
    page.evaluate("() => { window.__failWith = null; }")
    assert got["control"] == "cannot"
    assert "could not reach" in got["say"].lower()


def test_a_service_error_is_reported_with_its_detail(page):
    got = step(page, {"__status": 503, "detail": "step planner unavailable: timed out"})
    assert got["control"] == "cannot"
    assert "timed out" in got["say"]


def test_no_token_sends_no_authorization_header(page):
    step(page, {"status": "done", "narration": "ok"})
    headers = page.evaluate("() => window.__sent[0].init.headers")
    assert "authorization" not in {k.lower() for k in headers}


def test_a_saved_token_is_sent_as_a_bearer(page):
    page.evaluate("() => window.__memStore.set({adaptiveai_token: 'tok-123'})")
    step(page, {"status": "done", "narration": "ok"})
    headers = page.evaluate("() => window.__sent[0].init.headers")
    assert headers.get("authorization") == "Bearer tok-123"
    page.evaluate("() => window.__memStore.remove(['adaptiveai_token'])")


def test_history_records_the_outcome_of_the_previous_step(page):
    cont = page.evaluate("() => window.__snap.nodes.find(n => n.name === 'Continue').ref")
    step(page, {"status": "act", "action": "click", "ref": cont,
                "expect": "url_changed", "narration": "Continuing."})
    step(page, {"status": "done", "narration": "Booked."},
         outcome={"status": "verified", "change": {"description": "url changed"},
                  "reason": ""})
    body = sent_body(page)
    assert len(body["history"]) == 1
    entry = body["history"][0]
    assert entry["status"] == "verified"
    assert entry["change"] == "url changed"
    assert entry["ref"] == cont
