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

## What these scripts are NOT evidence about

**No real vendor site is contacted by any of them.** The targets are this repository's
own pages - `demo/book-tickets.html`, `demo/book-tickets-monitored.html`,
`demo/gov-form-demo.html`, `demo/monitor-stress.html` - served by the `demo-forms`
container. They prove the pipeline acts on a real Chromium DOM with real labels, real
validation errors and real readbacks. They do **not** prove booking on BookMyShow,
IRCTC, Swiggy or any other service, and none of those names appears anywhere in this
repository. Operating a real site is the browser extension's job
(`docs/superpowers/specs/2026-10-21-adaptiveai-real-user-extension-design.md` §7).

The demo pages' confirmation text now says so out loud, because it previously read
"Booked 2 seats… Reference PNR101017" - indistinguishable from a completed purchase to
someone who cannot see the "demo form" line above it. The reference number is a hash of
the passenger's name.

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
