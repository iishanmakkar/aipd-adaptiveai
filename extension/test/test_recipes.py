"""Recipes: site knowledge as data, and what that data is allowed to say.

The rule being tested is the one the design lives by (spec §7): a recipe may name a
role and the words a blind user hears in an accessible name, and may not name a
selector, an XPath, an id or a value. Everything else here is about what happens
when that data meets a real page - two controls matching one word, a control past
the stop line, a name that only matched as a substring.

Run:  python -m pytest extension/test/test_recipes.py -p no:warnings -v
"""
import glob
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
RECIPE_DIR = os.path.join(EXT_DIR, "recipes")

TRAIN_PAGE = b"""<!doctype html><html lang="en"><head><title>Train search</title></head>
<body><main><h1>Find trains</h1>
<label for="from">From</label><input id="from">
<label for="to">To</label><input id="to">
<label for="date">Journey date</label><input id="date">
<label for="cls">Class</label><select id="cls"><option>Sleeper</option><option>AC 3-tier</option></select>
<label for="pax">Passenger name</label><input id="pax">
<button id="trap">Total price \xe2\x82\xb9640</button>
<button id="go" onclick="location.href='/?case=results'">Search trains</button>
</main></body></html>"""

NAMES_PAGE = b"""<!doctype html><html lang="en"><head><title>Two names</title></head>
<body><main><h1>Passengers</h1>
<label for="a">Passenger name</label><input id="a">
<label for="b">Passenger name</label><input id="b">
<button id="book">Book now</button>
</main></body></html>"""

PARTIAL_PAGE = b"""<!doctype html><html lang="en"><head><title>Partial</title></head>
<body><main><h1>Find trains</h1>
<label for="from">From</label><input id="from">
<label for="to">To</label><input id="to">
<label for="date">Journey date</label><input id="date">
<button id="trap">Total price \xe2\x82\xb9640</button>
</main></body></html>"""

STATE = {"step_calls": 0, "replies": [], "bodies": []}


class _Handler(http.server.BaseHTTPRequestHandler):
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
        elif "case=names" in self.path:
            self._send(200, NAMES_PAGE)
        else:
            self._send(200, TRAIN_PAGE)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b"{}"
        if self.path == "/api/extension/step":
            with STATE["lock"]:
                STATE["step_calls"] += 1
                STATE["bodies"].append(raw.decode("utf-8", "replace"))
                reply = STATE["replies"].pop(0) if STATE["replies"] else {
                    "status": "done", "narration": "Nothing left for the model to do."}
            self._send(200, json.dumps(reply).encode(), "application/json")
            return
        self._send(404, b"{}")

    def log_message(self, *args):
        pass


STATE["lock"] = threading.Lock()


@pytest.fixture(scope="module")
def ctx():
    with sync_playwright() as p:
        c = p.chromium.launch_persistent_context(
            "", headless=True, channel="chromium",
            args=[f"--disable-extensions-except={EXT_DIR}", f"--load-extension={EXT_DIR}"])
        yield c
        c.close()


@pytest.fixture(scope="module")
def backend():
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), _Handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()
    httpd.server_close()


def _worker(context, timeout_s=45):
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        for sw in context.service_workers:
            if "chrome-extension://" in sw.url:
                return sw
        time.sleep(0.4)
    return None


@pytest.fixture
def onpage(ctx, backend):
    page = ctx.new_page()
    page.goto(backend + "/", wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=20000)
    sw = _worker(ctx)
    assert sw is not None
    sw.evaluate("""(base) => new Promise(r => chrome.storage.local.set(
        {adaptiveai_backend: base, adaptiveai_traces: {}}, r))""", backend)
    with STATE["lock"]:
        STATE["step_calls"] = 0
        STATE["replies"].clear()
        STATE["bodies"].clear()
    yield {"page": page, "sw": sw, "backend": backend}
    page.close()


def snapshot(sw):
    return sw.evaluate("""() => chrome.tabs.query({active:true,currentWindow:true})
        .then(ts => new Promise(r => chrome.tabs.sendMessage(
            ts[0].id, {type:'adaptiveai:snapshot', force:true},
            s => r(chrome.runtime.lastError ? null : s))))""")


def propose(sw, recipe_id, goal, done=None):
    return sw.evaluate("""async ([recipeId, goal, done]) => {
        const list = await AdaptiveAIRecipes.load();
        const snap = await chrome.tabs.query({active:true,currentWindow:true})
            .then(ts => new Promise(r => chrome.tabs.sendMessage(
                ts[0].id, {type:'adaptiveai:snapshot', force:true},
                s => r(chrome.runtime.lastError ? null : s))));
        const recipe = list.find(x => x.id === recipeId);
        if (!recipe) return { error: 'recipe not loaded: ' + recipeId };
        return AdaptiveAIRecipes.propose(recipe, snap, goal, done || []);
    }""", [recipe_id, goal, done or []])


def test_the_committed_recipes_are_data_and_say_what_was_never_run():
    """Read off disk, not through the extension: the point is what a reviewer
    commits, and a `verifiedOn` field that is missing is a recipe claiming a site
    it has never touched."""
    files = sorted(glob.glob(os.path.join(RECIPE_DIR, "*.json")))
    assert [os.path.basename(f) for f in files if f.endswith("index.json")] == ["index.json"]
    for path in files:
        if path.endswith("index.json"):
            continue
        recipe = json.load(open(path, encoding="utf-8"))
        name = os.path.basename(path)
        assert recipe["id"] and recipe["hosts"], f"{name}: needs id and hosts"
        assert "verifiedOn" in recipe and "notVerifiedOn" in recipe, \
            f"{name}: must state where it has and has not been run"
        assert set(recipe["verifiedOn"]) | set(recipe["notVerifiedOn"]), f"{name}: empty claims"
        blob = json.dumps(recipe)
        for pattern, why in ((r"querySelector", "DOM query"), (r"//\*", "xpath"),
                             (r"#\w+\",", "css id"), (r"\[id=", "attribute selector"),
                             (r"\.class", "css class")):
            assert not re.search(pattern, blob), f"{name} contains a {why}"
        for step in recipe["steps"]:
            assert step.get("intent") and step.get("names"), f"{name}: {step}"
            assert not re.match(r"^[.#\[]", str(step.get("names", [""])[0])), \
                f"{name}: a name word that looks like a selector"
            if step.get("value"):
                assert step["value"].startswith("profile:"), \
                    f"{name}: {step['intent']} carries a literal value"


def test_the_worker_loaded_every_recipe_the_index_advertises(ctx):
    sw = _worker(ctx)
    index = json.load(open(os.path.join(RECIPE_DIR, "index.json"), encoding="utf-8"))
    loaded = sw.evaluate("""(names) => AdaptiveAIRecipes.load().then(list => ({
        ids: list.map(r => r.id), missing: names.filter(n => !n.includes('.json') ? false : true),
        problems: AdaptiveAIRecipes.problems()}))""", index["recipes"])
    assert loaded["problems"] == [], loaded["problems"]
    assert len(loaded["ids"]) == len(index["recipes"]), loaded


def test_a_selector_in_a_recipe_is_refused_not_fetched_anyway(onpage):
    verdict = onpage["sw"].evaluate("""() => AdaptiveAIRecipes.validate({
        id: 'x', hosts: ['a.com'],
        steps: [{intent: 'origin', role: 'textbox', names: ['#from-input']}]})""")
    assert verdict and "selector" in verdict.lower(), verdict
    literal = onpage["sw"].evaluate("""() => AdaptiveAIRecipes.validate({
        id: 'x', hosts: ['a.com'],
        steps: [{intent: 'origin', role: 'textbox', names: ['from'], value: 'New Delhi'}]})""")
    assert literal and "value" in literal.lower(), literal


def test_the_recipe_proposes_the_first_thing_a_train_form_needs(onpage):
    got = propose(onpage["sw"], "train-booking", "book a train from delhi to mumbai")
    assert got["kind"] == "step", got
    assert got["intent"] == "origin", got
    assert got["action"] == "fill", got
    snap = snapshot(onpage["sw"])
    node = [n for n in snap["nodes"] if n["ref"] == got["ref"]][0]
    assert node["name"] == "From", node


def test_a_word_that_matches_two_controls_asks_instead_of_choosing(onpage):
    page = onpage["page"].context.new_page()
    page.goto(onpage["backend"] + "/?case=names", wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=20000)
    got = onpage["sw"].evaluate("""async () => {
        const list = await AdaptiveAIRecipes.load();
        const snap = await chrome.tabs.query({currentWindow:true})
            .then(ts => new Promise(r => chrome.tabs.sendMessage(
                ts[ts.length-1].id, {type:'adaptiveai:snapshot', force:true},
                s => r(chrome.runtime.lastError ? null : s))));
        const step = list.find(x => x.id === 'train-booking').steps
            .find(s => s.intent === 'passengers');
        return AdaptiveAIRecipes.propose(
            list.find(x => x.id === 'train-booking'), snap, 'book a train ticket',
            ['origin','destination','journey date','class','search']);
    }""")
    page.close()
    assert got["kind"] == "ask", got
    assert len(got["candidates"]) >= 2, got


def test_a_substring_only_match_is_not_enough_to_press_something(onpage):
    """"To" is a step word in the train recipe and the page has a paragraph saying
    "Total price ₹640". A substring matcher would fill the total."""
    snap = snapshot(onpage["sw"])
    assert any("Total price" in (n.get("name") or "") for n in snap["nodes"]), \
        "the page must still contain the trap"
    got = propose(onpage["sw"], "train-booking", "book a train from delhi to mumbai",
                  done=["origin"])
    assert got["kind"] == "step" and got["intent"] == "destination", got
    node = [n for n in snap["nodes"] if n["ref"] == got["ref"]][0]
    assert node["name"] == "To", node


def test_a_recipe_never_walks_past_its_own_stop_line(onpage):
    page = onpage["page"].context.new_page()
    page.goto(onpage["backend"] + "/?case=names", wait_until="load")
    page.wait_for_function(
        "() => document.documentElement.hasAttribute('data-adaptiveai-nodes')",
        timeout=20000)
    got = onpage["sw"].evaluate("""async () => {
        const list = await AdaptiveAIRecipes.load();
        const recipe = list.find(x => x.id === 'train-booking');
        const snap = await chrome.tabs.query({currentWindow:true})
            .then(ts => new Promise(r => chrome.tabs.sendMessage(
                ts[ts.length-1].id, {type:'adaptiveai:snapshot', force:true},
                s => r(chrome.runtime.lastError ? null : s))));
        // A step whose matched control carries a stop word is where the recipe
        // ends, even though the step itself matched.
        const stopper = { id: 'stopper', hosts: ['*'], matchGoal: [],
                          stopAt: ['book'],
                          steps: [{ intent: 'pay', role: 'button', names: ['book'] }] };
        return { stop: recipe.stopAt,
                 stopper: await AdaptiveAIRecipes.propose(stopper, snap, 'book a train', []),
                 complete: await AdaptiveAIRecipes.propose(recipe, snap,
                     'book a train ticket',
                     ['origin','destination','journey date','class','passengers','search']) };
    }""")
    page.close()
    assert got["stop"], got
    assert got["stopper"]["kind"] == "stop", got["stopper"]
    assert got["stopper"]["name"].lower().startswith("book"), got["stopper"]
    # With every intent already verified, the recipe has nothing left to offer
    # and says so, rather than walking into "Book now" on its own initiative.
    assert got["complete"]["kind"] == "complete", got["complete"]


def test_traces_are_written_only_for_a_step_the_page_confirmed(onpage):
    sw = onpage["sw"]
    snap = snapshot(sw)
    origin = [n for n in snap["nodes"] if n["name"] == "From"][0]
    wrote = sw.evaluate("""([node]) => AdaptiveAIRecipes.record(
        {url: node.url}, 'train-booking', 'origin',
        {role: 'textbox', name: 'From'}, 'verified')""",
        [{"url": onpage["page"].url}])
    assert wrote is True
    traces = sw.evaluate("() => new Promise(r => chrome.storage.local.get(['adaptiveai_traces'], r))")
    stored = json.dumps(traces["adaptiveai_traces"])
    assert "origin" in stored and "From" in stored, stored
    assert origin["ref"] not in stored, "a ref must never become memory"

    sw.evaluate("""() => new Promise(r => chrome.storage.local.set({adaptiveai_traces: {}}, r))""")
    sw.evaluate("""() => AdaptiveAIRecipes.record({url: 'http://127.0.0.1/x'}, 'train-booking',
        'origin', {role:'textbox', name:'From'}, 'failed')""")
    after = sw.evaluate("() => new Promise(r => chrome.storage.local.get(['adaptiveai_traces'], r))")
    assert not after["adaptiveai_traces"], \
        "a step the page refused must not be remembered as a route that works"


def test_a_recipe_step_skips_the_model_and_says_so_in_the_history(onpage):
    """Provenance, measured on the wire.

    The model covers origin, destination, date and class - values from the
    goal's own words. The recipe covers the passenger name, because that is
    profile data the device already holds, and the Search press. A recipe step
    that needs a value it cannot resolve is handed to the model instead, so a
    data file can never type `undefined` into a field and read it back as
    proof. The last model call must carry history labelled both ways, and
    never the recipe's internal node or intent.
    """
    sw = onpage["sw"]
    snap = snapshot(sw)
    refs = {n["name"]: n["ref"] for n in snap["nodes"]}
    sw.evaluate("""(profile) => new Promise(r =>
        chrome.storage.local.set({adaptiveai_profile: profile}, r))""",
        {"full name": "Asha Sharma"})
    with STATE["lock"]:
        STATE["replies"].extend([
            {"status": "act", "action": "fill", "ref": refs["From"],
             "value_from": "literal", "value_literal": "Delhi",
             "narration": "From Delhi."},
            {"status": "act", "action": "fill", "ref": refs["To"],
             "value_from": "literal", "value_literal": "Mumbai",
             "narration": "To Mumbai."},
            {"status": "act", "action": "fill", "ref": refs["Journey date"],
             "value_from": "literal", "value_literal": "15/12/2026",
             "narration": "Date set."},
            {"status": "act", "action": "select", "ref": refs["Class"],
             "value_from": "literal", "value_literal": "AC 3-tier",
             "narration": "AC 3-tier."},
            {"status": "done", "narration": "Trains listed."}])
    reply = sw.evaluate("(g) => runTask(g)",
                        "book a train from delhi to mumbai on 15/12/2026")
    assert reply["ok"] is True, reply
    assert reply["result"]["status"] == "completed", reply["result"]
    # The Search press navigated the page away, so the field itself is gone;
    # the actor's readback of the recipe fill is the evidence it was entered.
    passenger = [s for s in reply["result"]["steps"]
                 if s["description"] == "passengers (Passenger name)"]
    assert passenger and passenger[0]["status"] == "verified" and \
        passenger[0]["readback"] == "Asha Sharma", reply["result"]["steps"]
    bodies = [json.loads(b) for b in STATE["bodies"]]
    step_bodies = [b for b in bodies if "nodes" in b]
    assert step_bodies, bodies
    history = step_bodies[-1]["history"]
    assert len(history) == 6, history
    sources = {h.get("source") for h in history}
    assert "recipe" in sources and "model" in sources, sources
    for h in history:
        assert "node" not in h and "intent" not in h, \
            "internal fields must not be posted: %s" % list(h)
    recipe_steps = [h for h in history if h.get("source") == "recipe"]
    by_intent = {h["description"].split(" (")[0]: h["status"] for h in recipe_steps}
    # The fill the page confirmed is 'verified'; the Search press is honestly
    # 'pressed' - its readback was lost to the very navigation it caused.
    assert by_intent.get("passengers") == "verified", by_intent
    assert by_intent.get("search") in ("pressed", "verified"), by_intent
