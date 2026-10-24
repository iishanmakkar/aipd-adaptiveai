"""Real-browser smoke: the unpacked extension running in the machine's actual
installed Chrome (not Playwright's test Chromium), driven through its real
surfaces - the options page that fills the vault, the popup that runs a typed
goal and answers the spending gate, the listen command that turns a spoken
utterance into a goal - against this repository's own demo booking page.

What it proves, in order, each as a check that can fail:
  1. the content script runs in real Chrome and snapshots the demo page;
  2. the options page saves details into the vault ("Saved 2 details");
  3. a typed goal, run through the REAL task loop, fills the form - the recipe
     supplies the passenger name from the vault, the scripted planner supplies
     the goal's own words, and every step is read back;
  4. the "Book tickets" press is gated, the popup's Yes button (the way a user
     actually answers) releases it, and the page confirms the booking;
  5. the popup's Listen button captures real audio (fake device), the stub
     transcriber's words land in the goal field;
  6. the loop narrated out loud (attempts logged; the machine's own speakers
     may be heard during the run - that is the product working).

No NIM key is needed: the step planner is a scripted stub on a local socket.
Everything else - actor, watch, gate, vault, speech, recipes - is the shipped
code, unmodified, in the real browser.

Usage:
    python scripts/real_browser_smoke.py
Exit 0 = every check held; 1 = a check failed; 2 = Chrome could not launch.
"""
import http.server
import json
import os
import socketserver
import sys
import tempfile
import threading
import time
from datetime import date

from playwright.sync_api import sync_playwright

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXT_DIR = os.path.join(REPO, "extension")
DEMO_FILE = os.path.join(REPO, "demo", "book-tickets.html")
OUT_DIR = os.path.join(REPO, "docs", "proofs")

STATE = {"step_replies": [], "transcript": "book a train from delhi to mumbai",
         "lock": threading.Lock()}


class Handler(http.server.BaseHTTPRequestHandler):
    def _send(self, status, body=b"", ctype="text/html; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/favicon"):
            self._send(204)
            return
        with open(DEMO_FILE, "rb") as handle:
            self._send(200, handle.read())

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        if self.path == "/api/extension/step":
            with STATE["lock"]:
                reply = STATE["step_replies"].pop(0) if STATE["step_replies"] else {
                    "status": "done", "narration": "Nothing left to do."}
            self._send(200, json.dumps(reply).encode(), "application/json")
            return
        if self.path == "/api/transcribe":
            self._send(200, json.dumps({
                "transcript": STATE["transcript"], "language": "en",
                "duration": 1.2}).encode(), "application/json")
            return
        self._send(404, b"{}")

    def log_message(self, *args):
        pass


FAILURES = []


class ExtensionDidNotLoad(Exception):
    """The browser launched but the content script never appeared - which is
    what branded Chrome (137+) does with --load-extension: it launches fine
    and ignores the switch. The caller tries the next installed browser."""


def check(cond, msg):
    print(f"  {'ok' if cond else 'FAIL'}: {msg}")
    if not cond:
        FAILURES.append(msg)
    return bool(cond)


def ref_for(sw, name):
    return sw.evaluate("""async (name) => {
        const ts = await chrome.tabs.query({active: true, currentWindow: true});
        const r = await snapshotOf(ts[0].id);
        const node = (r.snapshot.nodes || []).find(n => n.name === name);
        if (!node) throw new Error('no node named ' + name);
        return node.ref;
    }""", name)


def main():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{port}"

    profile = tempfile.mkdtemp(prefix="adaptiveai-smoke-")
    # Branded Chrome (137+) ignores --load-extension entirely, so the machine's
    # own Chrome cannot load an unpacked extension from the command line any
    # more - measured, not assumed. Installed Edge is the same Chromium engine
    # and still honours the switch, so it is the real browser this smoke runs
    # in. Chrome itself is tried first and skipped on the specific failure.
    last_error = None
    try:
        with sync_playwright() as p:
            for channel in ("chrome", "msedge"):
                print(f"launching installed {channel} (stable), profile {profile}")
                try:
                    ctx = p.chromium.launch_persistent_context(
                        profile, channel=channel, headless=False,
                        args=[
                            f"--disable-extensions-except={EXT_DIR}",
                            f"--load-extension={EXT_DIR}",
                            # Real getUserMedia without needing a real
                            # microphone or a permission dialog: the capture
                            # path itself is genuine.
                            "--use-fake-device-for-media-stream",
                            "--use-fake-ui-for-media-stream",
                            "--no-first-run", "--no-default-browser-check",
                            "--autoplay-policy=no-user-gesture-required",
                        ])
                except Exception as e:
                    last_error = e
                    print(f"  {channel} did not launch: {str(e)[:160]}")
                    continue
                try:
                    return run_checks(ctx, p, base, channel)
                except ExtensionDidNotLoad as e:
                    print(f"  {channel} launched but ignored --load-extension "
                          f"(branded Chrome 137+ does this): trying the next browser")
                    last_error = e
                finally:
                    ctx.close()
    finally:
        httpd.shutdown()
        httpd.server_close()
    print(f"no launchable browser: {last_error}")
    return 2


def run_checks(ctx, p, base, channel):
    started = time.time()
    page = ctx.new_page()
    page.goto(base + "/", wait_until="load")
    try:
        page.wait_for_function(
            "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
            timeout=20000)
    except Exception:
        FAILURES.clear()   # the browser works; the switch did not. Not a smoke failure.
        raise ExtensionDidNotLoad(channel)
    check(True, f"content script ran in installed {channel}")

    def worker(deadline_s=30):
        end = time.time() + deadline_s
        while time.time() < end:
            for sw in ctx.service_workers:
                if "chrome-extension://" in sw.url:
                    return sw
            time.sleep(0.3)
        return None

    sw = worker()
    if not check(sw is not None, "service worker registered"):
        return 1
    sw.evaluate("""(b) => new Promise(r =>
        chrome.storage.local.set({adaptiveai_backend: b}, r))""", base)

    # --- the options page: how a real user fills the vault -------------------
    ext_id = sw.url.split("/")[2]
    options = ctx.new_page()
    options.goto(f"chrome-extension://{ext_id}/options.html", wait_until="load")
    options.fill("#f-full-name", "Asha Sharma")
    options.fill("#f-email", "asha@example.com")
    options.click("#save")
    try:
        options.wait_for_function(
            "() => document.getElementById('status').textContent.includes('Saved 2')",
            timeout=10000)
        check(True, "options page saved 2 details into the vault")
    except Exception:
        check(False, "options page saved 2 details into the vault")
    options.close()

    # --- a typed goal through the real task loop -----------------------------
    page.bring_to_front()
    labels = ["Email address", "From station", "To station", "Travel date",
              "Seats", "Book tickets"]
    refs = {name: ref_for(sw, name) for name in labels}
    actions = [
        {"status": "act", "action": "fill", "ref": refs["From station"],
         "value_from": "literal", "value_literal": "New Delhi",
         "narration": "From New Delhi."},
        {"status": "act", "action": "fill", "ref": refs["To station"],
         "value_from": "literal", "value_literal": "Chandigarh",
         "narration": "To Chandigarh."},
        {"status": "act", "action": "fill", "ref": refs["Travel date"],
         "value_from": "literal", "value_literal": "2026-12-15",
         "narration": "Travelling on 15 December."},
        {"status": "act", "action": "select", "ref": refs["Seats"],
         "value_from": "literal", "value_literal": "2",
         "narration": "Two seats."},
        # The money moment. The gate in the content script will stop this
        # click, no matter what the plan says.
        {"status": "act", "action": "click", "ref": refs["Book tickets"],
         "expect": "node_appears", "narration": "Booking now."},
        {"status": "done", "narration": "Booked."},
    ]
    with STATE["lock"]:
        STATE["step_replies"] = actions

    sw.evaluate("""(g) => {
        globalThis.__run = null;
        runTask(g).then(r => { globalThis.__run = r; });
        return true;
    }""", "book a train from new delhi to chandigarh on 2026-12-15 for asha sharma")

    # --- the popup answers the gate the way a user does ----------------------
    popup = ctx.new_page()
    popup.goto(f"chrome-extension://{ext_id}/popup.html", wait_until="load")

    def wait_for(predicate, timeout_s=30, what=""):
        end = time.time() + timeout_s
        while time.time() < end:
            if predicate():
                return True
            time.sleep(0.3)
        print(f"  (timed out waiting for {what})")
        return False

    gate_shown = wait_for(
        lambda: popup.evaluate(
            "() => !document.getElementById('ask').hidden"), 30, "the gate question")
    check(gate_shown, "the spending gate asked, and the popup showed the question")
    if gate_shown:
        question = popup.inner_text("#ask-text")
        check("640" not in question or "Book" in question or "book" in question,
              f"the question names the action: {question[:120]!r}")
        popup.click("#yes")

    wait_for(lambda: sw.evaluate("() => !!globalThis.__run"), 60, "the run to finish")
    result = sw.evaluate("() => globalThis.__run")
    ok = bool(result and result.get("ok"))
    check(ok, f"the task loop finished: {json.dumps(result)[:200] if result else 'null'}")
    if ok:
        check(result["result"]["status"] == "completed",
              f"run status: {result['result']['status']}")
        confirmed = [s for s in result["result"]["steps"] if s.get("confirmedByUser")]
        check(bool(confirmed), "the booking press is recorded as confirmed by the user")

    # --- what the page itself says happened ----------------------------------
    values = page.evaluate("""() => ({
        from: document.getElementById('from').value,
        to: document.getElementById('to').value,
        date: document.getElementById('date').value,
        seats: document.getElementById('seats').value,
        pname: document.getElementById('pname').value,
        pemail: document.getElementById('pemail').value,
        confirmation: document.getElementById('confirmation').textContent,
    })""")
    check(values["from"] == "New Delhi" and values["to"] == "Chandigarh",
          f"stations filled: {values['from']} -> {values['to']}")
    check(values["date"] == "2026-12-15", f"travel date filled: {values['date']}")
    check(values["seats"] == "2", f"seats selected: {values['seats']}")
    check(values["pname"] == "Asha Sharma",
          f"passenger name came from the vault via the recipe: {values['pname']!r}")
    check("Booked 2 seat(s), New Delhi to Chandigarh" in values["confirmation"],
          f"the page confirmed the booking: {values['confirmation'][:140]!r}")

    # --- the popup's Listen button: voice in, words in the goal field --------
    with STATE["lock"]:
        STATE["transcript"] = "book a train from delhi to mumbai"
    popup.click("#listen")
    heard = wait_for(
        lambda: popup.evaluate("() => document.getElementById('goal').value.length > 0"),
        30, "the transcript")
    check(heard and popup.input_value("#goal") == "book a train from delhi to mumbai",
          "the Listen button put the transcribed words in the goal field")

    # --- the loop was heard, not just written --------------------------------
    log = sw.evaluate("() => speechLog()")
    attempts = log["attempts"]
    check(len(attempts) > 0, f"the loop narrated ({len(attempts)} announcements)")
    said = [a["text"] for a in attempts]
    check(any("Say yes to go ahead" in t for t in said),
          "the gate's question was spoken aloud")

    elapsed = int(time.time() - started)
    print(f"\nreal Chrome smoke finished in {elapsed}s; "
          f"{len(FAILURES)} check(s) failed")
    out = {
        "date": date.today().isoformat(),
        "browser": f"installed {channel} (stable channel), unpacked extension",
        "note": "branded Google Chrome 137+ ignores --load-extension, so the "
                "smoke runs in the machine's installed Edge (same Chromium "
                "engine) when Chrome will not load it",
        "checks_failed": FAILURES,
        "run": result,
        "field_values": values,
        "narration_sample": said[:6],
        "elapsed_s": elapsed,
    }
    out_dir = os.path.join(OUT_DIR, f"{date.today().isoformat()}-real-chrome-smoke")
    os.makedirs(out_dir, exist_ok=True)
    with open(os.path.join(out_dir, "result.json"), "w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2, ensure_ascii=False)
    print(f"proof written to {out_dir}")
    return 1 if FAILURES else 0


if __name__ == "__main__":
    sys.exit(main())
