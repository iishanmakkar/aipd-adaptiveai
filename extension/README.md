# AdaptiveAI browser extension

**Status: perception only. This cannot yet do anything for a user.**

What exists is the accessibility layer: a real accessible-name computation and a
snapshot of every control, state and live region on a page, loaded into Chrome as
a genuine MV3 extension. What does not exist yet is why anyone would install it —
there is **no voice input, no page acting, no backend call and no spending gate**.
Do not demonstrate this as a working assistant; it would be the same kind of claim
this repository spent a full pass removing.

| Piece | State |
|---|---|
| `src/ax.js` accessible-name snapshot | done, verified in real Chromium |
| `src/content.js` bootstrap | done, verified as a loaded content script |
| `manifest.json`, `background.js`, `popup.html` | loads and runs; popup reports real counts |
| `src/actor.js` (click / fill / select + readback) | not written |
| gate (irreversible-action confirmation) | not written |
| `await_change` verification | not written |
| profile vault | not written |
| voice in / speech out | not written |
| `POST /api/extension/step` on the backend | not written |

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

Both files drive a **real Chromium** (21 tests): `test_ax.py` for name/role/state
computation, `test_extension_loads.py` for Chrome accepting the unpacked extension.
`test_ax.py` includes a differential test that compares every accessible name this
module produces against Chrome's own accessibility tree via CDP — Chrome is the
engine NVDA reads, so where the two disagree, this module is wrong.

Two things a future reader will otherwise rediscover the hard way:

- **`channel="chromium"` is required.** Playwright's default headless build is the
  headless *shell*, which cannot load extensions and reports no error.
- **The test server must be threaded.** Chrome fetches `/favicon.ico` concurrently;
  a plain `TCPServer` aborts it and the suite fails only when run in full.
