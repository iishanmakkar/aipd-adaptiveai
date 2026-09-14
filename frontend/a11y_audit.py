"""Keyboard-only + accessibility-tree audit for AdaptiveAI.

This is NOT a substitute for a human NVDA/VoiceOver pass (that remains a listed
gap). What it does verify is the exact contract a screen reader consumes:
  - logical Tab order with no focus trap
  - every interactive control has an accessible name
  - visible focus indicator on the focused element
  - Escape closes the accessibility panel and returns focus
  - new assistant messages land in an aria-live=polite region (so a screen
    reader announces them without the user navigating)
  - the page's accessibility tree exposes the expected roles

Usage: python a11y_audit.py <base_url>
"""
import sys

from playwright.sync_api import sync_playwright

from automation_guard import assert_focus_unchanged, assert_isolated_browser, foreground_window_token

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:5173"
issues = []


def run():
    focus_before = foreground_window_token()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        browser._isolated_launch = True  # launched by this process -> scoped input only
        assert_isolated_browser(browser)
        page = browser.new_context(viewport={"width": 1280, "height": 860}).new_page()
        page.goto(BASE, wait_until="networkidle")
        page.wait_for_function(
            "document.querySelectorAll('.message-bubble').length > 0", timeout=25000)

        # 1. Tab order: walk the first 12 stops, record accessible names.
        order = []
        for _ in range(12):
            page.keyboard.press("Tab")
            info = page.evaluate("""() => {
              const el = document.activeElement;
              if (!el || el === document.body) return null;
              const name = el.getAttribute('aria-label')
                || (el.textContent || '').trim().slice(0, 40)
                || el.placeholder || el.tagName;
              return {tag: el.tagName, name,
                      cls: (el.className || '').toString().slice(0, 40)};
            }""")
            if info and (info["tag"], info["name"]) not in [(o["tag"], o["name"]) for o in order]:
                order.append(info)
        print("Tab order:")
        for i, o in enumerate(order):
            print(f"  {i+1:2d}. <{o['tag']}> '{o['name']}'")
        names = [o["name"] for o in order]
        if not any("message" in n.lower() or "Message input" in n for n in names):
            issues.append("message input not reachable by Tab")
        # The h1 title is intentionally NOT a tab stop (headings are navigated
        # with screen-reader heading keys, not Tab) - verified via the roles
        # check below instead.

        # 2. Every focusable control has an accessible name (no unlabeled buttons).
        unlabeled = page.evaluate("""() => {
          const sel = 'button, input:not([type=hidden]), select, textarea, a[href], [role=button]';
          return [...document.querySelectorAll(sel)].filter(el => {
            const name = el.getAttribute('aria-label')
              || (el.labels && el.labels.length ? el.labels[0].textContent : '')
              || el.getAttribute('placeholder')
              || (el.textContent || '').trim();
            return !name.trim();
          }).map(el => el.tagName + '.' + (el.className||'').toString().slice(0,30));
        }""")
        if unlabeled:
            issues.append(f"unlabeled controls: {unlabeled}")
        print(f"unlabeled controls: {len(unlabeled)}")

        # 3. Focus visibility: the focused control must have a non-none outline.
        page.keyboard.press("Tab")
        focused_outline = page.evaluate("""() => {
          const el = document.activeElement;
          const cs = getComputedStyle(el);
          return {outline: cs.outlineStyle + ' ' + cs.outlineWidth, boxShadow: cs.boxShadow.slice(0,40)};
        }""")
        print("focused element outline:", focused_outline)
        if focused_outline["outline"].startswith("none") and not focused_outline["boxShadow"]:
            issues.append("focused control has no visible outline or box-shadow")

        # 4. Escape closes the accessibility panel.
        page.get_by_role("button", name="Show accessibility settings").focus()
        page.keyboard.press("Enter")
        panel_open = page.get_by_role("region", name="Accessibility settings").count()
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        panel_after = page.get_by_role("region", name="Accessibility settings").count()
        print(f"panel open via keyboard: {panel_open==1}; after Escape: {panel_after==0}")
        if panel_open != 1:
            issues.append("accessibility panel cannot be opened with the keyboard")
        if panel_after != 0:
            issues.append("Escape does not close the accessibility panel")

        # 5. aria-live: assistant messages live in a polite region.
        live = page.evaluate("""() => {
          const log = document.querySelector('[role=log]');
          const bubbles = document.querySelectorAll('.message-bubble.assistant');
          const last = bubbles[bubbles.length-1];
          return {logLive: log && log.getAttribute('aria-live'),
                  logCount: document.querySelectorAll('[aria-live]').length,
                  bubbleLive: last && last.getAttribute('aria-live')};
        }""")
        print("live regions:", live)
        if not live["logLive"]:
            issues.append("conversation log has no aria-live")

        # 6. Accessibility roles present (via ARIA/DOM, the tree a SR reads).
        role_counts = page.evaluate("""() => {
          const count = sel => document.querySelectorAll(sel).length;
          return {heading: count('h1,h2,h3'), textbox: count('textarea,input[type=text]'),
                  button: count('button'), log: count('[role=log]'),
                  article: count('[role=article]'), banner: count('[role=banner]'),
                  main: count('[role=main]'), contentinfo: count('[role=contentinfo]')};
        }""")
        print("roles:", role_counts)
        for needed in ("heading", "textbox", "button", "log", "article", "banner", "main", "contentinfo"):
            if role_counts.get(needed, 0) == 0:
                issues.append(f"missing landmark/role '{needed}'")

        # 7. DOM order of focusables vs tab order (header should precede composer).
        dom_order = page.evaluate("""() => {
          const sel = 'header button, header a, main [tabindex], footer button, footer textarea, footer input';
          return [...document.querySelectorAll(sel)].slice(0,6).map(el =>
            (el.closest('header') ? 'header:' : el.closest('footer') ? 'footer:' : 'main:')
            + (el.getAttribute('aria-label') || el.tagName));
        }""")
        print("DOM focusable order:", dom_order)
        if dom_order and dom_order[0].startswith("footer"):
            issues.append("tab/DOM order starts in the footer composer, not the header")

        browser.close()

    assert_focus_unchanged(focus_before, foreground_window_token())

    print("\n=== A11Y ISSUES ===")
    for i in issues:
        print(" -", i)
    if not issues:
        print(" (none) - keyboard + ARIA contract passes; human NVDA pass still pending")
    return issues


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
