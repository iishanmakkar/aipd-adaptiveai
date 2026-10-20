"""Live proof: fill a real form through the FormFillDialog UI — no API shortcuts.

Logs in through the real register form, pastes the demo booking page URL into
chat, opens the Fill this form dialog the UI offers, types real values into
its inputs, presses "Fill the form", and asserts the LIVE page's own
confirmation came back ("Booked ..."). Screenshots at every step.

Run: python scripts/ui_form_fill_proof.py [base_url]
"""
import re
import secrets
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "frontend"))
from audit_login import sign_up_and_in, utf8_console  # noqa: E402

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
OUT = Path(__file__).resolve().parents[1] / "qa_out" / "ui_form_fill"
OUT.mkdir(parents=True, exist_ok=True)

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" — {detail}" if detail else ""))


# label-substring -> value to type (real passenger, real booking)
VALUES = [
    ("Passenger name", "Asha Sharma"),
    ("Email address", "asha@real.test"),
    ("From station", "New Delhi"),
    ("To station", "Chandigarh"),
    ("Travel date", "2026-10-02"),
    ("Seats", "2"),
    ("Sleeper", "on"),
]


def wait_for(page, js, timeout_s=300, poll_s=3.0):
    deadline = time.time() + timeout_s
    last = None
    while time.time() < deadline:
        last = page.evaluate(js)
        if last:
            return last
        time.sleep(poll_s)
    return last


def main():
    utf8_console()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser._isolated_launch = True
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()
        page.on("pageerror", lambda e: print("PAGEERROR:", str(e)[:200]))

        page.goto(BASE)
        email = sign_up_and_in(page, email=f"formfill-{secrets.token_hex(3)}@example.com")
        print(f"[login] {email}")

        # 1. paste the demo URL — the UI loads the live page
        page.get_by_role("textbox", name="Message input").fill(
            "http://demo-forms:8080/book-tickets.html fill this form for me")
        page.keyboard.press("Enter")
        loaded = wait_for(page, """() =>
          /interactive fields found/i.test(document.body.textContent) ? true : null""", timeout_s=180)
        check("live page loaded, fields detected", bool(loaded))
        page.screenshot(path=str(OUT / "01-page-loaded.png"))

        # 2. open the Fill this form dialog
        page.get_by_role("button", name=re.compile("Fill this form")).click()
        page.wait_for_selector('[role="dialog"][aria-label="Fill this form"]', timeout=10000)
        fields = page.evaluate("""() => {
          const d = document.querySelector('[role="dialog"][aria-label="Fill this form"]');
          return [...d.querySelectorAll('label')].map(l => {
            const input = document.getElementById(l.getAttribute('for'));
            return {label: l.textContent, id: input && input.id};
          });
        }""")
        check("dialog lists the form's real fields",
              len(fields) >= 7, f"{len(fields)} fields: {[f['label'] for f in fields][:3]}…")
        page.screenshot(path=str(OUT / "02-dialog-open.png"))

        # 3. type the real values into the dialog inputs
        filled = 0
        for needle, value in VALUES:
            match = next((f for f in fields if needle.lower() in f["label"].lower()), None)
            if not match or not match["id"]:
                check(f"field '{needle}' present in dialog", False)
                continue
            page.locator(f"[id='{match['id']}']").fill(value)
            filled += 1
        check("all values typed into the dialog", filled == len(VALUES), f"{filled}/{len(VALUES)}")
        page.screenshot(path=str(OUT / "03-values-typed.png"))

        # 4. press "Fill the form" — the real POST /api/form-fill (no replay)
        page.get_by_role("button", name="Fill the form", exact=True).click()
        result = wait_for(page, """() => {
          const r = document.querySelector('.form-fill-result');
          return r ? r.textContent : null;
        }""", timeout_s=300)
        check("pipeline returned a result", bool(result), (result or "")[:140].replace("\n", " "))
        page.screenshot(path=str(OUT / "04-fill-result.png"))

        booked = result and re.search(r"Booked .* seat", result, re.I)
        check("the LIVE page's own confirmation came back", bool(booked),
              (re.search(r"The page says:.*", result) or [""])[0][:140] if result else "")
        ok_status = result and re.search(r"success", result, re.I)
        check("per-action status is success", bool(ok_status), (result or "")[:80])

        # 5. second run through the same dialog: replay path (cache + replay)
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
        page.get_by_role("button", name=re.compile("Fill this form")).click()
        page.wait_for_selector('[role="dialog"][aria-label="Fill this form"]', timeout=10000)
        # retype (dialog state resets when closed) then Replay
        for needle, value in VALUES:
            match = next((f for f in fields if needle.lower() in f["label"].lower()), None)
            if match and match["id"]:
                page.locator(f"[id='{match['id']}']").fill(value)
        page.get_by_role("button", name=re.compile("Replay")).click()
        replay = wait_for(page, """() => {
          const r = document.querySelector('.form-fill-result');
          return r && /Status:/i.test(r.textContent) ? r.textContent : null;
        }""", timeout_s=300)
        check("replay through the dialog also books", bool(replay and re.search(r"Booked .* seat", replay, re.I)),
              (replay or "")[:140].replace("\n", " "))
        page.screenshot(path=str(OUT / "05-replay-result.png"))

        browser.close()

    fails = [n for n, ok in results if not ok]
    print(f"\n===== UI FORM-FILL: {len(results) - len(fails)}/{len(results)} checks passed =====")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
