# Automation Safety — input isolation

**Why this exists.** In Round 5 an attempt to drive NVDA used OS-level input
injection (the `computer-use` tool's `key`/`left_click`). That API sends input to
**whatever window currently has OS focus** — it has no notion of "the window I
launched." The keystrokes landed on the operator's live desktop (an editor, a
browser tab with their own work), not a contained target. It was stopped, but the
gap is structural: nothing guaranteed the input was scoped.

## The rule

**Any script in this repo that drives a browser or the accessibility tree must
use an isolated, self-launched target — never OS-level input to the live
session.**

- ✅ **Allowed:** Playwright/CDP driving a browser it launched itself
  (`p.chromium.launch(headless=True)`), or a browser connected via an explicit
  remote-debugging endpoint to a *dedicated* profile. Input goes to the page
  object, which cannot reach other windows.
- ❌ **Forbidden for automation:** OS-level synthetic input (computer-use
  `key`/`click`, `pyautogui`, `pynput`, `SendKeys`, `ctypes` user32) targeting
  the desktop. It is unscoped by construction and will hit the operator's
  foreground app.

This is why `qa_audit.py` and `a11y_audit.py` are safe: they only ever call
`page.*` on a headless browser they started. The NVDA attempt was unsafe because
it used a *different* tool that is unscoped — and that is exactly the class of
mistake this rule prevents.

## Screen-reader testing is explicitly human-only

NVDA/JAWS/VoiceOver cannot be driven by OS-level input from an agent against a
live desktop — see the rule above. The screen-reader pass is a **human**
procedure (`docs/screen-reader-test-script.md`). An automated ARIA/keyboard audit
(`a11y_audit.py`) is the automated substitute for the *contract*; it is not a
substitute for a human listening to real announcements.

## Enforcement in code

`qa_audit.py` and `a11y_audit.py` call `assert_isolated_browser(browser)` at
startup, which fails if the browser is not a Playwright-launched isolated
instance, and `assert_focus_unchanged(...)` around the run to prove the
automation did not steal OS focus. If either check cannot confirm isolation, the
script aborts rather than proceeding against an unscoped target.

## For any future automation added here

1. Launch your own browser/context; never assume the current foreground window
   is yours.
2. Send input to the page/element, not to screen coordinates or the OS.
3. If a task genuinely needs OS-level input (rare), run it in a **dedicated
   headless display / VM session**, never the operator's interactive one, and
   document that requirement in the PR.
