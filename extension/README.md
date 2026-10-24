# AdaptiveAI browser extension

**Status: say what you want, or type it, and it plans, acts, verifies and speaks back.**

What exists: a real accessibility snapshot (accessible names computed the way the
browser computes them), an actor that fills, selects, clicks and focuses **only
with a readback that proves it landed**, a spending gate enforced in the content
script itself, a planner client that posts structure and resolves values from the
local vault, a service worker that runs the step → act → verify → narrate loop, an
offscreen document that owns the speech engine **and the microphone**, and a
transcription path that turns recorded audio into the goal. All of it is driven
end-to-end in real Chromium, including what went to the wire.

What is not real yet: nobody has completed a booking on a real site. Site knowledge
exists as data (`extension/recipes/*.json` for train, movie and food flows, plus a
verified-trace memory that only records steps the page confirmed). RailYatri's
homepage has been **read** by the loaded extension — perception, name computation
and gate identification measured on real production markup (91% agreement with
Chrome's own AX tree, `docs/proofs/2026-10-24-railyatri`) — and the recipe's step
sequence is verified against this repository's own demo page. BookMyShow blocks
automated browsers behind a challenge; IRCTC, Swiggy and Zomato refuse them
outright; no field has ever been filled and no ticket booked on any of them, and
the human-with-NVDA acceptance pass has not happened (spec §12). Do not
demonstrate this as "books tickets on BookMyShow". It has never done that.

| Piece | State |
|---|---|
| `src/ax.js` accessible-name snapshot | done, verified against Chrome's own AX tree |
| `src/actor.js` fill / select / click / focus + readback | done, 18 tests incl. a controlled-input and a stale-reference case |
| `src/content.js` bootstrap + action message surface | done, driven end-to-end from the service worker |
| `src/gate.js` spending gate, enforced in the content script | done — a gated click cannot fire, and a missing gate script refuses **all** clicks |
| `src/watch.js` `await_change` | done — a click is only `verified` when the page changed the way it was predicted to; a wrong prediction fails and reports what did happen |
| `src/vault.js` profile vault | done — values stay on the device, `availableLabels()` is the only export, and passwords/OTPs/CVV are refused for storage outright |
| `src/privacy.js` snapshot redaction | done — plus `findLeaks()`, run against a page full of real values **and** a positive control proving the check would catch one |
| `src/planner.js` step client | done — redacts before sending, resolves `profile:<label>` from the vault on the device, refuses a ref that is not in the snapshot, refuses password fields locally as well as server-side, and reports an unreachable planner instead of guessing |
| `src/runner.js` task loop | done — budgets, gate pausing, halting on a failed step, and the planner's `done`/`ask_user`/`cannot` replies, all tested with a scripted planner **and** driven against a real step endpoint |
| `src/background.js` the loop itself | done — one run at a time, live snapshot per step, confirmation that treats silence as a no, run transcript readable afterwards |
| `src/speech.js` + `offscreen.html` narration | done — the worker has no speech engine, so an offscreen document owns it; every announcement reports what the engine did, and a document that answers nothing is reported rather than assumed |
| microphone in → transcript → goal | done — `getUserMedia` + `MediaRecorder` capture in the offscreen document, uploaded as a multipart `/api/transcribe` call, and the words land in the goal field. Verified in Chromium against a fake capture device (real encoded audio, 24 KB of opus for a 2.5 s take) — including the **spoken confirmation at the spending gate**: while the loop waits on the money question, a spoken "yes"/"no" is captured, transcribed and routed to the gate, a misheard answer is asked again, and silence is still a no (3 e2e tests, real capture path). **Not** yet verified with a real microphone or a noisy room — that needs a human |
| key commands | done — `listen` hears one utterance, says it back, and runs it; `stop-talking` cuts the announcement. While the spending gate is waiting, `listen` hears the answer instead: a spoken "yes" or "no" is routed to the pending question (anything else is repeated back and asked again). **Shipped with no default key**, because a `Ctrl+Alt+*` default makes Chrome refuse to install the extension at all (measured, below): assign one at `chrome://extensions/shortcuts`. The name is `listen`, not `hold-listen` — MV3 delivers no key-release, so "hold to speak" would be a promise the platform cannot keep |
| `options.html` + `src/options.js` | done — the one place details are entered, batched into a single write, delete needs two deliberate presses |
| `popup.html` typed goal + Listen + transcript + yes/no | done — labelled input, live regions, what happened listed per step |
| `extension/recipes/*.json`, verified-trace memory | written as data — a recipe may name roles and accessible-name words, never selectors or values; it proposes, the actor still verifies, and only steps the page confirmed are remembered (as intent + role + name, never a ref). Step sequence verified against `demo/book-tickets.html` and the local test pages; **perception verified on railyatri.in's live homepage** (read-only, `docs/proofs/2026-10-24-railyatri`) — every booking flow on every real site remains in `notVerifiedOn` |

Plan: `docs/superpowers/plans/2026-10-21-plan-b-extension.md`. Design:
`docs/superpowers/specs/2026-10-21-adaptiveai-real-user-extension-design.md`.

## Pointing it at a backend

The loop posts each step to `POST /api/extension/step` on the backend
(`http://localhost:8000` unless changed). The URL and the bearer token are read from
`chrome.storage.local` (`adaptiveai_backend`, `adaptiveai_token`), so a dev box with a
different port needs one storage write, not a rebuild. With no backend running the
extension says so and does nothing — it never plans locally.

## Loading it

`chrome://extensions` → enable Developer mode → **Load unpacked** → select this
`extension/` directory. Then open any normal web page: the content script runs and
the popup reports how many controls it found, how many have no accessible name, and
how many images have no alt text.

That flow is also proven automatically in the machine's installed browser:
`python scripts/real_browser_smoke.py` loads the unpacked extension into installed
Edge (branded Chrome 137+ ignores `--load-extension`, measured), then drives the
real surfaces — options page into the vault, a typed goal through the task loop,
the recipe filling the passenger name, the gate asked and answered with the
popup's own Yes button, and the Listen button putting transcribed words in the
goal field. Latest proof: `docs/proofs/2026-10-24-real-chrome-smoke/result.json`.

## No default keyboard shortcut, on purpose

`commands` entries ship **without** `suggested_key`, because a `Ctrl+Alt+…` default
makes Chrome refuse to install the extension at all. Measured on this machine
(Chromium 156, content-script marker as the probe):

| `commands.suggested_key` | Extension loads? |
|---|---|
| `Ctrl+Alt+A` | **no** — silently refused |
| `Ctrl+Alt+S` | **no** |
| `Ctrl+Alt+Space` | **no** |
| `Ctrl+Shift+X` / `Ctrl+Shift+K` | yes |
| no `suggested_key` at all | yes |

A conflicting default shortcut is the worst possible failure mode here: nothing
appears to go wrong, the extension just never runs, and the person affected cannot
see why. Assign keys deliberately at `chrome://extensions/shortcuts`. The shortcut
that actually ships will be decided with the voice task, in the page rather than
globally, and tested against NVDA rather than assumed.

## Tests

```bash
python -m pytest extension/test -p no:warnings
```

All suites drive a **real Chromium** (122 tests): `test_ax.py` name/role/state
computation, `test_actor.py` actions and their readbacks, `test_gate.py` what gets
stopped (and what must not be), `test_watch.py` change verification,
`test_vault_privacy.py` profile storage and redaction, `test_options.py` the setup
page and what the worker reads back from it, `test_runner.py` the task loop's
control flow, `test_planner.py` what the step client puts on the wire and what it
does with a reply it did not choose, `test_voice.py` the microphone through a real
capture device into a real multipart upload plus the key command that drives the
whole loop, `test_extension_loads.py` for Chrome accepting the unpacked extension,
the worker's script actually having run, and the offscreen document answering its
own health check, and `test_task_loop.py` for the whole loop: a typed goal in a
loaded extension produces a verified DOM change, a refusal it cannot talk itself
out of, and a narration the speech engine reported back.
`test_ax.py` includes a differential test that compares every accessible name this
module produces against Chrome's own accessibility tree via CDP — Chrome is the
engine NVDA reads, so where the two disagree, this module is wrong.

Two things a future reader will otherwise rediscover the hard way:

- **`channel="chromium"` is required.** Playwright's default headless build is the
  headless *shell*, which cannot load extensions and reports no error.
- **The test server must be threaded.** Chrome fetches `/favicon.ico` concurrently;
  a plain `TCPServer` aborts it and the suite fails only when run in full.
