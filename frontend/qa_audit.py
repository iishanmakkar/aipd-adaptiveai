"""Visual QA driver for the AdaptiveAI frontend.

Captures screenshots at each interaction step and records every console
message / page error, so styling regressions and runtime exceptions both show
up. Run: python qa_audit.py <base_url> <out_dir>
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5174"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "/tmp/qa")
OUT.mkdir(parents=True, exist_ok=True)

issues: list[str] = []
console_log: list[dict] = []


def shot(page, name):
    path = OUT / f"{name}.png"
    page.screenshot(path=str(path), full_page=False)
    print(f"[shot] {path}")
    return str(path)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                # headless has no audio hardware: fake device lets MediaRecorder
                # genuinely record, so the mic path is really exercised
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900},
                                      permissions=["microphone"])
        page = context.new_page()

        page.on("console", lambda m: console_log.append(
            {"type": m.type, "text": m.text[:300]}))
        page.on("pageerror", lambda e: issues.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: issues.append(
            f"request failed: {r.url} -> {r.failure}"))

        t0 = time.time()
        page.goto(BASE, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_load_state("networkidle", timeout=15000)
        print(f"[load] {time.time() - t0:.1f}s")
        shot(page, "01-initial")

        # --- structural expectations -------------------------------------
        checks = {
            "h1 title": page.get_by_role("heading", name="AdaptiveAI"),
            "message input": page.get_by_role("textbox"),
            "application container": page.get_by_role("application"),
            "chat log": page.get_by_role("log"),
        }
        for name, loc in checks.items():
            n = loc.count()
            print(f"[check] {name}: {n}")
            if n == 0:
                issues.append(f"MISSING: {name}")

        welcome = page.get_by_role("log").inner_text()
        print(f"[welcome] {welcome[:120]!r}")
        if "Welcome" not in welcome:
            issues.append("welcome message missing")

        # --- accessibility toolbar ---------------------------------------
        page.get_by_role("button", name="Show accessibility settings").click()
        page.wait_for_timeout(400)
        shot(page, "02-toolbar-open")

        # high contrast (real accessible name from AccessibilityToolbar.tsx)
        before = page.evaluate("document.documentElement.className")
        page.get_by_role("button", name="Enable high contrast mode").click()
        page.wait_for_timeout(500)
        after = page.evaluate("document.documentElement.className")
        print(f"[contrast] html class: {before!r} -> {after!r}")
        if "high-contrast" not in after:
            issues.append(f"high-contrast toggle did not change html class ({before!r} -> {after!r})")
        shot(page, "03-high-contrast")

        # font size is a <select>, cycle to Large
        size_select = page.get_by_role("combobox", name="Select font size")
        if size_select.count() == 0:
            issues.append("font size select missing from toolbar")
        else:
            size_select.select_option("large")
            page.wait_for_timeout(400)
            shot(page, "04-large-font")
            size_select.select_option("medium")

        page.get_by_role("button", name="Reset accessibility settings to defaults").click()
        page.wait_for_timeout(300)

        # --- close toolbar (its name flips to "Hide..." while open) ---------
        page.get_by_role("button", name="Hide accessibility settings").click()
        page.wait_for_timeout(300)
        shot(page, "05-back-to-chat")

        # --- send a real query ---------------------------------------------
        page.wait_for_function(
            "document.querySelectorAll('.message-bubble').length > 0", timeout=20000)
        box = page.get_by_role("textbox")
        box.fill("What does the permanent address field mean?")
        shot(page, "06-typed")
        page.get_by_role("button", name="Send message").click()
        page.wait_for_timeout(1500)
        shot(page, "07-thinking")
        try:
            # Wait for a SECOND settled assistant bubble (welcome + answer) -
            # the user's own echo contains the same words, so text matching
            # false-positived in earlier rounds.
            page.wait_for_function(
                """() => [...document.querySelectorAll('.message-bubble.assistant')]
                       .filter(b => !b.classList.contains('loading') && b.innerText.trim()).length >= 2""",
                timeout=200000)
            page.wait_for_timeout(800)
            shot(page, "08-answer")
            answer_text = page.get_by_role("log").inner_text()
            print(f"[answer] present, log length {len(answer_text)}")
            if "error" in answer_text.lower():
                issues.append(f"assistant answered with an error: {answer_text[-200:]!r}")
        except Exception as e:
            issues.append(f"query never produced an answer: {str(e)[:200]}")
            shot(page, "08-answer-timeout")

        # --- mic: hold-to-record via mouse, and keyboard toggle --------------
        mic = page.get_by_role("button", name="Record voice message")
        if mic.count() == 0:
            issues.append("mic button not found by accessible name")
        else:
            # mouse hold: down, hold 2.6s (past the 150ms press threshold and
            # past the point where the layout-shift bug used to self-cancel)
            mic.hover()
            page.mouse.down()
            page.wait_for_timeout(1200)
            still = page.get_by_role("button", name="Stop recording and send").count()
            page.wait_for_timeout(1400)
            still_late = page.get_by_role("button", name="Stop recording and send").count()
            print(f"[mic] recording at 1.2s: {bool(still)}, still at 2.6s: {bool(still_late)}")
            if not still:
                issues.append("holding the mic did not start recording")
            elif not still_late:
                issues.append("RECORDING SELF-CANCELLED mid-hold (layout-shift mouseleave)")
            shot(page, "09-mic-recording")
            page.mouse.up()
            page.wait_for_timeout(4000)
            log_after_mic = page.get_by_role("log").inner_text()
            print(f"[mic] after release, log tail: {log_after_mic[-120:]!r}")

            # keyboard: Space must toggle - start on first press, stop+send on
            # the second. Wait until the mic is enabled again first: while a
            # transcription is in flight the button is legitimately disabled,
            # and a disabled button swallows key events (focus lands on BODY).
            mic = page.get_by_role("button", name="Record voice message")
            mic.wait_for(state="visible", timeout=10000)
            page.wait_for_function(
                """() => { const b = document.querySelector('.mic-button');
                           return b && !b.disabled; }""", timeout=60000)
            mic.focus()
            page.keyboard.press("Space")
            page.wait_for_timeout(1500)
            kb_recording = page.get_by_role("button", name="Stop recording and send").count()
            print(f"[mic] keyboard Space started recording: {bool(kb_recording)}")
            if not kb_recording:
                issues.append("KEYBOARD A11Y: Space/Enter cannot start recording")
            else:
                shot(page, "10-mic-keyboard")
                page.keyboard.press("Space")  # stop + send
                page.wait_for_timeout(4000)

        # --- session persistence across reload -------------------------------
        page.reload(wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot(page, "11-after-reload")
        log_after_reload = page.get_by_role("log").inner_text()
        print(f"[reload] history restored: {len(log_after_reload)} chars, "
              f"welcome-still-first: {'Welcome' in log_after_reload}")

        browser.close()

    print("\n===== CONSOLE (" + str(len(console_log)) + " entries) =====")
    for m in console_log:
        if m["type"] in ("error", "warning"):
            print(f"[{m['type']}] {m['text']}")

    print("\n===== ISSUES (" + str(len(issues)) + ") =====")
    for i in issues:
        print(" -", i)

    (OUT / "report.json").write_text(json.dumps(
        {"issues": issues, "console": console_log}, indent=2))


if __name__ == "__main__":
    main()
