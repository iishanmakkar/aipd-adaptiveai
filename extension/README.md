# AdaptiveAI browser extension

**Status: it can see a page and act on it when told. Nobody tells it yet.**

What exists: a real accessibility snapshot (accessible names computed the way the
browser computes them), an actor that fills, selects, clicks and focuses **only
with a readback that proves it landed**, and a message surface a service worker can
drive — all verified end-to-end in real Chromium. What does not exist is the reason
a user would install it: **no voice input, no planner, no spending gate, no backend
call.** Ask it for a task and nothing happens. Do not demonstrate this as an
assistant.

| Piece | State |
|---|---|
| `src/ax.js` accessible-name snapshot | done, verified against Chrome's own AX tree |
| `src/actor.js` fill / select / click / focus + readback | done, 18 tests incl. a controlled-input and a stale-reference case |
| `src/content.js` bootstrap + action message surface | done, driven end-to-end from the service worker |
| `manifest.json`, `background.js`, `popup.html` | loads and runs; popup reports real counts |
| gate (irreversible-action confirmation) | not written |
| `await_change` — proving a click changed the page as expected | not written |
| profile vault (where field values live) | not written |
| voice in / speech out | not written |
| task runner, `POST /api/extension/step` | not written |

Plan: `docs/superpowers/plans/2026-10-21-plan-b-extension.md`. Design:
`docs/superpowers/specs/2026-10-21-adaptiveai-real-user-extension-design.md`.

## Loading it

`chrome://extensions` → enable Developer mode → **Load unpacked** → select this
`extension/` directory. Then open any normal web page: the content script runs and
the popup reports how many controls it found, how many have no accessible name, and
how many images have no alt text.

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

All three files drive a **real Chromium** (41 tests): `test_ax.py` for name/role/state
computation, `test_actor.py` for actions and their readbacks, and
`test_extension_loads.py` for Chrome accepting the unpacked extension and driving an
action from the service worker through to the page.
`test_ax.py` includes a differential test that compares every accessible name this
module produces against Chrome's own accessibility tree via CDP — Chrome is the
engine NVDA reads, so where the two disagree, this module is wrong.

Two things a future reader will otherwise rediscover the hard way:

- **`channel="chromium"` is required.** Playwright's default headless build is the
  headless *shell*, which cannot load extensions and reports no error.
- **The test server must be threaded.** Chrome fetches `/favicon.ico` concurrently;
  a plain `TCPServer` aborts it and the suite fails only when run in full.
