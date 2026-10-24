# Plan B — AdaptiveAI Browser Extension Implementation Plan

> **Status 2026-10-24: archived, not a to-do list.** Every task this plan
> specifies shipped; the checkboxes below are the original working state. Run
> `python -m pytest extension/test` (140 tests) for the current proof, and see
> `extension/README.md` for what is and is not verified.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline) or superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Ship an MV3 Chrome/Edge extension that lets a blind NVDA user speak a goal and have AdaptiveAI carry it out in the user's own logged-in browser, with every action verified by readback and every irreversible action gated behind a spoken confirmation.

**Architecture:** The extension is eyes and hands only. A content script computes a real accessibility snapshot (accessible name + role per the AccName/Core-AAM spec) and executes actions through one uniform `ActionOutcome` protocol. A service worker runs the step→act→verify→narrate loop and owns the spend gate; the existing backend keeps the brain (intent, policy, agents, NIM) over a new `POST /api/extension/step`. Field **values never leave the device** — only structure does.

**Tech Stack:** Manifest V3, plain ES5-compatible classic scripts (no bundler, so "loaded unpacked" is exactly what ships), Python Playwright for real-Chromium tests on the host, FastAPI backend, faster-whisper STT via the existing `/api/transcribe`.

**Spec:** `docs/superpowers/specs/2026-10-21-adaptiveai-real-user-extension-design.md` (§4 architecture, §5 action protocol, §6 perception, §7 platform reach). Plan A (truth pass) is complete at `8651758`.

## Global Constraints

- **No `success`/`completed` without a readback fact** (spec §5.2). A status that asserts nothing is a defect.
- **No CAPTCHA solving, no credential storage, no password autofill, no agent-initiated payment** (spec §3).
- **No per-site CSS selectors, XPath or element ids in code** (spec §7). Site knowledge is data (`extension/recipes/*.json`), never imperative.
- **No OS-level input.** Playwright/page-object/CDP only (`AUTOMATION_SAFETY.md:12-21`).
- **No new runtime dependencies and no build step.** Content scripts must be loadable unpacked as written. Tests reuse the Python Playwright already installed.
- **Verification is a real Chromium.** `python -m pytest extension/test -p no:warnings` runs on this host today (measured: host Chromium 156.0.8078.4, Python Playwright working). Anything not run is reported as NOT VERIFIED.
- Commit per task; do not push.

## Task Order and Why

Tasks 1–5 are client-side and provable without the backend running, so they can be verified today. Tasks 6–9 need the stack and/or live sites.

| # | Task | Deliverable |
|---|---|---|
| 1 | Accessibility snapshot (`extension/src/ax.js`) | names, roles, states, bounds, value kinds, hidden exclusion — real-Chromium tests |
| 2 | Actor + `ActionOutcome` | focus/click/fill/select with readback, React-safe insertion, stale-ref detection |
| 3 | Gate | deterministic irreversible-name predicate the planner cannot override |
| 4 | `await_change` | predicted-change verification: url / node / state / title / announcement |
| 5 | Profile vault + redaction | labels+values local only; snapshot redaction proving values never leave |
| 6 | `POST /api/extension/step` | structure-in / action-out contract, authenticated, rate-limited |
| 7 | MV3 shell | manifest, service worker loop, hotkey, popup, offscreen mic, narration |
| 8 | Recipes + trace memory | `movie-booking`, `train-booking`, `food-order` as data; traces bias, never skip |
| 9 | Live-site proof harness | BookMyShow / IRCTC / Swiggy to the paywall with artifacts, per spec §9 |

## Deferred / Open

- `ui_adjuster` and `profile_updater` real effects (Plan A §8 item 5) land with task 7's executor.
- Human NVDA pass, completed payment, Android/TalkBack remain out of scope (spec §12).
