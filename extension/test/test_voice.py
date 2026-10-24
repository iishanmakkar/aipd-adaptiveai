"""Voice in: the microphone in the offscreen document, the bytes on the wire.

Chromium is launched with a fake audio device and auto-granted permission, so
`getUserMedia` and `MediaRecorder` run for real and produce real encoded audio -
this is not a stubbed capture. What the test then checks is the shape of what
leaves the extension and what comes back: a multipart upload with an actual audio
part, the transcript from the route (whose field is `transcript`, and a client
reading `text` reports silence on a successful call), and the reason when the
transcriber refuses.

The transcription model itself is proved by `scripts/stt_local_proof.py`, which
speaks a sentence through the operating system's own voice and reads it back
through the real /api/transcribe route.

Run:  python -m pytest extension/test/test_voice.py -p no:warnings -v
"""
import http.server
import json
import os
import socketserver
import threading
import time

import pytest
from playwright.sync_api import sync_playwright

EXT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PAGE = b"""<!doctype html><html lang="en"><head><title>Voice target</title></head>
<body><main><h1>Book tickets</h1>
<label for="q">From</label><input id="q" name="q">
<button id="go">Search</button>
<button id="pay">Pay \xe2\x82\xb9640</button>
<div id="slot"></div>
<script>
  window.__paid = 0;
  document.getElementById('pay').addEventListener('click', function () {
    window.__paid++;
    var d = document.createElement('div');
    d.setAttribute('role', 'alert');
    d.textContent = 'Payment accepted';
    document.getElementById('slot').appendChild(d);
  });
</script>
</main></body></html>"""

STATE = {"uploads": [], "reply": {"transcript": "book two tickets", "language": "en",
                                  "duration": 1.4}, "status": 200,
         "step_replies": []}
LOCK = threading.Lock()


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
        if self.path == "/api/transcribe":
            with LOCK:
                STATE["uploads"].append({
                    "body": raw,
                    "content_type": self.headers.get("Content-Type", ""),
                })
            self._send(STATE["status"],
                       json.dumps(STATE["reply"]).encode("utf-8"),
                       "application/json")
            return
        if self.path == "/api/extension/step":
            with LOCK:
                reply = STATE["step_replies"].pop(0) if STATE["step_replies"] else {
                    "status": "done", "narration": "Nothing more to do."}
            self._send(200, json.dumps(reply).encode("utf-8"), "application/json")
            return
        self._send(200, b'{"status":"done","narration":"Nothing more to do."}',
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
            args=[
                f"--disable-extensions-except={EXT_DIR}",
                f"--load-extension={EXT_DIR}",
                # A real (synthetic) capture device and no permission dialog: the
                # microphone path runs end to end rather than being simulated.
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
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


def _worker(ctx, timeout_s=45):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sw in ctx.service_workers:
            if "chrome-extension://" in sw.url:
                return sw
        time.sleep(0.4)
    return None


@pytest.fixture
def voice(ctx, backend):
    page = ctx.new_page()
    page.goto(backend + "/", wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=20000)
    sw = _worker(ctx)
    assert sw is not None, "the worker never registered"
    sw.evaluate("""(base) => new Promise(resolve =>
        chrome.storage.local.set({adaptiveai_backend: base}, resolve))""", backend)
    with LOCK:
        STATE["uploads"].clear()
        STATE["status"] = 200
        STATE["reply"] = {"transcript": "book two tickets", "language": "en",
                          "duration": 1.4}
    yield {"sw": sw, "page": page, "backend": backend}
    page.close()


def test_the_microphone_captures_real_audio_and_uploads_it(voice):
    reply = voice["sw"].evaluate("() => transcribe(2500)")
    assert reply["ok"] is True, reply
    assert reply["text"] == "book two tickets", reply
    assert len(STATE["uploads"]) == 1, STATE["uploads"]
    upload = STATE["uploads"][0]
    assert upload["content_type"].startswith("multipart/form-data"), upload["content_type"]
    assert "boundary=" in upload["content_type"]
    body = upload["body"]
    assert b'name="audio"' in body, "the route's field is called audio"
    assert b"utterance.webm" in body
    # Bytes of encoded audio, not a placeholder: a MediaRecorder that produced
    # nothing would still post a valid multipart envelope.
    assert len(body) > 2000, f"only {len(body)} bytes of upload"


def test_the_transcript_reaches_the_goal_field(voice):
    popup = voice["page"].context.new_page()
    ext_id = voice["sw"].url.split("/")[2]
    popup.goto(f"chrome-extension://{ext_id}/popup.html", wait_until="load")
    popup.wait_for_selector("#listen")
    popup.click("#listen")
    popup.wait_for_function(
        "() => document.getElementById('goal').value.length > 0", timeout=20000)
    assert popup.input_value("#goal") == "book two tickets"
    assert "book two tickets" in popup.inner_text("#status")
    popup.close()


def test_a_refusal_from_the_transcriber_is_passed_through_not_hidden(voice):
    STATE["status"] = 422
    STATE["reply"] = {"detail": "No speech detected in audio"}
    reply = voice["sw"].evaluate("() => transcribe(1500)")
    assert reply["ok"] is False, reply
    assert "422" in reply["reason"], reply
    assert "no speech" in reply["reason"].lower(), reply


def test_a_transcriptless_success_is_not_treated_as_words(voice):
    STATE["reply"] = {"transcript": "   ", "language": "en"}
    reply = voice["sw"].evaluate("() => transcribe(1500)")
    assert reply["ok"] is False, reply
    assert "no words" in reply["reason"].lower(), reply


def test_the_audio_never_touches_storage(voice):
    voice["sw"].evaluate("() => transcribe(1500)")
    stored = voice["sw"].evaluate(
        "() => new Promise(r => chrome.storage.local.get(null, r))")
    keys = " ".join(sorted(stored.keys())).lower()
    assert "audio" not in keys and "blob" not in keys and "record" not in keys, keys
    values = json.dumps(list(stored.values()))[:4000]
    for key, upload in enumerate(STATE["uploads"]):
        sample = upload["body"][200:260]
        assert sample.hex() not in values, f"upload {key} bytes appear in storage"


def test_a_key_command_hears_a_goal_speaks_it_back_and_runs_it(voice):
    """The whole hands-free loop, driven the way a keyboard shortcut drives it."""
    reply = voice["sw"].evaluate("() => handleCommand('listen')")
    assert reply["ok"] is True, reply
    assert reply["text"] == "book two tickets", reply
    assert reply["result"]["status"] == "completed", reply["result"]
    log = voice["sw"].evaluate("() => speechLog()")
    said = [a["text"] for a in log["attempts"]]
    assert any(t.startswith("You said: book two tickets") for t in said), said


def test_stop_talking_is_a_command_not_a_mystery(voice):
    reply = voice["sw"].evaluate("() => handleCommand('stop-talking')")
    assert reply["ok"] is True, reply


def test_an_unknown_command_is_refused(voice):
    reply = voice["sw"].evaluate("() => handleCommand('self-destruct')")
    assert reply["ok"] is False and "unknown" in reply["reason"], reply


def test_the_manifest_and_the_worker_agree_on_command_names():
    """A command the worker does not handle is a key that does nothing, and a name
    in only one of the two files is invisible to every test that drives the other."""
    manifest = json.load(open(os.path.join(EXT_DIR, "manifest.json"), encoding="utf-8"))
    source = open(os.path.join(EXT_DIR, "src", "background.js"), encoding="utf-8").read()
    declared = sorted(manifest["commands"].keys())
    assert declared == sorted(["listen", "stop-talking"]), declared
    for name in declared:
        assert "'%s'" % name in source, "manifest declares %r, worker never handles it" % name
    # No default shortcut: Chrome refuses to install the extension when a
    # Ctrl+Alt+* default is claimed (measured - see README).
    for name, spec in manifest["commands"].items():
        assert "suggested_key" not in spec, "%s would block installation" % name


def test_the_worker_never_logs_the_transcript_of_a_privacy_field(voice):
    """The transcript becomes the *goal*, which is then sent to the planner as
    `goal`. That is by design - the user asked for it - but the transcript of
    something said near a password box must not end up in a log line either."""
    source = open(os.path.join(EXT_DIR, "src", "background.js"), encoding="utf-8").read()
    transcribe_block = source[source.index("async function transcribe"):
                              source.index("chrome.runtime.onMessage.addListener",
                                           source.index("async function transcribe"))]
    assert "logger" not in transcribe_block and "console" not in transcribe_block, \
        "the transcribe path must not log what it heard"


# ---- the spoken answer at the spending gate --------------------------------
#
# The gate's narration says "Say yes to go ahead, or no to stop". These tests
# drive that sentence with the same fixture the microphone tests use - a real
# (synthetic) capture device, real MediaRecorder bytes, a real multipart upload
# - while a task loop is genuinely waiting on ANSWER.

def _pay_ref(sw):
    return sw.evaluate("""async () => {
        const ts = await chrome.tabs.query({active: true, currentWindow: true});
        const r = await snapshotOf(ts[0].id);
        const node = r.snapshot.nodes.find(n => n.name && n.name.startsWith('Pay'));
        if (!node) throw new Error('fixture page has no Pay control');
        return node.ref;
    }""")


def _gate_fixture(voice, transcript, replies):
    sw = voice["sw"]
    with LOCK:
        STATE["uploads"].clear()
        STATE["reply"] = {"transcript": transcript, "language": "en"}
        STATE["step_replies"] = replies
    return sw


def _start_run(sw, goal):
    sw.evaluate("""(g) => {
        globalThis.__run = null;
        runTask(g).then(r => { globalThis.__run = r; });
        return true;
    }""", goal)


def _wait_for(predicate_sw, expression, timeout_s=40):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if predicate_sw.evaluate(expression):
            return True
        time.sleep(0.3)
    return False


def test_a_spoken_yes_releases_the_gate(voice):
    """The full hands-free booking moment: the loop asks about money, the user
    SAYS yes into the microphone, real audio is captured and transcribed, and
    only then is the click dispatched - verified by the page's own alert."""
    sw = _gate_fixture(voice, "yes", [
        {"status": "act", "action": "click", "ref": _pay_ref(voice["sw"]),
         "expect": "node_appears", "narration": "Paying 640 rupees now."}])
    _start_run(sw, "pay for my ticket")
    assert _wait_for(sw, "() => !!ANSWER"), "the gate never asked"
    heard = sw.evaluate("() => handleCommand('listen')")
    assert heard["ok"] is True and heard["answer"] == "yes", heard
    assert _wait_for(sw, "() => !!globalThis.__run"), "the run never finished"
    result = sw.evaluate("() => globalThis.__run")
    assert result["ok"] is True and result["result"]["status"] == "completed", result
    assert voice["page"].evaluate("() => window.__paid") == 1, result
    said = [a["text"] for a in sw.evaluate("() => speechLog()")["attempts"]]
    assert any("Going ahead" in t for t in said), said


def test_a_spoken_no_cancels_and_nothing_is_pressed(voice):
    sw = _gate_fixture(voice, "no thanks, stop", [
        {"status": "act", "action": "click", "ref": _pay_ref(voice["sw"]),
         "expect": "node_appears", "narration": "Paying 640 rupees now."}])
    _start_run(sw, "pay for my ticket")
    assert _wait_for(sw, "() => !!ANSWER"), "the gate never asked"
    heard = sw.evaluate("() => handleCommand('listen')")
    assert heard["ok"] is True and heard["answer"] == "no", heard
    assert _wait_for(sw, "() => !!globalThis.__run"), "the run never finished"
    result = sw.evaluate("() => globalThis.__run")
    assert result["result"]["status"] == "cancelled", result
    assert voice["page"].evaluate("() => window.__paid") == 0, \
        "a spoken no still spent money"


def test_a_misheard_answer_is_asked_again_not_guessed(voice):
    """"Maybe later" is neither yes nor no. The failure direction matters: the
    answer must fall toward ask-again, never toward spending."""
    sw = _gate_fixture(voice, "maybe later", [
        {"status": "act", "action": "click", "ref": _pay_ref(voice["sw"]),
         "expect": "node_appears", "narration": "Paying 640 rupees now."}])
    _start_run(sw, "pay for my ticket")
    assert _wait_for(sw, "() => !!ANSWER"), "the gate never asked"
    first = sw.evaluate("() => handleCommand('listen')")
    assert first["ok"] is False and "yes or no" in first["reason"], first
    # The question is still pending - the loop did not guess - so a clear
    # answer on the second take is still heard.
    with LOCK:
        STATE["reply"] = {"transcript": "yes", "language": "en"}
    second = sw.evaluate("() => handleCommand('listen')")
    assert second["ok"] is True and second["answer"] == "yes", second
    assert _wait_for(sw, "() => !!globalThis.__run"), "the run never finished"
    result = sw.evaluate("() => globalThis.__run")
    assert result["result"]["status"] == "completed", result
    assert voice["page"].evaluate("() => window.__paid") == 1, result
    said = [a["text"] for a in sw.evaluate("() => speechLog()")["attempts"]]
    assert any("I need yes or no" in t for t in said), said
