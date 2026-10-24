# Proof scripts

Every script here is a command you can run, with an exit code that means something.
Before 2026-10-21 three of them printed expectations (`(expected 0)`, `must be 1`) and
then exited 0 whether or not they held - which is not a proof. They now assert and exit
non-zero. `form_pipeline_proof.py`, `ui_form_fill_proof.py` and `e2e_blind_user_proof.py`
already asserted and exited non-zero; they were left alone.

| Script | What it proves | Can it fail? |
|---|---|---|
| `form_pipeline_proof.py` | discover → cache → replay → heal on a page redesign | yes (checks + `sys.exit(main())`) |
| `ui_form_fill_proof.py` | the fill dialog drives a real browser end to end | yes (`sys.exit(1 if fails else 0)`) |
| `e2e_blind_user_proof.py` | register → login → session → query → history journey | yes (`sys.exit(1 if fails else 0)`) |
| `r9_monitor_proof.py` | monitor gating, quiet-window defer, rate ceiling, stop-halts-spend | yes (16 assertions, added 2026-10-21) |
| `r9_chat_loop_proof.py` | monitoring and chat share one context; stop spends nothing more | yes (11 assertions, added 2026-10-21) |
| `r9_any_site_fill_proof.py` | guided slot-fill generalises across two different layouts | yes (5 assertions, added 2026-10-21) |
| `tts_proof.py` (frontend/) | muted speech enqueues nothing; audible speech reaches `speechSynthesis` | yes (both directions required) |
| `extension_live_site_proof.py` | the loaded extension sees and classifies real production pages, and the gate fires on real booking controls | yes (exit 3 = nothing proven, kept distinct from a failure) |
| `real_browser_smoke.py` | the unpacked extension in the machine's **installed** browser: options -> vault, typed goal -> task loop, recipe fill, gate asked and answered with the popup's Yes, Listen -> goal field | yes (exit 1 on any failed check; proof JSON written under `docs/proofs/<date>-real-chrome-smoke/`) |
| `stt_local_proof.py` | the OS voice speaks a sentence, `/api/transcribe` decodes it locally and the words come back | yes (exit 3 when this machine has no TTS voice or no local model) |
| `extension_step_live_proof.py` | a real model returns a step the device could act on, obeying the ref/value/password rules | yes (exit 3 when no NIM key is configured - which is the case on this host) |

## What these scripts are NOT evidence about

**Except `extension_live_site_proof.py`, no script here contacts a real vendor
site** - and that one only looks: nothing is clicked, filled, submitted or paid on
a live site by anything in this repository.

The other scripts target this repository's own pages - `demo/book-tickets.html`,
`demo/book-tickets-monitored.html`, `demo/gov-form-demo.html`,
`demo/monitor-stress.html` - served by the `demo-forms` container. They prove the
pipeline acts on a real Chromium DOM with real labels, real validation errors and
real readbacks. They do **not** prove booking on BookMyShow, IRCTC or Swiggy.

`extension_live_site_proof.py` is the one place a real site is read, and what it
proves is perception and gate identification on production markup - not a booking.
Operating a real site end to end is the extension's job and is not yet possible:
see the live-site table below for which vendors an automated browser can even reach.

`extension_step_live_proof.py` sends nothing to a vendor either: it calls NVIDIA's
own completion endpoint with a **structure-only** snapshot (refs, roles, accessible
names, states, value kinds) built by the proof script itself, and asserts the reply
obeys the contract. `stt_local_proof.py` sends nothing anywhere - the audio is
decoded by the local model, which is why it can be run on a machine with no API key.

The demo pages' confirmation text now says so out loud, because it previously read
"Booked 2 seats… Reference PNR101017" - indistinguishable from a completed purchase to
someone who cannot see the "demo form" line above it. The reference number is a hash of
the passenger's name.

## Live-site perception proof

`scripts/extension_live_site_proof.py` loads the unpacked extension into a real
Chromium, visits actual production pages, and asks the extension itself what it can
see. Nothing is clicked, filled or logged in to; artifacts are the **redacted**
snapshot (structure, never values) plus a screenshot, under
`docs/proofs/<date>-<site>/`.

Re-measured 2026-10-24 (vendor sites only, after the recipes feature landed):

| Site | Result | Nodes | Snapshot | Names agreeing with Chrome's own AX tree | Gate would stop |
|---|---|---|---|---|---|
| **railyatri.in** (Indian train booking) | read | 207 | 15 ms | 136/150 (91%) | **2** — "Book Train Tickets", "Book Bus Tickets" — same as 2026-10-21, reproduced |
| in.bookmyshow.com | **blocked** (challenge page) | — | — | — | — |
| irctc.co.in | **never loaded** (`ERR_HTTP2_PROTOCOL_ERROR`) | — | — | — | — |
| swiggy.com | **never loaded** (`ERR_HTTP_RESPONSE_CODE_FAILURE`) | — | — | — | — |
| zomato.com | **never loaded** (`ERR_HTTP2_PROTOCOL_ERROR`) | — | — | — | — |

The RailYatri result is now in `extension/recipes/train-booking.json`'s
`verifiedOn` - as *perception only*: the snapshot mechanism, the name computation
and the gate's booking-control identification were measured on the vendor's real
production markup. No field was filled and no booking was made; the recipe's
step sequence remains verified only against `demo/book-tickets.html`.

Measured 2026-10-21:

| Site | Result | Nodes | Snapshot | Names agreeing with Chrome's own AX tree | Gate would stop |
|---|---|---|---|---|---|
| developer.mozilla.org | read | 108 | 9 ms | 69/70 (99%) | 0 |
| MDN ARIA docs | read | 296 | 25 ms | 91/96 (95%) | 0 |
| news.ycombinator.com | read | 233 | 22 ms | 129/157 (82%) | 0 |
| **railyatri.in** (Indian train booking) | read | 207 | 15 ms | 136/150 (91%) | **2** — "Book Train Tickets", "Book Bus Tickets", reason "it reserves and usually charges" |
| in.bookmyshow.com | **blocked** | — | — | — | — |
| en.wikipedia.org | **error page** ("Wikimedia Error") | — | — | — | — |
| irctc.co.in | **never loaded** (`ERR_HTTP2_PROTOCOL_ERROR`) | — | — | — | — |
| swiggy.com | **never loaded** (`ERR_HTTP_RESPONSE_CODE_FAILURE`) | — | — | — | — |

Two things this table has to be read as saying, and not more than that:

1. **The perception layer works on real, complex, unauthored markup** - including a
   live Indian ticketing site, where the gate independently identified the two
   booking commitments by name and reason. That is the mechanism, measured.
2. **The vendor sites cannot be reached from an automated browser at all.** That is
   why the server-side design could never have booked a ticket honestly, and why
   the extension runs in the user's own session. Reproducing these four rows needs
   a real logged-in browser, which no script here can stand in for - and evading
   the walls is refused by design (spec §3).

The first run of this script **passed** against a 47-element Cloudflare interstitial,
because it asserted on structure alone and a block page has perfectly good
structure. It now detects challenge/error pages and reports them inconclusive
(exit 3), and refuses to call a run a pass when no site served a real page.

```bash
python scripts/extension_live_site_proof.py            # exit 0 verified / 1 failed / 3 nothing proven
python scripts/real_browser_smoke.py                   # installed browser, 0 failed checks = exit 0
```

`real_browser_smoke.py` needs no NIM key (the step planner is a local stub) and
no running compose stack. Branded Chrome 137+ ignores `--load-extension`, so it
tries installed Chrome first and falls back to installed Edge — the same
Chromium engine — when the content script never appears.

## Running them

```bash
docker compose up -d --build
export ADAPTIVEAI_ALLOW_LOCAL_TARGET=1     # these scripts default-deny private targets
export ADAPTIVEAI_BROWSER_URL=http://localhost:8003
export ADAPTIVEAI_BACKEND_URL=http://localhost:8000
python scripts/r9_monitor_proof.py gating          # or interruption | stress | fivemin
python scripts/r9_chat_loop_proof.py
python scripts/r9_any_site_fill_proof.py
```

`stress` and `fivemin` spend real NIM quota and take 1 and 5 minutes.

None of these scripts is wired into CI: they need a running stack, a working NIM key and
a live browser, so they belong in a release run rather than a per-push job. The automated
gate for the browser layer is `browser-agent/tests/test_real_browser.py`, which starts a
real Chromium against local fixtures in CI.

## Assertion style

Assertions are on **counters, statuses, roles and names** - never on model prose. A
NIM-generated narration sentence changes whenever the model or its temperature changes;
asserting its wording would produce a suite that fails for reasons unrelated to the
product. So the checks are structural: `narrations == 0` after a typing-only edit,
`deferred_by_quiet == 1`, `nim_after == nim_before` after a stop, `rate_blocked > 0`
under continuous churn.
