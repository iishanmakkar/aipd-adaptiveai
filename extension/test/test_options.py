"""Options page and the settings the worker reads back from it.

Proves the loop a user actually needs: type details in once, on an extension page,
then have the service worker see the same stored values - and prove what crosses
that boundary is the LABEL list and the ceiling, never the values themselves.

Run:  python -m pytest extension/test/test_options.py -p no:warnings
"""
import json
import os
import socketserver
import threading
import http.server
import time

import pytest
from playwright.sync_api import sync_playwright

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BLANK = b"<!doctype html><html><head><title>Blank</title></head><body><p>x</p></body></html>"


class _H(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith("/favicon.ico"):
            self.send_response(204)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(BLANK)))
        self.end_headers()
        self.wfile.write(BLANK)

    def log_message(self, *a):
        pass


@pytest.fixture(scope="module")
def ext():
    """One browser, one extension id, yielded only once the worker is up."""
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _H)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            "", headless=True, channel="chromium",
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"])
        wake = ctx.new_page()
        wake.goto(f"http://127.0.0.1:{port}/")
        deadline = time.time() + 45
        sw_url = None
        while time.time() < deadline:
            for sw in ctx.service_workers:
                if sw.url.startswith("chrome-extension://"):
                    sw_url = sw.url
                    break
            if sw_url:
                break
            time.sleep(0.4)
        assert sw_url, "service worker never registered"
        ext_id = sw_url.split("/")[2]
        yield ctx, ext_id, sw_url
        ctx.close()
    httpd.shutdown()
    httpd.server_close()


def ext_of(sw_url):
    return sw_url.split("/")[2]


def settings(ctx, sw_url):
    """Ask the worker what it knows. chrome.runtime.sendMessage from any extension
    page reaches it, and the vault lives in chrome.storage rather than in a page.

    Bounded on purpose: an unanswered message would otherwise hang the suite until
    CI's job timeout, which is the least readable failure there is."""
    page = ctx.new_page()
    page.goto(f"chrome-extension://{ext_of(sw_url)}/options.html", wait_until="load")
    value = page.evaluate("""async () => {
        const timer = new Promise((_, reject) => setTimeout(
            () => reject(new Error('worker did not answer get-settings in 8s')), 8000));
        const reply = chrome.runtime.sendMessage({ type: 'adaptiveai:get-settings' });
        return await Promise.race([reply, timer]);
    }""")
    page.close()
    return json.loads(json.dumps(value))


def test_filling_the_form_makes_the_values_visible_to_the_worker(ext):
    ctx, ext_id, sw_url = ext
    page = ctx.new_page()
    page.goto(f"chrome-extension://{ext_id}/options.html", wait_until="load")
    page.fill("#f-full-name", "Asha Sharma")
    page.fill("#f-email", "asha@example.com")
    page.fill("#f-aadhaar-number", "123456789012")
    page.fill("#f-ceiling", "1500")
    page.click("#save")
    page.wait_for_function(
        "() => /Saved/.test(document.getElementById('status').textContent)", timeout=8000)

    assert "Saved 3 details" in page.inner_text("#status")
    page.close()

    got = settings(ctx, sw_url)
    assert set(got["labels"]) >= {"full name", "email", "aadhaar number"}, got
    assert got["spendCeiling"] == 1500, got
    blob = json.dumps(got)
    for secret in ("Asha Sharma", "asha@example.com", "123456789012"):
        assert secret not in blob, f"value crossed into the settings response: {secret}"


def test_page_is_announced_through_its_own_controls(ext):
    """A user who cannot see the page must be able to tell that saving worked
    without hunting for it: the status is a live region and gets replaced, not
    appended to forever."""
    ctx, ext_id, sw_url = ext
    page = ctx.new_page()
    page.goto(f"chrome-extension://{ext_id}/options.html", wait_until="load")
    assert page.get_attribute("#status", "role") == "status"
    assert page.get_attribute("#status", "aria-live") == "polite"
    # Everything must be labelled, not identified by position or colour.
    for selector in ("#f-full-name", "#f-email", "#f-phone", "#f-ceiling"):
        assert page.locator(f'label[for="{selector[1:]}"]').count() == 1, selector
    page.fill("#f-phone", "9876543210")
    page.click("#save")
    page.wait_for_function(
        "() => /Saved \\d+/.test(document.getElementById('status').textContent)",
        timeout=8000)
    # The form saves whatever is filled in, so the count is the whole form rather
    # than the one box this test touched. Assert the pattern and the fact, not a
    # number that depends on test order.
    assert "detail" in page.inner_text("#status")
    assert "phone" in settings(ctx, sw_url)["labels"]
    page.close()


def test_delete_needs_two_deliberate_presses(ext):
    ctx, ext_id, sw_url = ext
    page = ctx.new_page()
    page.goto(f"chrome-extension://{ext_id}/options.html", wait_until="load")
    page.click("#wipe")
    status = page.inner_text("#status")
    assert "again" in status.lower(), status
    assert settings(ctx, sw_url)["labels"] != [], "one press already deleted everything"

    page.click("#wipe")
    page.wait_for_function(
        "() => /Deleted/.test(document.getElementById('status').textContent)", timeout=8000)
    assert settings(ctx, sw_url)["labels"] == []
    assert settings(ctx, sw_url)["spendCeiling"] is None
    page.close()
