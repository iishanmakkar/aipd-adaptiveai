# Accessibility Test Log — Round 4

**Method and honest scope.** This log records the automated keyboard + accessibility-tree
pass (`frontend/a11y_audit.py`, Playwright + headless Chromium). It is **not** a
human screen-reader session. NVDA is not installed on this machine and VoiceOver is
macOS-only; installing assistive technology is the owner's decision, not an agent's.
The audit verifies the exact contract a screen reader consumes (roles, names, focus,
live regions) — the strongest evidence obtainable without driving real AT. The human
NVDA pass remains an open item in README §11.

Run against the deployed stack at `http://localhost:5173`.

---

## Flow 1 — Keyboard-only navigation (no mouse)

`Tab` walked the focusable elements. Result (DOM order, authoritative):

1. Header — Open session history
2. Header — Download conversation transcript
3. Header — Show accessibility settings
4. Header — Start new session
5. Main — Copy answer (per assistant message)
6. Main — suggestion chips (one per agent domain)
7. Footer — Upload screenshot
8. Footer — Message input
9. Footer — Record voice message

**Finding:** order is logical (header → main → footer). No focus trap observed;
every control reachable and operable by keyboard.

## Flow 2 — Accessible names

`0` unlabeled controls (every button/input/select/textarea has an aria-label,
associated label, placeholder, or text content). Mic button carries
`aria-describedby` usage hints for both mouse-hold and keyboard-toggle.

## Flow 3 — Focus visibility

Focused element computed style: `outline: solid 2px`. Keyboard users can see
where focus is (WCAG 2.4.7).

## Flow 4 — Keyboard operation of controls

- Accessibility panel opens via `Enter` on its toggle.
- **BUG FOUND:** `Escape` did **not** close the panel (only the history panel had
  an Escape handler). Fixed in `ChatInterface.tsx`; re-tested → "panel open via
  keyboard: True; after Escape: True".
- Mic records via `Space`/`Enter` as a toggle (fixed in Round 3 — keyboard hold
  could never satisfy the 150ms hold timer).

## Flow 5 — Live regions / announcements

- Conversation log: `role=log` + `aria-live=polite`.
- Each assistant bubble: `aria-live=polite`.
- 2 live regions present. A new assistant answer changes a polite live region, so
  a screen reader announces it without the user navigating — this is the mechanism,
  verified structurally; the *audio* of a reader announcing it is what the human
  pass would confirm.

## Flow 6 — Landmarks / roles (the tree a reader reads)

`heading:1, banner:1, main:1, contentinfo:1, log:1, article:1, textbox:1, button:11`.
All expected landmarks present and singular.

---

## Final audit result

```
=== A11Y ISSUES ===
 (none) - keyboard + ARIA contract passes; human NVDA pass still pending
```

## What was fixed this round (a11y-relevant)

1. Escape now closes the accessibility settings panel.
2. (Round 3, re-verified here) hold-to-record no longer self-cancels; keyboard
   Space/Enter toggles recording — the single most important control for a
   low-vision user who cannot use a mouse.

## Still required before calling this "screen-reader tested"

- A sighted developer and, ideally, a blind user run the load → ask → answer →
  change preference → review history → delete-account flow in NVDA (Windows) or
  VoiceOver (macOS), confirming announcements and that nothing is read
  confusingly. Log findings here.
