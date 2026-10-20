# Truth Pass (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove every path in AdaptiveAI that reports success without having caused it, and make the project's verification claims reproducible by a stranger.

**Architecture:** Five FastAPI services plus a React frontend, all containerized. This plan touches existing code only — no new subsystem. Each fix replaces a fabricated outcome with either a real verified outcome or an honest failure, and every one is locked by a test that fails if the fabrication is reintroduced.

**Tech Stack:** Python 3.11 (in containers), FastAPI, Playwright/Chromium, SQLAlchemy async, pytest 8.4.2 + pytest-asyncio 0.26.0, React 18 + TypeScript strict + Vite.

**Spec:** `docs/superpowers/specs/2026-10-21-adaptiveai-real-user-extension-design.md` — this plan implements §8 items 1–4 and 6–14, and Phase 0 is already complete (10 preservation commits, `a21f8aa..acef636`).

---

## Global Constraints

- **No mocks in the product path.** A missing capability returns 502/503/422 or an honest spoken failure. Never invented data. (Spec §3.)
- **No `success`/`completed` status may be returned without a readback fact attached to it.** This is the definition of the whole plan. (Spec §5.2.)
- **Test commands run in containers, never on the Windows host.** Verified 2026-10-21: host `python -m pytest` collects **zero** tests for `backend`, `agents` and `intent-engine`, because host deps are absent (`jose`) and `import app` resolves to `D:\geospatial\geomeasure\app`, an unrelated project on this machine's `sys.path`. `browser-agent` (44 passed) and `npm run build` are the only host-runnable checks.
- **No new dependencies.** The only exception permitted is `playwright` inside the `browser-agent` image, which already installs Chromium.
- **No OS-level input automation** — Playwright/CDP/page objects only. (`AUTOMATION_SAFETY.md:12-21`, spec §3.)
- **Commit after every task**, message prefixed with the service scope, matching repo style (`fix(backend): ...`, `test(browser-agent): ...`).
- **Do not push.** Local commits only; pushing is the owner's decision.
- **Never assert on model prose.** NIM output is non-deterministic; assert on counters, statuses, roles and names.

## Reproducible Commands (use these throughout)

```bash
# bring the stack up (daemon must be running: Docker Desktop on this host)
docker compose up -d --build

# one service's offline suite
docker compose exec -T backend       python -m pytest -q
docker compose exec -T agents        python -m pytest -q
docker compose exec -T intent-engine python -m pytest -q
docker compose exec -T browser-agent python -m pytest -q -m "not live"

# frontend type-check + build (host is fine for this one)
cd frontend && npm run build
```

## What is deferred to Plan B, and why

- Spec §8 **item 5** (`ui_adjuster_agent` applying real page changes) needs the extension's `actor` to exist. Its sibling half — `profile_updater` writing preferences, `scheduler` demotion — is **Task 11** here, because it needs no extension.
- Spec §8 item 12 (README rewrite) is **Task 12**, held to last so it can state final measured numbers rather than intermediate ones.

---

### Task 1: Reproducible verification and a truthful baseline

The plan cannot proceed on TDD until a test command actually runs tests. Today it does not.

**Files:**
- Create: `scripts/verify.sh`
- Create: `docs/verification-baseline.md`
- Modify: `README.md:306-320` (§5 Testing — replace host instructions with container commands, keep the host note as a warning)

**Interfaces:**
- Consumes: nothing.
- Produces: `scripts/verify.sh` — exits non-zero if any suite fails to collect or any test fails. Every later task's "run the tests" step is `bash scripts/verify.sh <service>`.

- [ ] **Step 1: Confirm the daemon is up and the stack builds**

Run: `docker info --format '{{.ServerVersion}}'`
Expected: a version string. If it errors with `failed to connect to the docker API`, start Docker Desktop and wait — do not proceed, every later step needs it.

Run: `docker compose up -d --build`
Expected: 7 containers, `docker compose ps` shows all `healthy` (first build is 2–5 minutes).

- [ ] **Step 2: Write the runner**

Create `scripts/verify.sh`:

```bash
#!/usr/bin/env bash
# Runs each service's offline suite INSIDE its container. The Windows host
# cannot run these: deps are uninstalled and `import app` resolves to an
# unrelated project on sys.path (see docs/verification-baseline.md).
set -uo pipefail

declare -A CMD=(
  [backend]="python -m pytest -q"
  [agents]="python -m pytest -q"
  [intent-engine]="python -m pytest -q"
  [browser-agent]="python -m pytest -q -m \"not live\""
)

services=("${@:-backend agents intent-engine browser-agent}")
[[ $# -gt 0 ]] && services=("$@")

rc=0
for svc in "${services[@]}"; do
  printf '\n=== %s: %s\n' "$svc" "${CMD[$svc]}"
  # -T so it runs non-interactively; capture output to detect the collect-only
  # failure mode where pytest exits 4 and "0 passed" looks like a quiet pass.
  out=$(docker compose exec -T "$svc" bash -lc "${CMD[$svc]}" 2>&1) || rc=1
  echo "$out" | tail -n 15
  if echo "$out" | grep -qE "no tests ran|Interrupted: [0-9]+ error|errors during collection"; then
    echo "!! $svc collected ZERO tests - suite is not running, not passing"
    rc=1
  fi
done

printf '\n=== verify.sh exit %s\n' "$rc"
exit "$rc"
```

- [ ] **Step 3: Run it and record the honest baseline**

Run: `docker compose cp scripts/verify.sh backend:/tmp/` — not needed; run from host:
Run: `bash scripts/verify.sh`
Expected on first run: numbers for all four suites. **Record the exact totals**, including any collection errors. Do not round, do not reuse the README's 454 figure.

- [ ] **Step 4: Write the baseline document**

Create `docs/verification-baseline.md` with the measured date, the command, per-service pass/fail/skip counts, and this explicit statement where the counts sit:

```markdown
Measured 2026-10-21 with `bash scripts/verify.sh` against
`docker compose up -d --build` at commit <hash>.

Host execution is unsupported for backend/agents/intent-engine: `python -m pytest`
on this machine fails at collection (`ModuleNotFoundError: No module named 'jose'`,
and `import app` resolves to `D:\geospatial\geomeasure\app`, an unrelated project
placed on sys.path by a site-packages entry). Reading a host failure as a pass is
how the previous baseline went stale.
```

- [ ] **Step 5: Fix any collection error the container reveals**

If a suite fails to collect inside the container, that is a real defect, not an environment one. Reproduce with `docker compose exec -T backend python -m pytest tests/<file>.py`, fix the import or the test, and re-run Step 3.

- [ ] **Step 6: Commit**

```bash
git add scripts/verify.sh docs/verification-baseline.md README.md
git commit -m "test: containerized verification runner and honest baseline"
```

---

### Task 2: Delete the pattern cache that replays stale results as completed

`BrowserAgent.execute_task` short-circuits a repeated `(session, tool, action)` and returns the **previous** result flagged `cached`, so a second click reports `completed` having touched nothing. `steps_completed` then counts it. `BrowserAgent` has exactly one entry point, `POST /agent/browse` (`browser-agent/app/main.py:270-275`), and **no test imports it at all**.

**Files:**
- Create: `browser-agent/tests/test_browser_agent.py`
- Modify: `browser-agent/app/services/browser_agent.py:24-27,48-63,80-85,115-136`

**Interfaces:**
- Consumes: `tool.execute(action, **args) -> dict` with `status` in `completed|error` (`app/tools/base.py`).
- Produces: `BrowserAgent.execute_task()` returning `steps_completed` counting **executed-and-verified** steps only; no `cached` key anywhere in a result; `episodic_memory` retained as planning data.

- [ ] **Step 1: Write the failing tests**

Create `browser-agent/tests/test_browser_agent.py`:

```python
"""The pattern cache used to return a previous result for a repeated tool+action
and count it in steps_completed. Nothing may report a step it never executed."""
import pytest
from app.services.browser_agent import BrowserAgent


class CountingTool:
    def __init__(self, status="completed"):
        self.calls = 0
        self.status = status

    async def execute(self, action, **args):
        self.calls += 1
        return {"status": self.status, "action": action, "ran": self.calls}


class FakeDriver:
    def __init__(self): self.started = self.stopped = False
    async def start(self): self.started = True
    async def stop(self): self.stopped = True


def agent_with(tool):
    a = BrowserAgent(session_id="s1", driver=FakeDriver())
    a.tools = {"browser": tool}
    a._plan_task = lambda intent, ctx: [
        {"tool": "browser", "action": "click", "args": {}},
        {"tool": "browser", "action": "click", "args": {}},
    ]
    return a


@pytest.mark.asyncio
async def test_repeated_step_executes_twice_not_replayed():
    tool = CountingTool()
    out = await agent_with(tool).execute_task("snapshot", {})
    assert tool.calls == 2, "second identical step was replayed from cache"
    assert out["steps_completed"] == 2


@pytest.mark.asyncio
async def test_no_cached_flag_can_appear():
    out = await agent_with(CountingTool()).execute_task("snapshot", {})
    assert not any("cached" in r for r in out["results"])


@pytest.mark.asyncio
async def test_error_steps_are_not_counted_completed():
    out = await agent_with(CountingTool(status="error")).execute_task("snapshot", {})
    assert out["steps_completed"] == 0
    assert out["steps_failed"] == 2
```

- [ ] **Step 2: Run them to verify they fail**

Run: `docker compose exec -T browser-agent python -m pytest tests/test_browser_agent.py -q`
Expected: `test_repeated_step_executes_twice_not_replayed` FAILS with `assert 1 == 2` (second step replayed), `test_no_cached_flag_can_appear` FAILS. If they pass, the cache is already gone — stop and re-check the file.

- [ ] **Step 3: Delete the cache path**

In `browser_agent.py`, remove `self.pattern_cache` (line 27) and its `__init__` comment, delete the `# Check pattern cache first` block (lines 48-54), and drop `result["cached"] = False` (line 59) so no result ever carries that key. In `_store_episode`, delete the trailing cache write (lines 130-136) and keep only the `episodic_memory.append` — episodes remain as *planning data*, never as an execution substitute. Add one line above `episodic_memory` so the intent survives the deletion:

```python
        # Planning data only. A stored episode NEVER short-circuits execution:
        # replay must not report a step it did not run (see execute_task).
        self.episodic_memory: List[Dict[str, Any]] = []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec -T browser-agent python -m pytest tests/test_browser_agent.py -q`
Expected: 3 passed.

- [ ] **Step 5: Confirm nothing else referenced the cache**

Run: `grep -rn "pattern_cache" browser-agent/` (host grep is safe here)
Expected: no matches.

- [ ] **Step 6: Full service suite and commit**

Run: `bash scripts/verify.sh browser-agent`
Expected: 44 prior + 3 new pass.

```bash
git add browser-agent/app/services/browser_agent.py browser-agent/tests/test_browser_agent.py
git commit -m "fix(browser-agent): stop replaying cached results as completed steps"
```

---

### Task 3: Make an unverified checkbox/radio click report failure

`replay_agent.py:318-326` reads `is_checked()`, and when the element is *not* checked executes `pass  # report success w/ state` and returns `status: "success"`. A blind user cannot look at the screen to catch this.

**Files:**
- Create: `backend/tests/test_replay_verification.py`
- Modify: `backend/app/agents/form/replay_agent.py:310-326`

**Interfaces:**
- Consumes: `action` dict with `field_id`, `label`, `is_action_button`; Playwright `ElementHandle.click()`, `.is_checked()`.
- Produces: `execute_action()` returning `status` in `success|failed|no_value|not_selected|skipped` where `success` for a choice click is emitted **only** after `is_checked()` returns `True`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_replay_verification.py`:

```python
"""A choice click that leaves the box unchecked must not report success.
Reproduces the `pass  # report success w/ state` path at replay_agent.py:322."""
import pytest
from app.agents.form.replay_agent import ReplayAgent


class NeverCheckedField:
    def __init__(self): self.clicks = 0
    async def click(self, timeout=None): self.clicks += 1
    async def is_checked(self): return False


class CheckedOnSecondTry(NeverCheckedField):
    async def is_checked(self): return self.clicks >= 2


class Page:
    def __init__(self, field): self._field = field
    async def wait_for_load_state(self, state, timeout=None): return None
    async def query_selector(self, sel): return self._field
    async def query_selector_all(self, sel): return []


def agent(field):
    a = ReplayAgent.__new__(ReplayAgent)
    a.page = Page(field)
    return a


ACTION = {"field_id": "f1", "label": "I agree", "action": "click",
          "is_action_button": False, "selector": "#f1"}


@pytest.mark.asyncio
async def test_click_that_leaves_box_unchecked_is_not_success():
    out = await agent(NeverCheckedField()).execute_action(ACTION, {"I agree": "yes"})
    assert out["status"] != "success"
    assert out["status"] == "failed"
    assert "not checked" in out["reason"]


@pytest.mark.asyncio
async def test_second_pass_is_acked_when_it_lands():
    field = CheckedOnSecondTry()
    out = await agent(field).execute_action(ACTION, {"I agree": "yes"})
    assert out["status"] == "success"
    assert field.clicks == 2, "retry pass did not run"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_replay_verification.py -q`
Expected: first test FAILS asserting `'success' == 'failed'` — proving the fabrication.

- [ ] **Step 3: Replace the `pass` with a retry and an honest failure**

In `replay_agent.py`, replace the `else` branch of the `click` case (lines 317-326) with:

```python
                else:
                    # Choice click. Nobody is looking at the screen, so the
                    # checked state IS the success signal - a click that leaves
                    # the box unchecked must never be reported as done.
                    checked = False
                    for attempt in (1, 2):
                        try:
                            checked = await field.is_checked()
                        except Exception:
                            checked = False
                        if checked:
                            break
                        if attempt == 1:
                            try:
                                await field.click(timeout=5000)
                            except Exception:
                                break
                    if not checked:
                        return {"status": "failed", "action": action_type,
                                "field_id": field_id, "label": label,
                                "reason": "still not checked after two click passes"}
                return {"status": "success", "action": action_type,
                        "field_id": field_id, "label": label}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `docker compose exec -T backend python -m pytest tests/test_replay_verification.py -q`
Expected: 2 passed.

- [ ] **Step 5: Confirm no caller depended on the old over-reporting**

Run: `grep -rn '"status": "success"' backend/app/agents/form/` and read each site: every `success` must now be tied to a readback (`fill` compares `input_value()`, `select` checks `select_option` returned, `click` checks `is_checked`). If a site lacks one, that is a further task, not a fix to skip.

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/form/replay_agent.py backend/tests/test_replay_verification.py
git commit -m "fix(backend): report unverified checkbox clicks as failures"
```

---

### Task 4: Say out loud when a browser request cannot be carried out

`_demote_browser_intent` (`routes_query.py:1028-1045`) silently reroutes `browser_act`/`browser_inspect` to `form_agent`/`web_agent` when no page is open. The user asks "click the book button", and a chat agent answers *about* buttons while the user believes an action was attempted. It is called from two sites, `routes_query.py:1211` and `:1338`.

**Files:**
- Modify: `backend/app/api/routes_query.py:1028-1045` and both call sites
- Create: `backend/tests/test_browser_demotion.py`

**Interfaces:**
- Consumes: `IntentResponse` (intent, target_agent, extracted_entity, reasoning, confidence, ambiguous).
- Produces: `_demote_browser_intent(...) -> tuple[IntentResponse, bool]` — the second element is `demoted`, and when true the route answers with a spoken limitation instead of a topic-matched essay.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_browser_demotion.py`:

```python
"""A browser request with no page open must not be answered as if it were an
informational question. The user asked for an action; the honest reply is that
there is nothing to act on."""
from app.api.routes_query import _demote_browser_intent
from app.schemas.query import IntentResponse


def intent(name, target, label):
    return IntentResponse(intent=label, target_agent=target,
                          extracted_entity="x", reasoning="r", confidence=0.9,
                          ambiguous=False)


def test_act_without_page_reports_demotion():
    demoted_result, demoted = _demote_browser_intent(
        intent("browser_act", "browser_agent", "browser_act"), page_present=False)
    assert demoted is True
    assert demoted_result.target_agent == "form_agent"


def test_no_demotion_when_page_present():
    src = intent("browser_act", "browser_agent", "browser_act")
    result, demoted = _demote_browser_intent(src, page_present=True)
    assert demoted is False
    assert result is src


def test_non_browser_intent_never_demoted():
    result, demoted = _demote_browser_intent(
        intent("form_help", "form_agent", "form_help"), page_present=False)
    assert demoted is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_browser_demotion.py -q`
Expected: FAIL — the function returns an `IntentResponse`, so `demoted` unpacking raises `ValueError`/assertion error.

- [ ] **Step 3: Return the demotion flag**

Change the signature and both return paths of `_demote_browser_intent`:

```python
def _demote_browser_intent(intent_result, page_present: bool):
    """A browser_* intent with no open page has nothing to act on. Returns
    (result, demoted); `demoted` makes the caller state the limitation aloud
    instead of letting an informational agent answer as if the action ran."""
    if intent_result.target_agent == "browser_agent" and not page_present:
        fallback = {
            "browser_inspect": ("web_navigation_help", "web_agent"),
            "browser_act": ("form_help", "form_agent"),
        }.get(intent_result.intent, ("web_navigation_help", "web_agent"))
        return (IntentResponse(
            intent=fallback[0], target_agent=fallback[1],
            extracted_entity=intent_result.extracted_entity,
            reasoning=intent_result.reasoning + " [demoted: no live page open]",
            confidence=intent_result.confidence,
            ambiguous=intent_result.ambiguous,
        ), True)
    return intent_result, False
```

- [ ] **Step 4: Speak the limitation at both call sites**

At `routes_query.py:1211` and `:1338`, unpack and branch. The answer must name what is missing and what would unblock it — written for a screen reader, no visual references:

```python
    intent_result, demoted = _demote_browser_intent(
        intent_result,
        page_present=(
            _live_pages.get(request.session_id) is not None
            or _extract_url(request.input_text, request.screen_context) is not None
        ),
    )
    if demoted:
        return await _finish_turn(
            db, session, current_user, session_uuid,
            answer=(
                "I can't do that from here. You asked me to act on a page, and I "
                "have no page open for this session. Open the page and ask me to "
                "read it, paste its address to me, or install the AdaptiveAI "
                "browser extension so I can work in the page you are already in. "
                "I have not clicked or filled anything."
            ),
            agent_used="limitation",
            suggested_action="none",
            sources_used=[],
            confidence=intent_result.confidence,
            intent_label=intent_result.intent,
            request_id=request_id,
        )
```

Read the real `_finish_turn` signature before editing and match its parameters exactly — if it takes fewer arguments, drop the extras rather than inventing them, and keep the `answer` text intact.

- [ ] **Step 5: Run the new and the existing query tests**

Run: `docker compose exec -T backend python -m pytest tests/test_browser_demotion.py tests/test_pagecontext.py -q`
Expected: all pass. Then `bash scripts/verify.sh backend` for the whole suite.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes_query.py backend/tests/test_browser_demotion.py
git commit -m "fix(backend): state the limitation when a browser action has no page"
```

---

### Task 5: Stop `_plan_task` from pretending to plan

`browser_agent.py:87-113` matches only literal keys (`navigate_to_url`, `fill_field`, …). Any natural-language intent falls through to one fixed three-step exploratory sequence, which is then narrated as if it were a plan for the request. README §2 calls this `POST /agent/browse`.

**Files:**
- Modify: `browser-agent/app/services/browser_agent.py:29-36,87-113`
- Modify: `browser-agent/tests/test_browser_agent.py` (append)

**Interfaces:**
- Consumes: `intent: str`.
- Produces: `execute_task(intent, context)` returning `{"status": "exploratory", ...}` when the intent is not a recognized verb, and `unsupported_intent: True`, instead of dressing a generic sniff up as a plan.

- [ ] **Step 1: Write the failing test**

Append to `browser-agent/tests/test_browser_agent.py`:

```python
@pytest.mark.asyncio
async def test_natural_language_intent_is_reported_exploratory_not_planned():
    """_plan_task matched only literal verb keys and ran a fixed sniff for
    everything else while narrating it as a completed task."""
    a = BrowserAgent(session_id="s2", driver=FakeDriver())
    a.tools = {"accessibility_tree": CountingTool(), "vlm_analysis": CountingTool(),
               "browser": CountingTool()}
    out = await a.execute_task("book me two seats to Chandigarh", {})
    assert out["unsupported_intent"] is True
    assert out["status"] == "exploratory"
    assert "not a booking" in out["narration"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T browser-agent python -m pytest tests/test_browser_agent.py -q`
Expected: FAIL with `KeyError: 'unsupported_intent'`.

- [ ] **Step 3: Mark the fallback honestly**

In `_plan_task`, replace the trailing `return [ ...exploratory... ]` with a tagged tuple, and have `execute_task` surface it. Above the fallback:

```python
        # No natural-language understanding here: this is a fixed page sniff, and
        # it must never be narrated as a plan for what the user asked. Real
        # step-by-step planning arrives with the extension's
        # POST /api/extension/step (design spec §4.2), which is why this route
        # declares itself exploratory instead of pretending otherwise.
        return EXPLORATORY
```

Define at module level: `EXPLORATORY = "exploratory"` and keep the three-step list behind it. In `execute_task`, detect the sentinel before the loop, run the sniff, and return:

```python
        exploratory = steps is EXPLORATORY
        if exploratory:
            steps = [
                {"tool": "accessibility_tree", "action": "extract", "args": {}},
                {"tool": "browser", "action": "extract", "args": {}},
            ]
```

and in the return dict add:

```python
            "status": "exploratory" if exploratory else "planned",
            "unsupported_intent": exploratory,
            "narration": (
                ("I looked the page over: structure and text only. I did not act, "
                 "and this is not a booking. ") if exploratory else ""
            ) + self._generate_narration(results),
```

Drop the `vlm_analysis` step from the fallback: it hard-fails without `NIM_API_KEY` and adds a 502-shaped step to a result that should be a clean "I only looked".

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec -T browser-agent python -m pytest tests/test_browser_agent.py -q`
Expected: 4 passed.

- [ ] **Step 5: Update the route's OpenAPI description so the limitation is public**

In `browser-agent/app/main.py:270`, set the `summary`/`description` of `POST /agent/browse` to say it performs an exploratory page read and does not execute multi-step tasks.

- [ ] **Step 6: Commit**

```bash
git add browser-agent/app/services/browser_agent.py browser-agent/app/main.py browser-agent/tests/test_browser_agent.py
git commit -m "fix(browser-agent): declare exploratory browsing instead of fake planning"
```

---

### Task 6: A real Chromium suite — the first test that launches a browser

Every existing `browser-agent` test injects `FakeDriver`; **no test in the repository has ever started Chromium**. Without one, "real Playwright" is a claim about code, not a verified behaviour.

**Files:**
- Create: `browser-agent/tests/test_real_browser.py`
- Modify: `browser-agent/pytest.ini` (register the `browser` marker)
- Verify: `browser-agent/Dockerfile` already runs `playwright install --with-deps chromium`

**Interfaces:**
- Consumes: `app.tools.driver.Driver` — `.start()`, `.navigate(url)`, `.snapshot()`, `.stop()`.
- Produces: a `browser`-marked suite that fails CI if the perception layer stops returning genuine page facts.

- [ ] **Step 1: Confirm the image actually has Chromium**

Run: `docker compose exec -T browser-agent python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); print('chromium', b.version); b.close(); p.stop()"`
Expected: a version string. If this fails, install is missing from the Dockerfile — fix that first; this task is not done until a browser really launches.

- [ ] **Step 2: Register the marker**

In `browser-agent/pytest.ini`, add `browser` under `markers =`, and change `addopts` to `-m "not live" -q` staying as-is (the `browser` tests run offline against localhost fixtures, so they are *not* `live`-marked).

- [ ] **Step 3: Write the suite**

Create `browser-agent/tests/test_real_browser.py`:

```python
"""The first tests in this repo that launch a real Chromium. Everything else
injects FakeDriver, which proves routing but never proves perception.

Serves its own fixture page over 127.0.0.1 so the assertions are about the
page, not about a vendor that may redesign mid-week. AUTOMATION_SAFETY.md is
honoured: a Playwright-launched browser, input only through page objects.
"""
import asyncio
import functools
import http.server
import socketserver
import threading
import pytest
from app.tools.driver import Driver

PAGE = b"""<!doctype html><html><head><title>Fixture booking</title></head>
<body><form>
  <label for="pname">Passenger name</label><input id="pname" name="pname">
  <label for="seats">Seats</label><input id="seats" name="seats">
  <button type="submit">Book tickets</button>
</form></body></html>"""


@pytest.fixture(scope="module")
def server():
    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(PAGE)))
            self.end_headers()
            self.wfile.write(PAGE)

        def log_message(self, *a):
            pass

    httpd = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{port}/"
    httpd.shutdown()


@pytest.mark.asyncio
async def test_snapshot_reads_real_labels(server):
    d = Driver()
    await d.start()
    try:
        nav = await d.navigate(server)
        assert nav["title"] == "Fixture booking"
        snap = await d.snapshot()
        labels = {n.get("label") for n in snap["nodes"]}
        assert "Passenger name" in labels, f"real labels missing, got {labels}"
        assert "Book tickets" in labels
    finally:
        await d.stop()


@pytest.mark.asyncio
async def test_fill_is_read_back_from_the_real_dom(server):
    d = Driver()
    await d.start()
    try:
        await d.navigate(server)
        snap = await d.snapshot()
        field = next(n for n in snap["nodes"] if n.get("label") == "Passenger name")
        await d.fill(field["selector"], "Asha Sharma")
        assert await d.read_value(field["selector"]) == "Asha Sharma"
    finally:
        await d.stop()
```

Read `app/tools/driver.py` first and use its real method names for reading a value back — if there is no `read_value`, add one that returns `element.input_value()` rather than weakening the assertion, because the readback *is* the point of the task.

- [ ] **Step 4: Run the suite**

Run: `docker compose exec -T browser-agent python -m pytest tests/test_real_browser.py -v`
Expected: 2 passed. Any failure here is a genuine perception bug found by running, which is exactly what this task exists to produce.

- [ ] **Step 5: Wire it into CI**

In `.github/workflows/ci.yml`'s `browser-agent` job, after the `pytest` step add:

```yaml
      - name: Install Chromium for real-browser tests
        run: playwright install --with-deps chromium
      - name: Real Chromium perception tests
        run: pytest tests/test_real_browser.py -v
```

- [ ] **Step 6: Commit**

```bash
git add browser-agent/tests/test_real_browser.py browser-agent/pytest.ini .github/workflows/ci.yml
git commit -m "test(browser-agent): first tests that launch a real Chromium"
```

---

### Task 7: `speak()` must not resolve when nothing was spoken

`useTextToSpeech.ts:59-74` returns early on `!supported` and on `volume === 0`, resolving the promise either way. Callers that `await speak(...)` then proceed as though narration reached the user — the most consequential possible silent failure for a blind user.

**Files:**
- Create: `frontend/tts_proof.py`
- Modify: `frontend/src/hooks/useTextToSpeech.ts:4-9,59-74`
- Modify: call sites that currently treat resolution as "spoken"

**Interfaces:**
- Consumes: `enqueueSpeech` from `utils/speechQueue`.
- Produces: `speak(text) -> Promise<"spoken" | "silent">`, where `"silent"` is returned (not thrown) for the deliberate muted case, and the hook exposes `supported` so callers can tell why.

- [ ] **Step 1: Change the contract**

In `useTextToSpeech.ts`, replace the interface and the early returns:

```typescript
interface UseTextToSpeechReturn {
  // "silent" means the text was NOT spoken: unsupported engine, or an explicit
  // mute at volume 0. Callers must not describe content as announced after it.
  speak: (text: string) => Promise<'spoken' | 'silent'>;
  stop: () => void;
  isSpeaking: boolean;
  supported: boolean;
}
```

```typescript
  const speak = useCallback(async (text: string): Promise<'spoken' | 'silent'> => {
    if (!supported) return 'silent';
    // ... existing rate/pitch/volume reads unchanged ...
    if (volume === 0) return 'silent';

    await enqueueSpeech(text, { rate, pitch, volume, voice: getPreferredVoice() });
    return 'spoken';
  }, [supported, getPreferredVoice]);
```

- [ ] **Step 2: Fix the callers that claimed narration**

Run: `grep -rn "await speak\|\.speak(" frontend/src --include=*.ts --include=*.tsx`
For each site that speaks and then reports success (status text, "Announced …", dialog open), branch on the result. Where a mute is legitimate, keep the flow but stop the narration *claim*; where speech is the whole point (e.g. a form-fill result), surface a visible+announced fallback or an error state.

- [ ] **Step 3: Type-check**

Run: `cd frontend && npm run build`
Expected: `tsc` strict passes. A call site that ignored the new return type still compiles, so do not rely on the build alone — Step 2's grep is the actual check.

- [ ] **Step 4: Prove it in a real browser**

Create `frontend/tts_proof.py`, following `AUTOMATION_SAFETY.md:40` by asserting isolation:

```python
"""Proves speak() no longer resolves a vacuous success.

Drives the built frontend in a Playwright-launched Chromium with a fake audio
input, never OS-level input (AUTOMATION_SAFETY.md). Run with the stack up:
    python frontend/tts_proof.py http://localhost:5173
"""
import sys
from playwright.sync_api import sync_playwright

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"

# volume 0 is the mute case: enqueue must NOT be called.
with sync_playwright() as p:
    browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
    page = browser.new_page()
    page.goto(URL, wait_until="domcontentloaded")
    spoken = page.evaluate("""async () => {
        let enqueued = 0;
        const orig = window.speechSynthesis?.speak?.bind(window.speechSynthesis);
        if (window.speechSynthesis) {
            window.speechSynthesis.speak = (u) => { enqueued++; return orig(u); };
        }
        document.documentElement.style.setProperty('--voice-volume', '0');
        const r = await window.__adaptiveai_test_speak?.('silence test');
        return { result: r ?? 'no-test-hook', enqueued };
    }""")
    browser.close()

if spoken["result"] == "no-test-hook":
    print("FAIL: no test hook; expose speak on window in dev builds only")
    raise SystemExit(1)
if spoken["result"] != "silent" or spoken["enqueued"] != 0:
    print(f"FAIL: muted speak reported {spoken}")
    raise SystemExit(1)
print("PASS: muted speak returns 'silent' and enqueues nothing")
```

Add the dev-only hook (`if (import.meta.env.DEV) (window as any).__adaptiveai_test_speak = speak;`) inside the hook so the proof has something to call, and gate it so it never ships in a production bundle.

- [ ] **Step 5: Run the proof**

Run: `docker compose up -d && python frontend/tts_proof.py http://localhost:5173`
Expected: `PASS: muted speak returns 'silent' and enqueues nothing`, exit 0.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/hooks/useTextToSpeech.ts frontend/tts_proof.py frontend/src
git commit -m "fix(frontend): speak() reports silence instead of false success"
```

---

### Task 8: Delete the mock user endpoint

`auth.py:191-193` `get_demo_user()` returns a fresh random-UUID `DemoUser` and is referenced **nowhere** — grep confirms its only appearance is its own definition. The `DemoUser` class itself is live (used by the DEBUG no-token path at `:111`/`:147` and asserted in `tests/test_hardening.py:276-279`) and stays.

**Files:**
- Modify: `backend/app/api/auth.py:184-193`
- Create: `backend/tests/test_no_mock_identity_endpoint.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no route or helper in the auth module can hand a caller an identity that was never authenticated.

- [ ] **Step 1: Write the guard test**

Create `backend/tests/test_no_mock_identity_endpoint.py`:

```python
"""A callable that mints an authenticated-looking identity with no credential
behind it must not exist in the product path. The DEBUG no-token demo identity
is a separate, explicitly-labelled concern and stays."""
import inspect
import pytest
from app.api import auth


def test_mock_identity_helper_is_gone():
    assert not hasattr(auth, "get_demo_user"), (
        "get_demo_user resurrected: it returns a random-UUID user with no "
        "credential and no caller - a mock identity endpoint")


def test_demo_user_is_not_usable_as_a_dependency():
    # DemoUser is only ever constructed inside get_current_user_optional's
    # DEBUG branch; nothing may depend on it directly.
    src = inspect.getsource(auth)
    assert "Depends(get_demo_user)" not in src
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_no_mock_identity_endpoint.py -q`
Expected: first test FAILS.

- [ ] **Step 3: Delete the function**

Remove lines 191-193 and their docstring. Keep `class DemoUser` and retitle its comment so the surviving use is explicit:

```python
# Ephemeral DEBUG identity for the no-token dev path in get_current_user_optional
# (there is no database to look a real user up in). Never a dependency, never a
# production identity.
class DemoUser:
```

- [ ] **Step 4: Run the auth suite**

Run: `docker compose exec -T backend python -m pytest tests/test_no_mock_identity_endpoint.py tests/test_auth_and_proxy.py tests/test_hardening.py -q`
Expected: all pass — `test_hardening.py`'s `isinstance(user, DemoUser)` still holds.

- [ ] **Step 5: Mark the shared demo identity in the API response**

The DEBUG no-token path keys all per-user data to one shared identity. So that "history" and "preferences" are not silently pretend, log once at first use and include the marker where the response schema allows a debug field:

```python
        logger.warning(
            "DEBUG demo identity in use - history and preferences are shared by "
            "every tokenless caller. Production refuses DEBUG boot by design."
        )
```

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/auth.py backend/tests/test_no_mock_identity_endpoint.py
git commit -m "fix(backend): remove the unused mock identity endpoint"
```

---

### Task 9: Label a heuristic confidence as what it is

`classifier.py:181` computes `confidence = min(0.9, 0.4 + 0.1 * best_score)` when the LLM is unreachable. It is honest about being a fallback but the number arrives at the UI looking identical to a model's self-assessment, and README §2 prints "conf 0.95" as evidence of quality.

**Files:**
- Modify: `intent-engine/app/schemas.py:12-24`
- Modify: `intent-engine/app/classifier.py:132-136,175,181` and every `ClassifyResponse` construction
- Modify: `intent-engine/tests/test_keyword_classifier.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ClassifyResponse.confidence_source: Literal["llm", "keyword", "default"]`, with `keyword` wherever the formula produced the number and `llm` where the model self-assessed.

- [ ] **Step 1: Write the failing test**

Append to `intent-engine/tests/test_keyword_classifier.py`:

```python
def test_keyword_fallback_declares_its_confidence_source():
    """The keyword formula (0.4 + 0.1*score) is not a model judgment; shipping
    it as a bare number let a fallback look as trustworthy as the LLM."""
    from app.classifier import keyword_classify
    out = keyword_classify("fill in my aadhaar number on this form")
    assert out.confidence_source == "keyword"
    assert out.confidence <= 0.9


def test_no_match_default_is_marked_default():
    from app.classifier import keyword_classify
    out = keyword_classify("zzz qqq nothing matches this")
    assert out.confidence_source == "default"
    assert out.confidence == 0.3
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T intent-engine python -m pytest tests/test_keyword_classifier.py -q`
Expected: FAIL — `keyword_classify` returns a tuple / the field does not exist.

- [ ] **Step 3: Add the field**

In `schemas.py`, after `ambiguous`:

```python
    # Who produced the number above: the model's self-assessment ("llm"), the
    # keyword-match formula ("keyword"), or the no-match default. A heuristic
    # 0.9 is not a model's 0.9 and the UI must be able to say so.
    confidence_source: Literal["llm", "keyword", "default"] = "llm"
```

Add `from typing import Literal` to the imports.

- [ ] **Step 4: Set it on every fallback path**

In `classifier.py`, extend `keyword_classify`'s returns so each carries its source — `0.85` browser-route hit → `"keyword"`, no-match `0.3` → `"default"`, scored match → `"keyword"` — and make the function return a `ClassifyResponse` rather than a bare tuple if it does not already, so the field cannot be dropped by a caller. Where the LLM path builds the response, set `confidence_source="llm"` explicitly rather than relying on the default.

- [ ] **Step 5: Run the suite**

Run: `docker compose exec -T intent-engine python -m pytest -q`
Expected: all pass, including `tests/test_api.py`.

- [ ] **Step 6: Surface it in the frontend**

In `MessageBubble.tsx`, wherever confidence is rendered, append `(keyword match)` when `confidence_source !== 'llm'`. Read the file first and follow its existing markup; do not add a new live region, and do not put the label inside an element that duplicates the answer's announcement.

- [ ] **Step 7: Commit**

```bash
git add intent-engine/app/schemas.py intent-engine/app/classifier.py intent-engine/tests/test_keyword_classifier.py frontend/src
git commit -m "feat(intent): label heuristic confidence as a keyword match"
```

---

### Task 10: Fail loudly in production when the shared store is missing

`session_memory.py:35-42` falls back to a process-local in-memory TTL store when Redis is unreachable. On a single dev box that is harmless; with two instances it silently partitions session state, and `README.md:360-362` already documents Redis as a safe-to-loss cache — which is a different claim from "safe to be absent while scaling".

**Files:**
- Modify: `backend/app/services/session_memory.py:30-45`
- Create: `backend/tests/test_shared_store_production.py`

**Interfaces:**
- Consumes: `settings.production` (the flag `ADAPTIVEAI_PRODUCTION=1` already drives the DEBUG refusal in `app/main.py`).
- Produces: a startup check that raises under production when Redis is unreachable; unchanged silent fallback otherwise.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_shared_store_production.py`:

```python
"""An in-process TTL store is fine for one dev instance and a silent data-loss
bug for a multi-instance production deployment. Production must refuse to
pretend session state is shared."""
import pytest
import redis as redis_lib
from app.config import settings
from app.services import session_memory


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    monkeypatch.setattr(session_memory, "_client", None)
    monkeypatch.setattr(session_memory, "_fallback", True)


def test_production_refuses_unreachable_redis(monkeypatch):
    monkeypatch.setattr(settings, "production", True, raising=False)

    def boom(*a, **k):
        raise redis_lib.exceptions.ConnectionError("no redis")

    monkeypatch.setattr(redis_lib, "Redis", lambda *a, **k: type("X", (), {"ping": boom})())
    with pytest.raises(RuntimeError, match="shared store"):
        session_memory._connect()


def test_dev_still_falls_back(monkeypatch):
    monkeypatch.setattr(settings, "production", False, raising=False)
    monkeypatch.setattr(redis_lib, "Redis", lambda *a, **k: type("X", (), {
        "ping": lambda: (_ for _ in ()).throw(redis_lib.exceptions.ConnectionError("x"))})())
    session_memory._connect()          # must not raise
    assert session_memory._fallback is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_shared_store_production.py -q`
Expected: FAIL — no `_connect()`/`_fallback` symbols yet.

- [ ] **Step 3: Split connection from fallback**

Refactor the module-level connect into `_connect()`, keeping its current behaviour for dev and adding the production refusal:

```python
def _connect() -> None:
    """Redis backs the TTL stores. Unreachable in dev -> process-local fallback
    (fine for one instance). Unreachable under ADAPTIVEAI_PRODUCTION -> raise:
    a second instance would silently stop sharing session state."""
    global _client, _fallback
    try:
        _client = redis_lib.Redis.from_url(
            _REDIS_URL, decode_responses=True,
            socket_connect_timeout=2.0, socket_timeout=2.0)
        _client.ping()
        _fallback = False
    except Exception as e:
        if getattr(settings, "production", False):
            raise RuntimeError(
                f"ADAPTIVEAI_PRODUCTION is set but the shared store is "
                f"unreachable ({e}); refusing to run with a per-process TTL "
                f"store that would silently partition session state") from e
        logger.warning("redis unavailable (%s) - in-memory TTL fallback", e)
        _client, _fallback = None, True
```

Verify `settings` exposes `production`; if the flag lives elsewhere, use whatever `app/main.py` consults for the existing DEBUG refusal rather than adding a new setting.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose exec -T backend python -m pytest tests/test_shared_store_production.py -q`
Expected: 2 passed.

- [ ] **Step 5: Record the robots default honestly**

In `browser-agent/app/main.py:164`, `robots_ok, robots_reason = True, "no host to check"` reads as "permitted" in the session log for non-HTTP URLs. Change the reason string to `"not_applicable (non-http target)"` and add a test asserting the log records `not_applicable` rather than an allow. Keep the behaviour — `data:` URLs must still open.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/session_memory.py backend/tests/test_shared_store_production.py browser-agent/app/main.py browser-agent/tests
git commit -m "fix(backend,browser-agent): refuse silent shared-store loss in prod"
```

---

### Task 11: Give the handless agents hands, or take away the claim

`suggested_action` is rendered as "Suggested: highlight button" and never executed (`MessageBubble.tsx:109-117`). `profile_updater_agent` is told to "confirm the change" while no code applies one. `scheduler_agent` promises "reminder" and nothing fires. Spec §8 item 5; the `ui_adjuster` half waits for Plan B's extension.

**Files:**
- Modify: `agents/agents/profile_updater_agent.py`
- Modify: `agents/agents/scheduler_agent.py:10-19`
- Modify: `backend/app/api/routes_query.py` (apply parsed profile changes)
- Modify: `frontend/src/components/MessageBubble.tsx:109-117`
- Create: `backend/tests/test_profile_update_is_applied.py`

**Interfaces:**
- Produces: `profile_updater_agent` returns `extracted_changes: dict` (validated subset of `disability_profile|verbosity_level|voice_speed|language_complexity`); `/api/query` writes it through the existing `PUT /api/preferences` logic and confirms only what was actually stored. `suggested_action` is either executed or not rendered.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_profile_update_is_applied.py`:

```python
"""'Your profile has been updated' must be the consequence of a write, not a
sentence the model happened to produce."""
import pytest
from app.api import routes_query


def test_only_known_preference_keys_are_applied():
    changes = {"verbosity_level": "concise", "role": "admin", "voice_speed": 99}
    allowed = routes_query._sanitise_preference_changes(changes)
    assert allowed == {"verbosity_level": "concise"}


@pytest.mark.asyncio
async def test_profile_update_writes_before_confirming(client, monkeypatch):
    written = {}
    monkeypatch.setattr(routes_query, "_apply_preference_changes",
                        lambda changes: written.update(changes))
    resp = client.post("/api/query", json={
        "session_id": "s1", "input_text": "make your answers shorter please",
        "input_source": "text", "screen_ctx": ""})
    assert resp.status_code == 200
    if resp.json().get("agent_used") == "profile_updater_agent":
        assert written, "agent confirmed a change that was never written"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `docker compose exec -T backend python -m pytest tests/test_profile_update_is_applied.py -q`
Expected: FAIL — `_sanitise_preference_changes` does not exist.

- [ ] **Step 3: Make the change real**

Add to `routes_query.py` a validator against the existing `Preference` schema — never a free-form dict from the model:

```python
_PREFERENCE_KEYS = {"disability_profile", "verbosity_level", "voice_speed",
                    "language_complexity"}


def _sanitise_preference_changes(changes: dict) -> dict:
    """Whitelist + range check. An LLM proposing {"role": "admin"} or a 99x
    speech rate must not reach the preference row."""
    out = {k: v for k, v in (changes or {}).items() if k in _PREFERENCE_KEYS}
    if "voice_speed" in out:
        try:
            speed = float(out["voice_speed"])
        except (TypeError, ValueError):
            out.pop("voice_speed")
        else:
            out["voice_speed"] = min(max(speed, 0.5), 3.0)
    return out
```

Then have `profile_updater_agent` return a parseable change set alongside its prose, and in the query route apply it through the same persistence path `PUT /api/preferences` uses and build the confirmation from **what was stored** — e.g. `Set verbosity to concise.` / `I could not apply that; your speech rate must be between 0.5 and 3.`

- [ ] **Step 4: Remove the words that promise a capability that does not exist**

In `scheduler_agent.py`, replace the system prompt's `what, when, reminder` framing with plan-only language, and change `_get_suggested_action` to return `"none"`:

```python
    @property
    def system_prompt_template(self) -> str:
        return (
            "You are a Task Planner for blind and low-vision users. Turn a "
            "request into a short ordered plan: what, then what, with explicit "
            "times. Number every step, one action per step. You do NOT create "
            "reminders, alarms, or calendar entries and you must not say that "
            "you did - no reminder fires from this system."
        )

    def _get_suggested_action(self, query: str, entity: str) -> str:
        # "plan_schedule" implied a scheduler that does not exist.
        return "none"
```

- [ ] **Step 5: Delete the decorative suggestion**

In `MessageBubble.tsx`, remove the `suggested-action` block (lines 109-117) entirely. A label that reads "Suggested: highlight button" to a user who cannot verify that nothing was highlighted is a claim about the system, not a hint. If a suggestion should be actionable, that belongs with Plan B's executor — at which point it becomes a real button that does the thing.

Run: `grep -rn "suggested_action" frontend/src backend/app` and remove the now-dead type field only where nothing reads it; keep the backend field if tests assert on it, and note that in the commit message.

- [ ] **Step 6: Run the suites**

Run: `bash scripts/verify.sh backend agents`
Expected: the new tests pass, and any agent-registry test that asserted `suggested_action == "update_profile"` or `"plan_schedule"` is updated to the new honest value rather than deleted.

- [ ] **Step 7: Commit**

```bash
git add agents/ backend/app/api/routes_query.py backend/tests/test_profile_update_is_applied.py frontend/src/components/MessageBubble.tsx
git commit -m "fix(agents,backend): apply profile changes, drop decorative suggestions"
```

---

### Task 12: Proof scripts that can fail, and a README that matches them

Three `r9_*` proof scripts print expectations — `r9_monitor_proof.py:133-134` prints `(expected 0)`, `:196` prints `must be 1` — and then exit 0 regardless. A script that cannot fail is not a proof. After this task the README's claims are rewritten against these scripts and the measured baseline from Task 1.

**Files:**
- Modify: `scripts/r9_monitor_proof.py`, `scripts/r9_chat_loop_proof.py`, `scripts/r9_any_site_fill_proof.py`
- Modify: `README.md:13-23,63-90,306-320,340-389` and `demo/book-tickets.html` header
- Create: `docs/proofs/README.md`

**Interfaces:**
- Produces: `_require(cond, msg)` — prints `FAIL: msg` to stderr and `raise SystemExit(1)`; every scenario ends in assertions and an explicit exit 0.

- [ ] **Step 1: Add the failure primitive**

In `r9_monitor_proof.py`, after the imports:

```python
def _require(cond, msg):
    """A proof that cannot fail is not a proof. Print, then exit non-zero."""
    if not cond:
        print(f"FAIL: {msg}", file=sys.stderr)
        raise SystemExit(1)
    print(f"ok: {msg}")
```

- [ ] **Step 2: Convert the printed expectations into assertions**

In `scenario_gating`, replace the `print(f"  narrations so far: ...")` block (lines 133-134) with the same information enforced:

```python
    pull = narrations(sid)
    counters = pull["stats"]["counters"]
    _require(counters["narrations"] == 0,
             f"a typing-only edit must not narrate (got {counters['narrations']})")
```

After each `wait_for_narrations(...)` call, require the event landed and that it came from a structural signal, never model prose:

```python
    _require(len(events) >= 1, "seat-count validation error was never narrated")
    _require(events[0]["trigger"] in ("dom_change", "aria_live", "new_field"),
             f"unexpected narration trigger {events[0]['trigger']!r}")
```

In `scenario_stress`, require the rate ceiling actually bit:

```python
    _require(c["polls"] > 0, "monitor never polled the live page")
    _require(c["changes_detected"] > 0, "monitor saw no DOM changes on a mutating page")
    _require(c["rate_blocked"] > 0, f"rate ceiling never engaged: {c}")
    _require(after.get("active") is False, "monitor still active after stop")
```

In `scenario_interruption`, require `deferred_by_quiet == 1` rather than printing it, and assert the narration timestamp is later than the user turn. End every scenario with `return stats` and change `__main__` to exit explicitly:

```python
if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "gating"
    {"gating": scenario_gating, "interruption": scenario_interruption,
     "stress": scenario_stress, "fivemin": scenario_fivemin}[what]()
    raise SystemExit(0)
```

- [ ] **Step 3: Do the same to the other two scripts**

For `r9_chat_loop_proof.py` and `r9_any_site_fill_proof.py`, add the same `_require` helper and convert each printed expectation into an assertion on a status, a count, or a field name — with these required checks: chat loop must assert the reply carries a non-empty `response_text`, a known `agent_used`, and that the session history grew by the turns it sent; any-site fill must assert, per field, that the **readback value equals the value sent** and that any field whose readback mismatched is reported in the failure output rather than counted as done.

- [ ] **Step 4: Make the scripts say what they are not**

Add to each script's module docstring, in plain terms:

```python
Scope: these drive the repo's OWN demo pages (demo/book-tickets*.html served by
the demo-forms container). They prove the fill/monitor pipeline acts on a real
DOM. They are NOT evidence of booking on any real vendor - no vendor page is
touched here, and the demo page's "PNR" is a hash of the passenger name
(demo/book-tickets.html:58).
```

- [ ] **Step 5: Run every scenario and record the result**

Run: `export ADAPTIVEAI_ALLOW_LOCAL_TARGET=1` then, for each of `gating`, `stress`, `interruption`, `fivemin`:
Run: `python scripts/r9_monitor_proof.py gating`
Expected: `ok:` lines and exit 0 — or a `FAIL:` with exit 1. **A FAIL is a real finding**: fix the underlying behaviour (or record the defect honestly in `docs/proofs/README.md`), never soften the assertion to pass.

- [ ] **Step 6: Rewrite README §2 and §5 against measured facts**

Replace the certification lines with the truth, keeping the good parts (the fail-honest-with-5xx discipline is real and worth stating):

- Correct §1's "No mocks anywhere" to name what this pass removed and to point at `docs/verification-baseline.md` for how claims are measured.
- Rewrite the "Ticket booking, container Chromium" row so it states the target is the repo's own demo page and that no real vendor is automated in this release; cross-reference spec §7.1 for what the extension will and will not reach.
- Replace §5's host `python -m pytest` block with `bash scripts/verify.sh`, and the "454 passed" claim with the Task 1 numbers, dated, with the host caveat.
- Add to §6 the gaps this plan closes (fake success paths, assertion-free proofs, no real-browser test, decorative suggestions) and the ones it does not (human NVDA pass, live vendor booking, Android).
- State plainly that §2's earlier "proof" rows predate this pass and were re-measured on <date>, or mark them superseded.

- [ ] **Step 7: Label the demo pages at the top of the file**

In `demo/book-tickets.html` and `demo/book-tickets-monitored.html`, add a visible and screen-reader-announced banner — `<div role="alert">Demo page built for this repository's tests. No real tickets are sold here and the reference number is a hash.</div>` — so a demo can never be mistaken for a vendor by the person who cannot see the URL.

- [ ] **Step 8: Commit**

```bash
git add scripts/ README.md docs/proofs/ demo/
git commit -m "docs,scripts: proofs that can fail and claims that match them"
```

---

## Self-Review

**Spec coverage.** §8 item 1 → Task 12 Step 7 (+ Step 6's chip text correction); item 2 → Task 2; item 3 → Task 3; item 4 → Task 4; item 5 → Task 11 (extension half deferred, stated); item 6 → Task 11 Step 5; item 7 → Task 5; item 8 → Task 12 Steps 1–5; item 9 → Task 6; item 10 → Task 7; item 11 → Task 8; item 12 → Task 12 Step 6; item 13 → Task 9; item 14 → Task 10. Phase 0 was completed before this plan (commits `a21f8aa..acef636`). Nothing in §8 is unassigned.

**Corrections made while writing.** My chat finding that the booking chip "conceals" the demo was overstated — [ChatInterface.tsx:42](file:///D:/aipd/frontend/src/components/ChatInterface.tsx#L42) already reads "on the demo booking page". The defect is that it is the *default first* suggestion for a product claiming ticket booking, and that no surface states live vendors are unsupported. Task 12 fixes that. The chat finding that no confirmation gate exists was also wrong: `needs_confirmation` proposals and `/session/{id}/confirm` already ship in `browser-agent/app/main.py`, which is why Plan A leaves them intact and Plan B extends them.

**Baseline finding added to the plan.** The host test claim in README §5 is not reproducible — `backend`, `agents` and `intent-engine` collect **zero** tests on this machine. That is Task 1, ahead of every fix, because TDD is impossible until a test command runs tests.

**Placeholders.** None. Two steps instruct reading a file before editing (`_finish_turn`'s real signature in Task 4 Step 4; the driver's readback method in Task 6 Step 3) — those are deliberate accuracy guards against inventing an API, and each names exactly what to do with what is found.

**Type consistency.** `execute_task` → `status`/`unsupported_intent` (Task 5) match the shape asserted in Task 2's tests; `_demote_browser_intent` returns `tuple[IntentResponse, bool]` in Task 4 Step 3 and both call sites are listed as `routes_query.py:1211` and `:1338`; `confidence_source` is defined once in `schemas.py` and consumed in Task 9 Step 6; `speak()` returns `'spoken' | 'silent'` in Step 1 and is what Task 7's proof asserts.
