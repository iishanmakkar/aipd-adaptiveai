# NVDA Screen-Reader Test Script — AdaptiveAI

**Why this file exists.** NVDA 2026.2 was installed and confirmed running on the
Windows host (processes `nvda`/`nvda_noUIAccess`, audio devices present, welcome
dialog read). But capturing what NVDA *actually says* requires a human ear in a
clean session — driving it by blind keystroke automation lands on whatever window
has focus (an editor, a browser tab) and is disruptive. This script is the
precise, ten-minute procedure for a person to run that capture, with the expected
NVDA output at every step so deviations are obvious.

## Setup (once)

1. Start NVDA (system tray NVDA icon, or run NVDA). Confirm it speaks.
2. Open **Edge or Chrome** (NVDA's browser support is far better than Firefox
   here) to `http://localhost:5173`.
3. Make sure the stack is up: `docker compose up -d` (see DEPLOY.md).
4. NVDA key in this script = **Caps Lock** (confirmed enabled in NVDA's welcome
   dialog). `NVDA+Space`/`NVDA+N` = Caps Lock + that key.

Read-aloud conventions below are what NVDA *should* say. If it says less,
mislabels something, or goes silent where text is expected, that is a finding —
note the step number and what you heard.

## Test 1 — First load and landmarks (no mouse)

| # | Action | Expected NVDA output |
|---|--------|----------------------|
| 1.1 | Page loads, focus in the document | "AdaptiveAI, heading level 1" then the tagline |
| 1.2 | Press `H` (jump to next heading) | "AdaptiveAI, heading level 1" (only one H1 — check it is not skipped) |
| 1.3 | Press `N` (next landmark) repeatedly | cycles: "banner", "main", "content information" — **all three must be announced** |
| 1.4 | Press `Tab` from the top | lands on "Open session history button", then "Download conversation transcript button", "Show accessibility settings button", "Start new session button" |
| 1.5 | Keep `Tab`-ing into the footer | "Upload screenshot button", "Message input edit", "Record voice message button" |
| 1.6 | On the welcome bubble, press `B` (next region) then arrows | the assistant message is reachable and reads its full text |

**Pass:** every control names itself (no "button" with no label, no raw "edit"
without a name). **The message input must announce as "Message input" — a
placeholder alone is NOT an accessible name; if NVDA says just "edit", that is a
real WCAG 3.3.2 failure to fix.**

## Test 2 — Does a new answer announce itself automatically? (critical)

| # | Action | Expected NVDA output |
|---|--------|----------------------|
| 2.1 | Focus the message input, type "What is the Aadhaar number field?", press Enter | "You said: What is the Aadhaar number field?" (user bubble, right-aligned) |
| 2.2 | Wait for the answer (10–90s) **without touching the keyboard** | NVDA should announce the assistant's reply via the polite live region — you should HEAR the answer appear without navigating to it |
| 2.3 | Also note | the "Thinking…" status pill should announce as a status ("Thinking"), then the answer |

**This is the single most important check.** If NVDA stays silent after 2.2 and
you only hear the answer by manually tabbing to it, the live region is not
working for screen-reader users and the app is not actually usable hands-free —
that is a blocking finding, not a nitpick.

## Test 3 — Voice recording announcements

| # | Action | Expected NVDA output |
|---|--------|----------------------|
| 3.1 | Focus the mic button, press `Space` | "Recording voice message, button, pressed" and the usage hint ("…press Enter or Space to start recording and press it again to stop and send") |
| 3.2 | Watch the timer | the "0:01 / Release to send" indicator should be announced as it appears (it has `role=status`) |
| 3.3 | Press `Space` again | recording stops; if STT returns text, the transcript is submitted and Test 2's announcement applies |
| 3.4 | If transcription fails (no mic / silence) | "Transcription failed. Please try again or type your message." should be announced (it is a polite live region + `role=alert` on the mic error) |

## Test 4 — Preferences actually take effect

| # | Action | Expected |
|---|--------|----------|
| 4.1 | `Tab` to "Show accessibility settings", Enter | panel opens; NVDA says "Accessibility settings, region" |
| 4.2 | `Tab` to "Select font size", use arrow keys | each change announces ("Large 1.25rem") |
| 4.3 | `Tab` to "Enable high contrast mode", Space | announces "checked"; the whole UI flips to high contrast (verify visually) |
| 4.4 | `Tab` to "Select answer detail level", choose Concise | announces the selection |
| 4.5 | Ask a question (Test 2) | the answer should come back noticeably shorter (the policy engine rewrites for "concise") — this proves the preference reached the backend |
| 4.6 | Press `Escape` | panel closes and focus returns to the toggle button |

## Test 5 — History and account deletion

| # | Action | Expected |
|---|--------|----------|
| 5.1 | `Tab` to "Open session history", Enter | "Session history, dialog" with a list of past sessions, each announcing its date and message count; the current one says "Current" |
| 5.2 | Arrow to a past session, Enter | dialog closes, that session's messages load and are announced |
| 5.3 | Press `Escape` | history closes |
| 5.4 | Ask a question, then `Tab` to its "Copy answer to clipboard" button, Enter | announces "Answer copied to clipboard" |

## Test 6 — Error surfaces are announced

| # | Force it | Expected |
|---|----------|----------|
| 6.1 | Stop the backend (`docker compose stop backend`), send a message | the assistant bubble should say and **speak** an error ("Sorry, I encountered an error…") — not silent failure |
| 6.2 | Upload a non-image file via the dropzone | the upload error ("…must be an image…") is announced (`role=alert`) |

## Test 7 — New since Round 5: sources, adaptive controls, replay/skip (critical)

Round 7 added RAG source chips, disability-profile/complexity/verbosity selects,
a per-answer Replay button, and behavior-driven adaptation. None of these existed
when Tests 1–6 were written.

| # | Action | Expected |
|---|--------|----------|
| 7.1 | Ask a question, wait for the answer | below the answer, NVDA reads "Knowledge sources used" followed by chips (`form_aadhar_number`, …) — each chip reachable by Tab |
| 7.2 | Same answer | NVDA announces the agent badge ("Handled by form_agent") and confidence ("Confidence 90%") |
| 7.3 | Open accessibility settings | three NEW selects vs Round 5: "Select disability profile for adapted responses", "Select language complexity level", "Select answer detail level" — each announces its value on change |
| 7.4 | Set profile Blind + detail Concise, ask a question | the answer comes back as numbered steps AND noticeably short (proves profile+verbosity reached the backend policy engine) |
| 7.5 | On any assistant answer, Tab to "Listen to this answer again", Enter | the answer is spoken again (Replay); NVDA announces the button by its full name, not just "button" |
| 7.6 | While an answer is being spoken, Tab to the stop-speaking control, Enter | speech stops immediately; this is logged as a skip (answers get shorter when skipped repeatedly — backend Rule 5) |
| 7.7 | Stop the backend (`docker compose stop backend`), send a message | error bubble is spoken ("Sorry, I encountered an error…"), not silence |

**Form-fill honesty note (for the examiner):** autonomous form filling has NO chat
UI trigger — it is `POST /api/form-fill` plus the runnable demo page
`demo/book-tickets.html` (open it directly in Edge/Chrome: full keyboard flow,
real confirmation region with `role=status`). Do NOT mark "form-fill initiation"
as a UI pass; verify the demo page reads correctly instead (labels, required
announcement, confirmation text).

## Record results

For each numbered step, log: **Pass / Fail + what NVDA actually said.** Anything
that is silent, mislabeled, or requires the mouse is a defect. Send the log to be
triaged — the fixes go in the same place as Rounds 1–4 (README §10 fix log), and
the automated `frontend/a11y_audit.py` should be extended to cover any new
finding so it cannot regress.

## What this script checks that the automated audit cannot

`a11y_audit.py` proves the ARIA/keyboard *contract* (roles, names, focus order,
live-region presence). Only a human with NVDA confirms the *experience*: that
announcements are actually spoken, in a sensible order, without the user hunting.
Tests 2 and 3 are where a real problem would most likely hide.

---

## Printable pass/fail checklist

Run with NVDA active, Edge/Chrome on `http://localhost:5173`. Mark each row
**P** (pass), **F** (fail), or **N/A**, and write what you actually heard in the
last column. Return this filled table — it is the deliverable, not verbal notes.

| Step | Check | P / F / N/A | What NVDA actually said (note deviations) |
|------|-------|:-----------:|-------------------------------------------|
| 1.1 | H1 "AdaptiveAI" announced on load | | |
| 1.2 | `H` cycles headings, no skip | | |
| 1.3 | `N` announces banner / main / contentinfo | | |
| 1.4 | Header buttons all named (history/download/settings/new) | | |
| 1.5 | Footer: upload / "Message input" / mic named | | |
| 1.6 | Welcome bubble reachable + full text read | | |
| **2.1** | User message echoed ("You said: …") | | |
| **2.2** | **Answer announced WITHOUT navigating to it (live region)** | | |
| 2.3 | "Thinking…" status announced | | |
| 3.1 | Mic Space → "pressed" + usage hint | | |
| 3.2 | Recording timer announced | | |
| 3.3 | Second Space stops + sends | | |
| 3.4 | STT failure announced (not silence) | | |
| 4.1 | Panel opens, region announced | | |
| 4.2 | Font-size change announces value | | |
| 4.3 | High-contrast toggle announces "checked" + visual flip | | |
| 4.4 | Answer-detail select announces | | |
| 4.5 | Concise preference → next answer shorter (reaches backend) | | |
| 4.6 | Escape closes panel, focus returns | | |
| 5.1 | History dialog + per-session date/count | | |
| 5.2 | Selecting a session loads + announces its messages | | |
| 5.3 | Escape closes history | | |
| 5.4 | Copy button announces "copied" | | |
| 6.1 | Backend down → error spoken (not silence) | | |
| 6.2 | Non-image upload → error announced | | |
| **7.1** | **Source chips announced + reachable** | | |
| 7.2 | Agent badge + confidence announced | | |
| 7.3 | Profile / complexity / detail selects named + announce | | |
| 7.4 | Blind+Concise → steps AND short (reaches backend) | | |
| 7.5 | "Listen to this answer again" replays | | |
| 7.6 | Stop-speaking stops + is named | | |
| 7.7 | Backend down → error spoken (re-check post-R7) | | |
| — | demo/book-tickets.html reads correctly (labels/confirmation) | | |

**Overall verdict:** ☐ Usable with a screen reader  ☐ Usable with noted issues
(list below)  ☐ Blocking issues found

**Blocking issues (fix before shipping):**
1. ______________________________
2. ______________________________
3. ______________________________

