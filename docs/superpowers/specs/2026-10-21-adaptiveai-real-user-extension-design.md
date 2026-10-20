# AdaptiveAI — Real blind-user operation + browser extension + truth pass

**Date:** 2026-10-21
**Status:** Design agreed in chat, pending user review of this document
**Supersedes nothing.** Adds a subsystem (extension), a protocol (action/verification), and a corrective pass over claims in `README.md`.

---

## 1. Why this design exists

AdaptiveAI's serving layer is real: Playwright Chromium actually launches
(`browser-agent/app/tools/driver.py:87,92`), STT is real faster-whisper with VAD
anti-hallucination filtering (`backend/app/api/routes_transcribe.py:69-97`), RAG
and NIM calls are real, and unavailable capability returns 502/503/422 rather than
invented data. That discipline is worth keeping and is the reason this is a
corrective pass rather than a rewrite.

But the project cannot currently do the thing it is named for. As measured on this
working tree on 2026-10-21:

| Finding | Evidence |
|---|---|
| No browser extension exists | zero `manifest.json`, zero `chrome.*` API use anywhere in the repo |
| No real platform support | repo-wide grep for BookMyShow / IRCTC / Swiggy / Zomato / RedBus / Paytm → **no code hits**, only a CSS comment and `.pyc` binaries |
| Every "ticket booked" claim is self-referential | `README.md:69` proves against `demo/book-tickets.html`, a page this repo wrote; its "PNR" is a char-code hash of the passenger name (`demo/book-tickets.html:58`) |
| The UI conceals that | `frontend/src/components/ChatInterface.tsx:38-42` pre-fills the demo URL into the "Book my tickets" chip |
| Stale results reported as completed | `browser-agent/app/services/browser_agent.py:48-54` returns a cached prior result, flags `cached`, and counts it in `steps_completed` |
| Unverified clicks reported as success | `backend/app/agents/form/replay_agent.py:318-326` reads `is_checked()`, sees unchecked, executes `pass  # report success w/ state`, returns `success` |
| Browser requests answered without browsing | `backend/app/api/routes_query.py:1028-1045` silently demotes `browser_act`/`browser_inspect` to chat agents when no page is open |
| Four of eleven agents have no effect | `scheduler_agent.py`, `ui_adjuster_agent.py`, `profile_updater_agent.py` are prompt-only subclasses of `BaseAgent.handle` (`agents/agents/base.py:64-101`); no backend code applies a profile change or a UI change or fires a reminder |
| `suggested_action` is decorative | rendered as the text "Suggested: highlight button" (`frontend/src/components/MessageBubble.tsx:109-115`); no code executes it |
| Proof scripts assert nothing | `scripts/r9_monitor_proof.py`, `scripts/r9_chat_loop_proof.py`, `scripts/r9_any_site_fill_proof.py` contain no assertions and no failure exit path; they always return 0 |
| No test ever launches a browser | all four `browser-agent/tests/*` files inject `FakeDriver` and use `data:` URLs; CI's "Browser agent" job runs `pytest` with no Playwright install (`.github/workflows/ci.yml:109-124`) |
| Natural-language "planning" is a key lookup | `browser_agent.py:87-113` matches only literal keys (`navigate_to_url`, `fill_field`); any other intent falls to one fixed 3-step exploratory sequence |

**Step 0 is repository integrity.** `git status` on 2026-10-21 shows 129 modified,
1 deleted, 18 untracked, +6560/−1577 lines, uncommitted since `e9fdef7`
(2026-09-30). HEAD still contains the `SignAvatar.tsx` placeholder that
`FEATURE_PLAN.md:183-186` reports deleted, and lacks `AuthScreen.tsx`,
`FormFillDialog.tsx`, `SharedSession.tsx`, `utils/auth.ts`,
`useDialogFocus.ts`, `utils/apiError.ts`, the `20261007_history_indexes`
migration, and three test files. The README's "verified 2026-10-06" state is a
dirty working tree, not a commit. A project whose stated standard is "everything
above was executed, not asserted" must have a history that matches. **Nothing else
in this design proceeds until the tree is committed.**

## 2. Decisions locked by the product owner

1. **Deadline class:** real tool, 4–8 weeks. Fix pass and extension proceed together.
2. **Target user:** desktop Windows, Chrome or Edge, NVDA. (Not Android/TalkBack; not
   macOS/VoiceOver; low-vision is out of scope for this cycle.)
3. **Authority model:** the agent drives freely (navigate, select, fill, build cart)
   and a human authorizes spend. No money is committed by the agent in this cycle.
4. **Perception:** Approach C — content-script accessible-name computation by
   default, `chrome.debugger`/CDP as explicit per-site opt-in, VLM only for
   unlabelled images and canvas.
5. **Acceptance bar:** live-site verification that stops at the payment wall. Not a
   completed purchase, not a human NVDA trial, not demo-page proofs.

## 3. Non-goals — refused on principle

These are refusals, not deferrals. Each one is a way this project could have looked
finished while being useless or harmful to a blind user.

- **No CAPTCHA solving, no CAPTCHA bypass, no defeat of anti-bot controls.** The
  agent describes a challenge and the user answers it. Building evasion would put a
  real account at risk to make a demo look impressive.
- **No credential storage, no password autofill, and no autonomous login.** Values
  live in `chrome.storage.local` on the user's machine; the user is already logged
  in to their own browser. `type=password` fields are never read and never filled by
  the agent — the user types their own password, which NVDA handles natively. An OTP
  is dictated by the user each time it is needed and is never stored or reused.
- **No payment capability.** The gate stops *before* the irreversible action.
- **No OS-level synthetic input.** This is already project law
  (`AUTOMATION_SAFETY.md:12-21`): Playwright/CDP/page-object input only. The
  extension inherits this by construction — it addresses elements, never screen
  coordinates.
- **No new second brain.** Planning stays in the existing backend (intent engine +
  policy engine + agents + NIM). The extension is a client and an executor.
- **No claims in `README.md` that lack a reproducible command behind them.**

## 4. Architecture

```
Blind user · NVDA · Chrome/Edge on Windows
   │  global hotkey Ctrl+Alt+A (avoids NVDA's Insert/CapsLock modifier combos)
   ▼
┌──────────────────────────── MV3 extension (extension/) ─────────────────────────┐
│                                                                                  │
│  offscreen-document  mic capture → PCM/WAV chunks → POST /api/transcribe.        │
│                      MV3 constraint: getUserMedia is unavailable in a service    │
│                      worker, and an active recording must survive the host tab   │
│                      navigating mid-task.                                        │
│                                                                                  │
│  ax-perceptor        content script. Page → AXSnapshot using the AccName spec    │
│                      + a Core-AAM subset. Pure; no network, no LLM.              │
│                                                                                  │
│  actor               content script. The ONE action protocol. Every call         │
│                      returns an ActionOutcome containing a readback.             │
│                                                                                  │
│  deep-mode           service worker. chrome.debugger + CDP                       │
│                      Accessibility.getFullAXTree. Attaches only on explicit       │
│                      opt-in, announced before attaching, detached when done.      │
│                                                                                  │
│  profile-vault       service worker. chrome.storage.local. The only place a      │
│                      field VALUE ever exists on this path.                       │
│                                                                                  │
│  task-runner         service worker. goal → step → act → verify → narrate.       │
│                      Owns the gate. Holds no model of its own.                   │
│                                                                                  │
│  gate                deterministic local predicate over accessible names. Cannot │
│                      be overridden by a planner response.                        │
└──────────┬───────────────────────────────────────────────▲───────────────────────┘
           │ POST /api/extension/step                       │ action + narration
           │ (structure only: roles, names, states,         │
           │  value-kind; NO values)                        │
           ▼                                                │
   backend :8000   existing JWT bearer auth; new endpoints only
     ├─ intent-engine :8001   intent + confidence (real LLM, flagged keyword fallback)
     ├─ agents :8002          specialists; handless ones get hands or are removed
     └─ policy engine         adaptive verbosity from disability profile
   NIM (LLM + VLM) — receives page STRUCTURE, never page CONTENT values
```

### 4.1 Unit boundaries

Each unit answers: what it does, how it is used, what it depends on.

| Unit | Does | Used by | Depends on | Testable without |
|---|---|---|---|---|
| `ax-perceptor` | DOM → `AXSnapshot` (pure function) | task-runner, deep-mode | DOM, ARIA specs | network, LLM, other units |
| `actor` | `(ref, action, value)` → `ActionOutcome` | task-runner | perceptor refs only | LLM, network |
| `task-runner` | `(goal, snapshot, history)` → next action, gate check, narration | hotkey UI, voice | step API, actor, vault, gate | mic, NVDA |
| `profile-vault` | label → value, local read/write | actor (fill), task-runner (what's missing) | `chrome.storage.local` | network |
| `voice-bridge` | mic → transcript | task-runner | `/api/transcribe` | LLM |
| `narrator` | policy-adjusted text → speech | task-runner | existing FIFO speech queue | backend (queued) |
| `gate` | name+context → `bool irreversible`, amount | task-runner | static grammar, no network | everything |

**Interface rule:** `deep-mode` produces the *same* `AXSnapshot` shape and consumes
the *same* actions as the content-script path. If the two paths grow separate
verbs, we have rebuilt `browser_agent.py`'s mess with a banner attached, and that
is a defect to be fixed on sight.

### 4.2 Server-side changes (deliberately three)

1. **New `POST /api/extension/step`.** Input: `goal`, `AXSnapshot` summary
   (role, accessible name, states, frame URL, `value_kind`, ref hash — values
   redacted), `available_labels` (which vault labels exist, names only),
   `history` (every prior step with its verified outcome), `profile` (disability
   profile + verbosity). Output: `next_action(s)`, `narration`,
   `expected_change` predicate, `gate_required` bool. Reuses the intent engine,
   policy engine and NIM client unchanged.
2. **`browser-agent` is demoted, not deleted.** It keeps a real job: page preview
   and Round 9 monitoring for a user who cannot authenticate, where a server-side
   browser is honest. It stops being presented as the thing that books tickets.
   Its `pattern_cache` replay-as-success is removed.
3. **PII comes out of the request path.** `screen_ctx` currently forwards whole-page text
   to NIM on every query. On a passenger-details or payment page that is a card
   number in a cloud model. The extension path sends structure; the legacy path
   gains redaction of value-bearing text before it goes out.

`frontend/public/manifest.webmanifest` is a PWA manifest and stays. The extension's
MV3 `manifest.json` lives in `extension/` and is a separate artifact.

## 5. The action protocol and verification

This section is the answer to "no fake things". It defines what the word *done*
means.

### 5.1 Statuses

`ActionOutcome.status ∈ verified | failed | gated | unsupported_frame | not_found | ambiguous`

There is no `cached` status and there is no `success` without a readback. A status
of `verified` asserts a specific, recorded fact about the page after the action.

### 5.2 Rule 1 — no action reports success without readback

- `fill` → read the element's own current value after the write, and compare.
- `select` → read `selectedIndex` and the option's accessible name.
- `click` on checkbox/radio → read `checked` (via `aria-checked`/matching input).
  Unchecked after the click → retry once via the associated `label[for]` element.
  Still unchecked → `failed`. The current `pass` at `replay_agent.py:322` becomes a
  retry and then an honest failure; a blind user cannot check.
- `submit`/`Proceed` → governed by Rule 2, not by the click's return value.

**The React trap, named explicitly.** Assigning `el.value` on a React-controlled
input does not update React's state, so a naive content-script fill leaves the
visible value populated while the site's own validation still reports the field
empty. That is precisely the "filled but never typed" bug that makes a form agent
useless. The actor therefore writes by: `focus()` → select existing range →
`document.execCommand('insertText', false, value)` (produces genuine
`beforeinput`/`input`, works for React, Vue, Angular and `contenteditable`),
falling back to the native prototype setter plus a bubbling `InputEvent` and
`ChangeEvent`. A `fill` that cannot achieve a readback match is `failed`.

### 5.3 Rule 2 — `await_change` makes clicks provable

A click is not verified by "no exception was thrown". The planner supplies an
`expected_change` predicate and the actor waits for that kind, on a deadline:

| Predicted kind | Verified by |
|---|---|
| `url_changed` | `location` differs from the pre-click value |
| `node_appears` | a snapshot node matching role+name predicate exists |
| `state_flipped` | `checked`/`aria-expanded`/`disabled` changed on a named node |
| `title_changed` | `document.title` differs |
| `announcement` | an `aria-live`/`role=alert` region received new text |
| `navigation_committed` | cross-document load observed |

Nothing matched by the deadline → `failed`, and the narration reports what *did*
change, if anything. This catches the SPA case where "Proceed" was pressed, the URL
stayed put, and an inline field error appeared — which the current code records as
`success`.

### 5.4 Rule 3 — capture what NVDA would have announced

A `MutationObserver` plus taps on `aria-live`, `role=alert`, `role=status` regions
give the agent the page's own announcements. Two uses: as an `announcement`
verification kind, and to tell the user what changed in a region they were not
focused on. This is the concrete meaning of "act as a blind person": the page's
spoken output is a first-class signal, not a visual afterthought.

### 5.5 Rule 4 — the gate is deterministic and local

`gate` is a static predicate in the extension, evaluated against the target node's
accessible name and its immediate context, before any action executes:

- Money/irreversible name grammar: `pay`, `proceed to payment`, `confirm booking`,
  `confirm order`, `place order`, `book now`, `submit application`, `add card`,
  `save card`, `register`, `cancel ticket`, `apply coupon` (data-driven list,
  reviewable, extendable without touching logic).
- Plus: any action whose target is inside a frame matching a payment-provider host.
- Plus: any `node_appears`/`state_flipped` on a node named for order confirmation.

**A planner response cannot clear the gate.** If `/api/extension/step` returns an
action the local gate flags, the action is refused and the gate fires. This
inverts the usual failure mode where a model can be argued out of a safety rule.

Gate flow: pause → narrate site, exact button text, parsed amount → wait for spoken
"yes" (or Enter on the confirm control) → nothing. No spoken yes within the timeout
→ abort and report. Amount parsed from the button's accessible name or nearest
currency node; if unparseable, narrate without an amount and still gate.

### 5.6 Rule 5 — failures are narrated, not smoothed over

| Status | Spoken (blind + concise profile) |
|---|---|
| `not_found` | "I can't find *<name>* on this page. What I can see: *<top candidates>*." |
| `ambiguous` | "Two things match *<name>*: *A* and *B*. Which one?" |
| `unsupported_frame` | "That control is inside a frame I can't reach. I can switch on deep inspect — Chrome will show a debugging banner. Say yes or no." |
| `failed` | "I pressed *<name>* and the page didn't change the way I expected. It now says: *<announcement>*." |
| `gated` | "About to press *Pay ₹640* on *bookmyshow.com*. This spends money. Say yes to continue, no to stop." |

### 5.7 Privacy boundary

Sent to the backend: role, accessible name, states, frame URL, a per-snapshot ref
hash, `value_kind` (`text|password|email|phone|date|select|checkbox|radio`), and
whether a field is empty. Never sent, and never touched: any value the user typed,
vault contents, `type=password` fields (never read, never autofilled — see §3),
cookies, tokens.

## 6. Perception details

### 6.1 Accessible-name computation (default path)

Implement the parts of AccName + Core-AAM that decide real-site outcomes:

- **Role:** explicit `role`, else implicit from tag (`button`, `a[href]`→link,
  `input[type]`, `select`, `summary`, `nav`, `main`), else `generic`.
- **Name, in precedence order:** `aria-labelledby` → `aria-label` → `title` →
  native `<label for>`/wrapping label → `placeholder` → `alt` → `value` of a
  `type=button` → text content → `aria-describedby` as a last resort, marked
  low-confidence.
- **States:** `checked`, `selected`, `expanded`, `pressed`, `disabled`,
  `readonly`, `required`, `invalid` (including `aria-invalid` and
  `:user-invalid`), plus current value for form controls.
- **Structure:** accessible `description`, live-region politeness, heading level,
  `fieldset`/`legend` grouping for radio and checkbox sets, and whether the node is
  in an open shadow tree (retargeted to the host).
- **Ordering:** DOM order with `document.order` semantics, plus bounding boxes so
  "the third one from the top" can be resolved and announced.

Refs are `(frameId, backendNodeKey)` where available, else a stable structural path
rebuilt on each snapshot and re-validated before action — never the
`tag:nth-of-type(n)` selectors that `driver.py:50` builds today, which break on
the first re-render.

### 6.2 When deep mode is allowed

Attach `chrome.debugger` only if all hold: the user opted in for this origin; the
target is in a cross-origin frame the content script cannot reach; and the agent
announced the banner and its reason before attaching. Detach on task end or on any
error. Deep mode is a capability grant, not a default, because the "started
debugging this browser" infobar is itself a source of confusion for a screen-reader
user and can be dismissed by a stray keystroke.

### 6.3 Where the VLM legitimately belongs

Only two jobs: describing images whose `alt` is missing, empty, or a filename; and
describing canvas-rendered regions such as a seat map, where there is no DOM text
to read at all. It is never the primary read channel — when the accessibility tree
already has the text, routing through an image model is slower, costlier, and less
accurate.

## 7. Making it work on arbitrary sites *and* on three named ones

**No per-site CSS selectors, XPath, or hardcoded element ids in code.** Brittle
selectors are exactly how a project ends up working only on its own demo page.
Three layers instead:

1. **Generic agentic loop** — perceptor → step → act → verify → narrate, repeated
   under a step budget. This is what makes "any website" a true claim rather than a
   slogan.
2. **Task recipes as data.** `extension/recipes/*.json` documents phases, the
   semantic names to look for at each phase, the `expected_change` kind per phase,
   and required vault labels. Keyed by `task_kind + origin`, so a recipe can bias
   the generic loop with knowledge — "IRCTC adds passengers via *Add Passenger*",
   "BookMyShow seat selection is often canvas", "Swiggy needs a delivery location
   before it will show a menu" — without a line of site-specific imperative code.
   A redesign is a data diff, reviewable, and cannot crash.
3. **Verified-trace memory.** On success, store `(origin, page-state signature,
   action, verified outcome)`. On repeat visits the planner receives these as
   priors. Replay means *prefer this action*, never *skip this action*. This is the
   correct version of what `browser_agent.py`'s `pattern_cache` claims to be.

### 7.1 Platform reality, stated before the demo rather than discovered during it

| Platform | Reachable to | Known walls |
|---|---|---|
| **BookMyShow web** | venue → showtime → seat selection → viewer details → cart, gate fires at payment | seat map may be canvas → VLM describes, user names seats verbally; payment is a third-party frame → `unsupported_frame`, hand over; OTP login is user-dictated |
| **IRCTC web** | post-login: train search → class/berth → passenger details → boarding point → fare breakdown | login requires a look-and-feel CAPTCHA and OTP, which the agent **presents and never solves** (VLM describes the image, user types it, refresh loop is a real spoken cost); seat locks expire server-side, so a slow agent can lose the lock — this must be narrated, not hidden; IRCTC's terms prohibit scripted booking, and our position (see §3) is an assistive agent in the user's own authenticated session, with no stored credentials, no CAPTCHA evasion, no bulk behaviour |
| **Swiggy / Zomato web** | location → menu → item → cart → address → gate at checkout | location permission prompt; minimum-order and address validation are inline errors, which is what `await_change` is built to catch; saved-address selection is by accessible name, not by visual position |
| **Government / generic forms** | guided field-by-field fill with readback per field | CAPTCHA + OTP remain user-owned; the existing guided-fill idea at `routes_query.py:298-331,504-521,715-812` ports to the action protocol, replacing its hash-id field location |

**No money is spent by the agent in the accepted build.** That is consistent with
the chosen bar and is the honest state of the art for a first release to a real
user.

## 8. Truth-and-fix pass

Fourteen items. "Fixed" means the behaviour changes, not that a comment improves.

| # | Location | Defect | Fixed means |
|---|---|---|---|
| 0 | whole tree | 3 weeks uncommitted; HEAD lacks the files README certifies | commit the working tree with real messages before any new work; then `git log --stat` matches the claims |
| 1 | `ChatInterface.tsx:38-42` | booking chip hardcodes the repo's own demo URL | label it "demo page (this repo's own test form)"; the unlabelled "Book my tickets" affordance goes away; a live-site path appears only when the extension is present |
| 2 | `browser_agent.py:48-54` | cached result replayed and counted as completed | cache deleted; traces become §7 planning priors only; `steps_completed` counts `verified` only |
| 3 | `replay_agent.py:318-326` | `pass # report success w/ state` | retry once via `label[for]`, else `failed`/`unverified`; never `success` |
| 4 | `routes_query.py:1028-1045` | browser intent silently answered by a chat agent | with the extension: route to the executor. without it: say "I can't act on a page from here, I only have a preview" — no action-shaped answer |
| 5 | `scheduler_agent.py`, `ui_adjuster_agent.py`, `profile_updater_agent.py` | prompt-only, no effect | `profile_updater` really writes `PUT /api/preferences`; `ui_adjuster` really changes page/CSS tokens through the extension; `scheduler` is **demoted to an explicit planner and renamed in its own system prompt and `agent_name` output** — it produces an ordered plan and the words "reminder" are removed from its prompt and from `plan_schedule`, because nothing fires one. A real reminder is a separate later feature with its own spec |
| 6 | `MessageBubble.tsx:109-115` | `suggested_action` renders text that does nothing | each action becomes executable, or the field is deleted along with its rendering |
| 7 | `browser_agent.py:87-113` | NL "planning" is a literal key lookup | replaced by `/api/extension/step` structured planning; the dead key map is deleted |
| 8 | `scripts/r9_*_proof.py` (3 files) | no assertions, always exit 0 | assert page-state facts and exit non-zero on failure, or delete them; wire a real Playwright browser job into CI |
| 9 | `browser-agent/tests/*` | `FakeDriver` everywhere; no test launches Chromium | add a suite that launches real Chromium (the `demo-forms:8080` container already exists) against §9 fixtures |
| 10 | `useTextToSpeech.ts:59-74` | `speak()` resolves vacuously when unsupported or volume 0 | resolve vs reject distinguishes "spoken" from "not spoken"; callers may not claim narration they didn't produce |
| 11 | `auth.py:184-193` | `DemoUser`/`get_demo_user` is a mock endpoint | deleted. The DEBUG demo identity path (`auth.py:99-147`) stays but is logged and surfaced in the UI as a shared demo identity, so per-user history and preferences aren't pretend |
| 12 | `README.md:18,69` + §2/§2C/§2D/§7 | "No mocks anywhere" and "ticket booked for real" against a self-authored page | rewrite to state what was proven, against which page, and that real-vendor booking is the extension's job in this cycle; add the §12 gap list |
| 13 | `classifier.py:181` | keyword confidence is a computed formula, not a model judgment | keep the fallback (it is flagged and useful) but mark `confidence_source: heuristic` so the UI can say "keyword match, not a model judgment" |
| 14 | `session_memory.py:35-42`, `main.py:164-166` | silent Redis→in-memory downgrade; non-HTTP URLs default `robots_ok=True` reading as "allowed" | under `ADAPTIVEAI_PRODUCTION=1`, a missing shared store fails loudly instead of pretending multi-instance state works; the robots default is logged as `not_applicable` |

Also: delete the untracked shell artifacts `backend/pytest.ini;C`,
`backend/tests;C`, `qa_out/`, `frontend/qa_out/` (redirect accidents; none are
tracked), and add ignore rules for `qa_out/` and `.mimosa/`.

## 9. Verification and testing

Acceptance is live-site evidence, so the harness produces machine-checkable
artifacts instead of prose.

### 9.1 Proof harness

Each run records: goal, then per step — snapshot-before, action, readback-after,
status — plus screenshots, the extension action log, and the narration actually
produced. Output goes to `docs/proofs/<date>-<site>/`. **Any step whose status is
not `verified` or an expected `gated`/`unsupported_frame` exits non-zero.**

Assertions are on page state, never on HTTP 200. Examples of the shape required:
"after seat selection, the snapshot contains N nodes whose accessible names match
the requested seats with `aria-checked=true`"; "after the passenger fill, the
submit button's accessible description contains the ticket count and fare";
"at the paywall the gate fired and the agent was still idle 10 s later".

### 9.2 Extension testability

- **Unit:** AccName computation under jsdom — labelled inputs, `aria-labelledby`
  chains, nested shadow trees, `fieldset`/`legend`, hidden-from-AT subtrees,
  `alt=""` vs missing `alt`.
- **Integration:** Playwright `launchPersistentContext` with `--load-extension`,
  driving the real MV3 service worker and content scripts against §9.3 fixtures.
  This is how a browser extension gets automated proof at all; without it, "tested"
  would mean "clicked around once".
- **Contract:** `/api/extension/step` request/response schema, value-redaction
  (a test that asserts a typed value cannot appear in the outgoing body), and gate
  refusal when a planner returns a gated action.

### 9.3 Offline CI fixtures (six, one per hard primitive)

Live-site-only CI is red most weeks, so a minimal set of local pages that mirror how
real sites are actually built — late-hydrating React form, div-soup with no ARIA,
open shadow DOM, cross-origin iframe, lazily-mounted modal, inline validation error
after submit. Served by the existing `demo-forms` container. Their purpose is
proving the **perception and verification primitives**, and they are never described
as evidence that booking works.

### 9.4 Speech

Replace synthesized-only STT evidence with recorded human speech, including a Hindi
and a Telugu sample and one accented English, run through
`backend/stt_wer.py`. This closes an admitted gap in `README.md:347` cheaply,
and it matters because the whole extension is voice-driven.

### 9.5 Live-site runs (the acceptance bar)

Via the connected real browser, per platform: open → search → select → fill → build
cart → gate, with artifacts. IRCTC runs use the owner's own logged-in session, are
explicitly limited to a single passenger and no booking submission, and the CAPTCHA
step is left to the human.

## 10. Permissions, security, privacy

- **Optional permissions, granted per origin on demand.** Nothing at install time;
  `<all_urls>` is never requested as a default. When the user asks to act on a
  site, the agent names the site and asks for that origin. Smaller blast radius and
  a defensible review story.
- **`chrome.debugger` is opt-in per origin** and always announced before attach.
- **CSP** locks the extension to its own bundle plus the configured backend origin;
  no remote code, which MV3 forbids anyway.
- **Vault is local and not synced**, never in `chrome.storage.sync`, with a
  one-tap wipe and an export-to-file path for the user's own data portability.
- **SSRF/URL guards stay** — `browser-agent/app/tools/url_guard.py` and
  the request interceptor at `driver.py:109-130` are real and already proven by 422s.
- **Existing JWT auth is reused**; the extension stores the token in
  `chrome.storage.local`, and `/api/extension/step` is authenticated and rate-limited
  per user, consistent with the per-IP budgets already shipped on Chromium endpoints.

## 11. Phasing (4–8 weeks)

**This spec feeds two implementation plans, not one.** Plan A is Phases 0–1
(repository integrity plus the truth pass) — it touches only existing code, and its
exit condition is a clean, honest repo. Plan B is Phases 2–6 (the extension), built
against §5's action protocol, which is the stable interface between them. Plan A
starts immediately and does not wait on Plan B; splitting them keeps a six-week
subsystem from delaying the fixes that make the current project trustworthy.

| Phase | Work | Exit condition |
|---|---|---|
| **0 · Integrity** (days 1–2) | commit the dirty tree, split into reviewable commits, delete §8 junk | `git status` clean; HEAD contains everything README cites |
| **1 · Truth pass** (week 1) | §8 items 1–4, 6–8, 10–14; README rewrite | 454+ tests still green; every deleted fake has a regression test that fails if reintroduced |
| **2 · Protocol + perception** (weeks 2–3) | perceptor, actor, gate, `await_change`; §9.2/§9.3 suites; real-Chromium browser-agent suite | fixture suite green; AccName unit coverage on the listed cases; §5 rules enforced by tests |
| **3 · Extension shell** (week 4) | MV3 wiring, offscreen mic, hotkey, vault, narration through the speech queue, `/api/extension/step` | a voice command on a live page produces a verified action and honest narration, on this machine |
| **4 · Recipes + first platform** (week 5) | generic loop, recipe format, trace memory; BookMyShow to the paywall | §9.1 artifacts green on BookMyShow; §9.5 |
| **5 · Platforms + hands** (weeks 6–7) | IRCTC and Swiggy/Zomato runs; §8 item 5 gives the three agents real effects | artifacts green per platform, walls documented per §7.1 |
| **6 · Hardening + docs** (week 8) | failure-mode narration review, real-speech STT, permissions, README + supervisor-facing limitations section | acceptance table reproducible by a stranger from the README alone |

## 12. Honest gaps this design leaves open

These stay written down rather than quietly implied as done:

- **No human NVDA pass.** Automated ARIA/keyboard contracts prove the interface, not
  the announcements. Until a blind user or an NVDA operator listens, that claim
  stays unproven — and the owner's chosen acceptance bar does not include it.
- **No completed payment.** The gate stops at the wall by decision.
- **No Android/TalkBack.** Most real Indian booking happens on phones, where an
  MV3 extension cannot exist and the agent needs an accessibility-service client.
- **IRCTC CAPTCHA is user-owned**, so a fully hands-free IRCTC session is not
  achievable here by design, and a slow agent may lose a server-side seat lock.
- **Anti-bot may block any live run**, so §9.5 artifacts are dated evidence of
  specific runs, not a standing guarantee.
- **VLM cost and latency** on canvas seat maps is unmeasured; free-tier NIM limits
  are already documented in `DEPLOY.md`.

## 13. Success criteria

Measurable, not adjectives.

1. A blind user presses one hotkey, speaks one goal, and the agent completes a
   ≥6-step task on a live BookMyShow page, with every step recorded as `verified`
   under §5 and the run stopping at a spoken gate.
2. Zero status in any log can read `success` or `completed` without an attached
   readback fact — enforced in code and by test.
3. No CAPTCHA, credential, or payment path is automated anywhere in the repo, and
   §12's limits appear in the README rather than in a footnote.
4. `git log --stat` on `main` accounts for every artifact the README cites.
5. A stranger can reproduce the acceptance table from the README alone, and the
   scripts under `scripts/` exit non-zero when the world changes.
6. The three formerly handless agents either produce a verifiable side effect or no
   longer exist, and no user-facing "Suggested: …" remains decorative.
