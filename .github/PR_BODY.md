# AdaptiveAI — Rounds 1–6: production hardening, tests, security, docs

## What this branch is
Six rounds of taking AdaptiveAI from "demo that quietly didn't work" to a system
whose every claim is backed by a command and its real output — **including its
limitations**. 12 commits off `main`.

## Fixed (each has proof in README §10 fix log)
- **Core crashes:** `/intent/classify` 500'd on every request (whole product
  dead); keyword fallback crashed too; frontend never created its session
  server-side so **every first query 404'd**; the voice pipeline returned a stale
  blob so transcription never ran; recordings self-cancelled via a layout-shift
  `mouseleave`; keyboard users could never record; reload with history crashed
  the chat; `passlib`+`bcrypt` broke auth in the deployed image.
- **Silent failures made honest:** DB-down → 503 (was 500); upstream → 502
  naming the exception; Whisper silence-hallucination → 422 via VAD; timeouts
  sized to real NIM latency; classifier-reported confidence (was hardcoded 0.85).
- **RAG actually grounds all 5 agents** (added education/document/web docs — the
  KB had none for 3 of 5 domains).
- **Feature loops closed:** preferences→policy rewrite, sources in the UI,
  history panel, account deletion, transcript download, markdown answers.
- **Deploy:** `.dockerignore` everywhere (frontend image was shipping Windows
  `node_modules`), `npm ci`, CPU-only torch (9 GB→2.5 GB), compose `env_file`
  optional, restart policies, migrations verified on a fresh DB.
- **Mock ecosystem deleted** — no fake path exists anywhere.
- **Security (R5–6):** per-user + tight auth-endpoint rate limits, server-side
  upload caps, production boot guard, JWT expiry/rotation verified live,
  dependency CVEs (cleared the 12-advisory upload parser), **sealed deep scan
  completed: 0 findings / 339 packages** (seal `sha256:69a3ea4e…`), CI `security`
  job fails if the scanner can't initialize.
- **Automation safety (R6):** OS-level input is unscoped to the foreground window
  (this is what broke the Round 5 NVDA attempt). Added `AUTOMATION_SAFETY.md` +
  isolation/focus guards to the audit scripts.

## Tests / CI
190 offline + 15 live-Postgres tests; CI runs them + a real-Postgres job +
frontend build + compose validation + the dependency scan. All green locally.

## Genuinely still open (human-only; each has a runbook — not faked)
1. **NVDA screen-reader pass** — NVDA 2026.2 installed + running, but capturing
   what it *says* needs a human ear. Fillable checklist:
   `docs/screen-reader-test-script.md`.
2. **Human-speech STT WER** — only synthesized speech measured (0–2.8%). A mic
   exists but an agent has no voice. Harness + runbook:
   `docs/real-speech-stt-runbook.md`, `backend/stt_wer.py`.
3. **Real cloud deploy + paid-NIM capacity** — no credentials here; runbooks in
   `DEPLOY.md` §6/§9. The 10–20 concurrent ceiling is a **free-tier** number.

## Note on the security gate
The lightweight pre-commit hook still reports `python_ast_unavailable` (a
degraded partial scan). The **authoritative** result is the separate sealed deep
scan above, which completed with 0 code findings. Do not read the hook's
"compatibility continue" as a clean pass — that is precisely the gap this round
closed by running the real scan and gating CI on scanner health.

## After merge
Delete the `round4-hardening` branch. Rotate the NIM key (it is in git history
from before these rounds — README §10 R4-2 context).
