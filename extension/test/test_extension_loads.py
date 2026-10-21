"""Does Chrome accept this as a real MV3 extension, and does the content script run?

Everything else in this directory tests a module inside a harness. This one loads
the actual unpacked extension into Chromium the way a user would, because a
manifest that Chrome rejects, a service worker that fails to register, or a
content script that never runs are all failures no unit test can see - and they
are the kind that only surface on demo day.

Run:  python -m pytest extension/test/test_extension_loads.py -p no:warnings -v
"""
import http.server
import os
import socketserver
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

FIXTURE = b"""<!doctype html><html lang="en"><head><title>Fixture booking</title></head>
<body>
<main>
<h1>Choose seats</h1>
<form>
  <label for="pname">Passenger name</label><input id="pname" name="pname">
  <label for="seats">Seats</label><input id="seats" name="seats">
  <label><input type="checkbox" id="ins"> I accept insurance</label>
  <button type="submit">Book tickets</button>
</form>
<img src="data:image/gif;base64,R0lGODlhAQABAAACAP///w==">
<div aria-live="polite" aria-label="Booking status"></div>
</main>
</body></html>"""


GATE_FIXTURE = b"""<!doctype html><html lang="en"><head><title>Pay</title></head><body>
<main>
<h1>Order summary</h1>
<p>2 seats, New Delhi to Chandigarh.</p>
<button id="pay">Pay \xe2\x82\xb9640</button>
<button id="next">Continue</button>
<script>
  window.__paid = 0; window.__next = 0;
  document.getElementById('pay').addEventListener('click', () => { window.__paid++; });
  document.getElementById('next').addEventListener('click', () => { window.__next++; });
</script>
</main>
</body></html>"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(status)
        if body:
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/favicon.ico"):
            # Chrome always asks. Answering 204 keeps the connection tidy instead
            # of raising inside the handler.
            self._send(204)
            return
        if "case=gate" in self.path:
            self._send(200, GATE_FIXTURE)
            return
        self._send(200, FIXTURE)

    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def site():
    # Threading, not the plain TCPServer: Chrome opens the page and asks for
    # /favicon.ico concurrently, and a single-threaded server aborts the second
    # connection ("WinError 10053"), which made this suite pass alone and fail in
    # a full run. That is a harness bug, not a product one, and it is exactly the
    # kind of flake that trains people to ignore red tests.
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/"
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture(scope="module")
def loaded_extension():
    """A persistent context is required: --load-extension is ignored by an
    incognito-style ephemeral context, and the extension must be attached before
    the first navigation.

    channel="chromium" is not optional. Playwright's default headless build is
    the chromium headless *shell*, which cannot load extensions at all - it
    silently runs with none installed, so every assertion below would fail with
    no error anywhere. Measured on this machine: headless shell = never loads,
    channel="chromium" headless = loads and runs."""
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            "",
            headless=True,
            channel="chromium",
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
            ],
        )
        yield ctx
        ctx.close()


def _wait_service_worker(ctx, timeout_s=20):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sw in ctx.service_workers:
            if "chrome-extension://" in sw.url:
                return sw
        time.sleep(0.4)
    return None


def test_service_worker_registers(loaded_extension):
    sw = _wait_service_worker(loaded_extension)
    assert sw is not None, (
        "Chrome never registered src/background.js - the manifest or the worker "
        "is invalid, so nothing downstream can work")
    assert sw.url.startswith("chrome-extension://"), sw.url


def test_content_script_runs_and_reports_real_counts(loaded_extension, site):
    page = loaded_extension.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    page.goto(site, wait_until="load")

    root = page.locator("html")
    # content.js publishes its findings as attributes, so this asserts the script
    # really executed inside the extension world rather than in my test harness.
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=15000)

    assert int(root.get_attribute("data-adaptiveai-interactive")) == 4, \
        "2 inputs + 1 checkbox + 1 button expected"
    assert int(root.get_attribute("data-adaptiveai-missing-alt")) == 1
    assert int(root.get_attribute("data-adaptiveai-unnamed")) == 0
    # A live region is content, not a control: it must be collected without
    # inflating the act-able count.
    assert int(root.get_attribute("data-adaptiveai-nodes")) >= 6
    assert errors == [], f"extension scripts threw on a real page: {errors}"


SW_FIND_AND_FILL = """async (siteUrl) => {
    // chrome.tabs.query() redacts `url` without the "tabs" permission, which
    // this extension deliberately does not ask for. The snapshot carries the
    // page's own location, so the tab is identified from inside the page.
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
        let snap;
        try {
            snap = await chrome.tabs.sendMessage(tab.id,
                { type: 'adaptiveai:snapshot', force: true });
        } catch (e) { continue; }        // no content script on this tab
        if (!snap || !snap.url || !snap.url.startsWith(siteUrl)) continue;
        const node = (snap.nodes || []).find(n => n.name === 'Passenger name');
        if (!node) continue;
        const out = await chrome.tabs.sendMessage(tab.id,
            { type: 'adaptiveai:act', ref: node.ref, action: 'fill',
              value: 'Asha Sharma' });
        return { out: out, ref: node.ref, tabUrl: snap.url };
    }
    return { error: 'no fixture tab answering the content script',
             tabs: tabs.map(t => t.id) };
}"""

SW_FIND_AND_ACT_ON_GHOST = """async (siteUrl) => {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
        let snap;
        try {
            snap = await chrome.tabs.sendMessage(tab.id,
                { type: 'adaptiveai:snapshot', force: true });
        } catch (e) { continue; }
        if (!snap || !snap.url || !snap.url.startsWith(siteUrl)) continue;
        return await chrome.tabs.sendMessage(tab.id,
            { type: 'adaptiveai:act', ref: 'n999', action: 'fill', value: 'x' });
    }
    return { status: 'error', reason: 'no fixture tab found' };
}"""

SW_GATE_CLICK = """async ({siteUrl, confirm}) => {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
        let snap;
        try {
            snap = await chrome.tabs.sendMessage(tab.id,
                { type: 'adaptiveai:snapshot', force: true });
        } catch (e) { continue; }
        if (!snap || !snap.url || !snap.url.startsWith(siteUrl)) continue;
        const node = (snap.nodes || []).find(n => n.name && n.name.indexOf('Pay') === 0);
        if (!node) continue;
        const out = await chrome.tabs.sendMessage(tab.id,
            { type: 'adaptiveai:act', ref: node.ref, action: 'click',
              confirm: confirm });
        return { out: out, name: node.name };
    }
    return { error: 'gate fixture tab not found' };
}"""

SW_NAV_CLICK = """async ({siteUrl}) => {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
        let snap;
        try {
            snap = await chrome.tabs.sendMessage(tab.id,
                { type: 'adaptiveai:snapshot', force: true });
        } catch (e) { continue; }
        if (!snap || !snap.url || !snap.url.startsWith(siteUrl)) continue;
        const node = (snap.nodes || []).find(n => n.name === 'Continue');
        if (!node) continue;
        const out = await chrome.tabs.sendMessage(tab.id,
            { type: 'adaptiveai:act', ref: node.ref, action: 'click' });
        return { out: out };
    }
    return { error: 'gate fixture tab not found' };
}"""


def test_service_worker_drives_an_action_through_to_the_page(loaded_extension, site):
    """The whole path a real task would use: service worker -> content script ->
    actor -> real page -> readback. If any link is missing (actor not listed in
    the manifest, no message handler, refs not resolvable) this fails, which is
    precisely the integration unit tests cannot see.

    A unique query string per test, not just the shared path: an earlier test
    leaves another tab on the same URL open, and the first run of this test
    happily reported "verified" for the WRONG tab while asserting against this
    one. A task runner that acts on "whichever tab looked right" is a bug, so the
    target here is unambiguous by construction."""
    target = site + "?case=fill"
    page = loaded_extension.new_page()
    page.goto(target, wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=15000)

    sw = _wait_service_worker(loaded_extension)
    assert sw is not None, "no service worker to act as the task runner"

    result = sw.evaluate(SW_FIND_AND_FILL, target)
    assert "out" in result, result
    out = result["out"]
    assert out["status"] == "verified", out
    assert out["readback"] == "Asha Sharma", out
    assert result["tabUrl"] == target, result
    assert page.input_value("#pname") == "Asha Sharma"
    page.close()


def test_service_worker_reports_a_ref_that_is_no_longer_in_the_snapshot(loaded_extension, site):
    target = site + "?case=ghost"
    page = loaded_extension.new_page()
    page.goto(target, wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')", timeout=15000)
    sw = _wait_service_worker(loaded_extension)
    result = sw.evaluate(SW_FIND_AND_ACT_ON_GHOST, target)
    assert result["status"] == "not_found", result
    page.close()


def test_gated_payment_is_refused_and_the_handler_never_fires(loaded_extension, site):
    """The point of the gate: it is enforced in the content script, so a planner
    that decides to press "Pay ₹640" cannot do it by asking nicely. A refusal that
    still ran the click would be worse than no gate at all, because it would look
    like a safety feature - so the handler counter is the real assertion here."""
    target = site + "?case=gate"
    page = loaded_extension.new_page()
    page.goto(target, wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')", timeout=15000)
    sw = _wait_service_worker(loaded_extension)

    refused = sw.evaluate(SW_GATE_CLICK, {"siteUrl": target, "confirm": False})
    assert "out" in refused, refused
    assert refused["out"]["status"] == "gated", refused
    assert refused["name"].startswith("Pay"), refused
    assert refused["out"]["gate"]["amount"]["value"] == 640, refused["out"]["gate"]
    assert page.evaluate("() => window.__paid") == 0, "a gated click still fired"

    approved = sw.evaluate(SW_GATE_CLICK, {"siteUrl": target, "confirm": True})
    assert approved["out"]["status"] == "pressed", approved
    assert page.evaluate("() => window.__paid") == 1, "confirmed click did not land"

    # Ordinary navigation must not be stopped, or the gate trains dismissal.
    plain = sw.evaluate(SW_NAV_CLICK, {"siteUrl": target})
    assert plain["out"]["status"] == "pressed", plain
    assert page.evaluate("() => window.__next") == 1, plain
    page.close()


def test_popup_page_loads_without_errors(loaded_extension):
    sw = _wait_service_worker(loaded_extension)
    assert sw is not None
    ext_id = sw.url.split("/")[2]
    page = loaded_extension.new_page()
    errors = []
    page.on("pageerror", lambda e: errors.append(str(e)[:200]))
    page.goto(f"chrome-extension://{ext_id}/popup.html", wait_until="load")
    # The popup's own status line is the evidence it ran. Opened as a plain tab
    # it cannot see a content-scripted page, and it must SAY that rather than
    # showing zero counts as if the page were empty - that distinction is the
    # difference between an honest failure and a silent one.
    status = page.locator("#status")
    page.wait_for_function(
        "() => document.getElementById('status').textContent.length > 0", timeout=10000)
    text = status.inner_text()
    assert text != "Reading this page…", "popup never resolved its request"
    assert ("cannot read this page" in text or "no controls" in text.lower()
            or "act-able" in text), f"unexpected popup status: {text!r}"
    assert errors == [], f"popup scripts threw: {errors}"
    page.close()
