"""Proves the TTS contract in a real browser: muted speaks nothing, audible
speech actually reaches speechSynthesis.

Why both halves: an assertion that only checks the muted path would also pass a
`speak()` that returns 'silent' unconditionally - i.e. a broken build where no
blind user ever hears anything. The loud half is what makes the quiet half
meaningful.

Drives the app's real hook (exposed only when import.meta.env.DEV, so it is dead-
code-eliminated from production builds) inside a Playwright-launched Chromium.
Input goes to the page object only - never OS-level - per AUTOMATION_SAFETY.md.

Usage:
    python frontend/tts_proof.py [url]           # default http://localhost:5173
Exit 0 only when every check passes.
"""
import os
import sys

from playwright.sync_api import sync_playwright

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from audit_login import sign_up_and_in, utf8_console  # noqa: E402

URL = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"

JS_PROBE = """async (volume) => {
  const enqueued = {calls: 0};
  if (!window.speechSynthesis) return {error: 'no speechSynthesis in this browser'};
  const original = window.speechSynthesis.speak.bind(window.speechSynthesis);
  window.speechSynthesis.speak = (u) => { enqueued.calls++; return original(u); };
  document.documentElement.style.setProperty('--voice-volume', String(volume));
  const hook = window.__adaptiveai_test_speak;
  if (typeof hook !== 'function') return {error: 'dev speak hook absent (is this a dev build?)'};
  let result;
  try {
    result = await hook('AdaptiveAI proof probe');
    await new Promise((r) => setTimeout(r, 250));  // FIFO queue drains async
  } finally {
    window.speechSynthesis.speak = original;
  }
  return {result, calls: enqueued.calls};
}"""

FAILURES = []


def check(label, cond, detail):
    if cond:
        print(f"ok: {label}")
        return
    print(f"FAIL: {label} -- {detail}")
    FAILURES.append(label)


def run():
    utf8_console()
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--autoplay-policy=no-user-gesture-required"])
        page = browser.new_page()
        page.goto(URL, wait_until="domcontentloaded")
        # The chat UI (and therefore the speech hook) only mounts behind real
        # authentication, so sign in the way a user does - same throwaway
        # account flow the other browser audits use, no back door.
        sign_up_and_in(page)

        muted = page.evaluate(JS_PROBE, 0)
        audible = page.evaluate(JS_PROBE, 1)
        browser.close()

    for name, out in (("muted", muted), ("audible", audible)):
        if out.get("error"):
            check(f"{name} probe ran", False, out["error"])
            return muted, audible
    check("muted speak returns 'silent'", muted["result"] == "silent", f"got {muted}")
    check("muted speak enqueues no utterance", muted["calls"] == 0, f"got {muted}")
    check("audible speak returns 'spoken'", audible["result"] == "spoken", f"got {audible}")
    check("audible speak reaches speechSynthesis", audible["calls"] >= 1, f"got {audible}")
    return muted, audible


if __name__ == "__main__":
    try:
        run()
    except Exception as e:
        print(f"FAIL: could not drive {URL}: {type(e).__name__}: {e}")
        raise SystemExit(1)
    if FAILURES:
        print(f"\n{len(FAILURES)} check(s) failed")
        raise SystemExit(1)
    print("\nPASS: speak() reports silence when nothing was spoken, and speaks when audible")
    raise SystemExit(0)
