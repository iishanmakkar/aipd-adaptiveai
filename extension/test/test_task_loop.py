"""The task loop, end to end, in the extension Chrome actually loaded.

Nothing here is mocked inside the extension: a real service worker plans through a
stub HTTP server that speaks the real /api/extension/step contract, acts through
the real content script on a real page, and narrates through a real offscreen
document. What the test reads back is the DOM, the recorded steps, the bytes that
went to the server, and what the speech engine said about itself.

This is the file that answers "does it actually do something when told" - which
every other suite in this directory deliberately avoids, because each tests one
module and a green module suite can still add up to an extension that does nothing.

Run:  python -m pytest extension/test/test_task_loop.py -p no:warnings -v
"""
import http.server
import json
import os
import re
import socketserver
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE = b"""<!doctype html><html lang="en"><head><title>Seat details</title></head>
<body>
<main>
<h1>Passenger details</h1>
<label for="pname">Passenger name</label><input id="pname" name="pname">
<label for="pemail">Email address</label><input id="pemail" name="pemail" type="email">
<button id="next">Continue</button>
<button id="pay">Pay \xe2\x82\xb9640</button>
<script>
  window.__paid = 0; window.__next = 0;
  document.getElementById('pay').addEventListener('click', () => { window.__paid++; });
  document.getElementById('next').addEventListener('click', () => { window.__next++; });
</script>
</main>
</body></html>"""

STATE = {"replies": [], "bodies": [], "lock": threading.Lock()}


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/favicon.ico"):
            self._send(204)
            return
        self._send(200, PAGE)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        with STATE["lock"]:
            STATE["bodies"].append(raw.decode("utf-8", "replace"))
            if STATE["replies"]:
                reply = STATE["replies"].pop(0)
            else:
                # Ran out of script: say so as the contract's own refusal rather
                # than inventing a step, so a test that expected more steps fails
                # loudly instead of drifting on.
                reply = {"status": "cannot", "narration": "script exhausted",
                         "why": "test script exhausted"}
        self._send(200, json.dumps(reply).encode("utf-8"),
                   "application/json")

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def ctx():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            "",
            headless=True,
            channel="chromium",
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"],
        )
        yield context
        context.close()


@pytest.fixture(scope="module")
def backend():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _wait_service_worker(context, timeout_s=45):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sw in context.service_workers:
            if "chrome-extension://" in sw.url:
                return sw
        time.sleep(0.4)
    return None


@pytest.fixture
def runner(ctx, backend):
    """A page with the content script up, the worker awake, and the planner
    pointed at the stub backend."""
    page = ctx.new_page()
    page.goto(backend + "/", wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=20000)
    sw = _wait_service_worker(ctx)
    assert sw is not None, "the worker never registered, so no task can run"
    sw.evaluate("""(base) => new Promise(resolve =>
        chrome.storage.local.set({adaptiveai_backend: base,
                                  adaptiveai_answer_timeout_ms: 1500}, resolve))""",
                backend)
    with STATE["lock"]:
        STATE["replies"].clear()
        STATE["bodies"].clear()
    yield {"page": page, "sw": sw, "backend": backend}
    page.close()


def script(sw, replies):
    with STATE["lock"]:
        STATE["replies"].extend(replies)


def run(sw, goal):
    return sw.evaluate("(goal) => runTask(goal)", goal)


def node_ref(sw, label):
    """The ref the content script gave this control, read through the worker -
    a normal page has no `chrome.runtime`, so the test cannot ask it.

    The callback form is deliberate: `sendMessage` resolves to nothing when the
    receiving end is missing, and an awaited `snap.nodes` on that undefined is how
    a test starts reporting "service worker restarted" instead of its real reason.
    """
    return sw.evaluate("""async (label) => {
        const tabs = await chrome.tabs.query({active: true, currentWindow: true});
        if (!tabs.length) throw new Error('no active tab to read a snapshot from');
        const snap = await new Promise(r => chrome.tabs.sendMessage(
            tabs[0].id, {type: 'adaptiveai:snapshot', force: true},
            reply => r(chrome.runtime.lastError ? null : reply)));
        const hit = ((snap && snap.nodes) || []).find(n => n.name === label);
        return hit ? hit.ref : null;
    }""", label)


def test_one_step_task_fills_the_field_and_verifies_it(runner):
    page, sw = runner["page"], runner["sw"]
    sw.evaluate("""() => AdaptiveAIVault.set('Passenger name', 'Asha Sharma')""")
    ref = node_ref(sw, "Passenger name")
    assert ref, "the content script did not name that field"
    script(sw, [{"status": "act", "action": "fill", "ref": ref,
                 "value_from": "profile", "value_label": "passenger name",
                 "expect": "none", "narration": "Entering your passenger name."},
                {"status": "done", "narration": "Your name is in the field."}])

    reply = run(sw, "Put my passenger name in the booking form")
    assert reply["ok"] is True, reply
    result = reply["result"]
    assert result["status"] == "completed", result
    assert result["stepsVerified"] == 1, result
    assert page.input_value("#pname") == "Asha Sharma", "the DOM says otherwise"


def test_the_planner_never_saw_the_value_it_asked_for(runner):
    """The privacy boundary measured on the wire the extension actually used."""
    page, sw = runner["page"], runner["sw"]
    sw.evaluate("""() => AdaptiveAIVault.set('Email address', 'asha@example.com')""")
    ref = node_ref(sw, "Email address")
    script(sw, [{"status": "act", "action": "fill", "ref": ref,
                 "value_from": "profile", "value_label": "email address",
                 "expect": "none", "narration": "Entering your email."},
                {"status": "done", "narration": "Done."}])
    run(sw, "Fill in my email")
    bodies = json.dumps(STATE["bodies"])
    assert "asha@example.com" not in bodies
    assert '"value"' not in bodies
    assert "selector" not in bodies
    payload = json.loads(STATE["bodies"][0])
    labels = {n["name"] for n in payload["nodes"]}
    assert "Email address" in labels, "structure was supposed to survive"
    assert page.input_value("#pemail") == "asha@example.com"


def test_a_failed_step_halts_the_run(runner):
    page, sw = runner["page"], runner["sw"]
    script(sw, [{"status": "act", "action": "fill", "ref": "does-not-exist",
                 "value_from": "literal", "value_literal": "x",
                 "narration": "Filling something."}])
    result = run(sw, "Fill the name field")["result"]
    assert result["status"] == "stopped", result
    assert result["steps"][-1]["status"] == "cannot" or \
        result["steps"][-1]["status"].startswith("planner_"), result


def test_a_payment_is_gated_and_a_missing_answer_is_a_no(runner):
    """Silence is a refusal: the user may simply not have heard the question."""
    page, sw = runner["page"], runner["sw"]
    ref = node_ref(sw, "Pay \u20b9640")
    script(sw, [{"status": "act", "action": "click", "ref": ref,
                 "expect": "none", "narration": "Paying now."}])
    result = run(sw, "Pay for my tickets")["result"]
    assert result["status"] == "cancelled", result
    assert page.evaluate("() => window.__paid") == 0, "money was spent"
    assert any("Say yes" in line or "go ahead" in line.lower() or "ahead" in line
               for line in result["narration"]), result["narration"]


def test_an_answered_yes_releases_the_gate(runner):
    page, sw = runner["page"], runner["sw"]
    ref = node_ref(sw, "Pay \u20b9640")
    script(sw, [{"status": "act", "action": "click", "ref": ref,
                 "expect": "none", "narration": "Paying now."},
                {"status": "done", "narration": "Paid."}])
    # The answer has to arrive while the loop is waiting for it, which means the
    # run and the answer are made in the same worker tick: a sync test cannot
    # interleave two evaluates on one service worker. This is the same hand the
    # popup plays with its Yes button.
    sw.evaluate("""() => {
        globalThis.__done = null;
        runTask('Pay for my tickets').then(r => { globalThis.__done = r; });
        const poll = setInterval(() => {
          if (ANSWER) { clearInterval(poll); ANSWER('yes'); }
        }, 100);
        setTimeout(() => clearInterval(poll), 20000);
        return true;
    }""")
    done = _until(sw, "() => globalThis.__done")
    assert done and done["ok"], done
    assert done["result"]["status"] == "completed", done["result"]
    gated = [s for s in done["result"]["steps"] if s.get("confirmedByUser")]
    assert gated, done["result"]["steps"]
    assert page.evaluate("() => window.__paid") == 1, \
        "the press the user approved never happened"


def _until(sw, expression, timeout_s=30, accept=None):
    """Poll a worker expression until it is truthy - or until `accept` says the
    value is the one worth returning. Narration is fire-and-forget, so "the log is
    non-empty" is not "this run's announcement is in the log"."""
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = sw.evaluate(expression)
        if last and (accept is None or accept(last)):
            return last
        time.sleep(0.3)
    return last


def test_narration_reaches_the_speech_document_and_reports_the_engine(runner):
    """Audio cannot be captured here, so the claim is narrower and still honest:
    every announcement the loop made was handed to the speech path, and the speech
    path stated what its engine did. `no-voices` on a machine without text to
    speech is a real outcome; what must never happen is an announcement that
    reports nothing at all, because that is a silent assistant with a green log."""
    page, sw = runner["page"], runner["sw"]
    script(sw, [{"status": "done", "narration": "There is nothing to do here."}])
    run(sw, "Do something")
    # A second run with a different announcement: the first call creates the
    # speech document and every later call reuses it, which is exactly where a
    # cached-value-instead-of-cached-promise bug lands.
    script(sw, [{"status": "done", "narration": "Second announcement."}])
    run(sw, "Do something else")
    log = _until(sw, "() => speechLog()",
                 accept=lambda v: any("nothing to do" in a["text"].lower()
                                      for a in v.get("attempts") or [])
                 and any("second announcement" in a["text"].lower()
                         for a in v.get("attempts") or []))
    assert log and log["ok"], log
    attempts = log["attempts"]
    assert attempts, "the worker recorded no announcement"
    target = [a for a in attempts if "nothing to do" in a["text"].lower()]
    second = [a for a in attempts if "second announcement" in a["text"].lower()]
    assert target and second, attempts
    assert len(target) == 1 and len(second) == 1, \
        "an announcement was recorded twice: %s" % attempts
    for a in attempts:
        assert isinstance(a["ok"], bool), a
        if not a["ok"]:
            assert a["reason"], a
    definite = [a for a in target if a["ok"] or re.search(
        r"voice|silent|engine|offscreen", (a["reason"] + a["status"]).lower())]
    assert definite, ("the speech path accepted the announcement and reported "
                      "nothing about it: %s" % target)
    print("\nnarration attempts: " + json.dumps(target))
    if log["engine"] is not None:
        print("engine outcomes: " + ", ".join(
            sorted({e["status"] for e in log["engine"]})))


def test_two_runs_at_once_are_refused(runner):
    page, sw = runner["page"], runner["sw"]
    ref = node_ref(sw, "Continue")
    # `expect: url_changed` on a page that does not navigate keeps the first run
    # waiting on its own verification, which is the window in which a second task
    # must be refused rather than queued: two loops acting in one tab is a race on
    # a page the user cannot see.
    script(sw, [{"status": "act", "action": "click", "ref": ref,
                 "expect": "url_changed", "narration": "Continuing."}])
    sw.evaluate("""() => {
        globalThis.__second = null;
        runTask('first task');
        setTimeout(() => runTask('second task').then(r => { globalThis.__second = r; }), 400);
        return true;
    }""")
    second = _until(sw, "() => globalThis.__second", timeout_s=20)
    assert second is not None, "the second run never answered"
    assert second["ok"] is False, second
    assert "already" in second["reason"].lower(), second
