# AdaptiveAI — Executive Summary

**What it is.** A context-aware accessibility assistant that helps blind and
low-vision users use forms, documents, websites and educational content
independently — it answers *what should I do here*, not just reads the page.
Six services (React frontend · intent engine · 5 task agents + RAG · backend
orchestration/DB/policy · real-Chromium browser agent · Postgres), running as
one Docker Compose stack on real NVIDIA-NIM LLMs, FAISS retrieval and Postgres.

**How a request flows.** Voice or text → Whisper STT → intent classifier (picks
one of form/document/web/education/general) → matching agent answers **grounded
on retrieved knowledge-base documents** → an adaptive policy engine rewrites the
reply to the user's stored disability profile, verbosity, and *observed
behavior* (replays simplify, skips concisely — explicit prefs always win) →
text-to-speech back. Screenshots are described by a vision model and used as
context. Forms are filled for real: discover → cache → replay → heal in live
Chromium (ticket-booking demo included).

**How a request flows.** Voice or text → Whisper STT → intent classifier (picks
one of form/document/web/education/general) → matching agent answers **grounded
on retrieved knowledge-base documents** → an adaptive policy engine rewrites the
reply to the user's stored verbosity preference → text-to-speech back. Screenshots
are described by a vision model and used as context.

**The most defensible claim for the viva:** *every claim in this repo is backed
by a command and its real output — including the limitations, and the majority
of real bugs were found by **running** the system rather than reviewing it.*
README §2 lists what is proven (with numbers) and §6 what is genuinely not,
each open item with a runbook someone can execute. Nothing is asserted from
code review alone.

## Proven (measured, not claimed)

- **Works end-to-end, on two hosts**: full stack healthy under `docker compose`
  locally AND as a clean-clone WSL2 Ubuntu deploy under the prod overlay
  (only 8000+5173 public); a real query returns a RAG-grounded answer with
  classifier-reported confidence and visible sources; remote query 26.1s vs
  10.9s local.
- **Really fills forms / browses**: ticket booking 9/9 in remote Chromium with
  the page's own confirmation; browser agent navigates + fills with readbacks.
  Round 8: "where is the submit button on this page?" now answers from the
  LIVE session's DOM (the chat holds one persistent Chromium page per chat
  session; submit-class clicks are held behind an explicit confirmation).
- **Round 9 — really watches the page**: explicit-consent monitoring of the
  live session narrates meaningful changes through the same NIM vision
  endpoint and the same policy engine as chat. Measured over a real 5-minute
  session: 164 local polls → **2 NIM calls**; a 250ms-mutation stress page
  stayed capped at 3 calls/60s (hard 20s ceiling); interruption holds
  narrations ~15s while the user talks; stop freezes NIM calls at the exact
  count. Full numbers, transcripts and seal: `docs/round9-monitoring.md`.
- **Really adaptive**: same question answered step-by-step (blind+concise,
  818 chars) vs technical (detailed, 1088 chars); observed replays/skips reshape
  subsequent answers unless the user stated otherwise (852→346 proven).
- **218 automated tests** (offline, no API cost) + **15 against real Postgres**
  + CI on every push + a fail-closed nightly live-accuracy gate.
- **Resilience**: DB down → 503 (not 500); upstream down → 502 naming the
  cause; rate limiter sheds load (429) instead of collapsing; backend killed
  mid-load → clean failures, no hangs; Postgres backup→destroy→restore returns
  exact row counts.
- **Security/privacy**: per-user rate limits + a tight auth-endpoint limit,
  SSRF allowlist + internal-only services in prod, server-side upload caps,
  account deletion that really removes rows, JWT expiry + rotation enforced
  end-to-end, a production flag that refuses to boot in insecure debug mode
  (fired live on the deploy host), dependency advisories audited (remaining:
  major-cascade-only, documented).
- **Accessibility (automated)**: keyboard-only walkthrough passes — logical focus
  order, zero unlabeled controls, visible focus, Escape closes panels, polite
  live regions on new answers, all landmarks present.

## Honest gaps (each has a runbook; none faked)

1. **Human screen-reader pass.** Checklist refreshed for the current UI (Test 7:
   sources, adaptive controls, replay) — `docs/screen-reader-test-script.md`.
2. **Human-speech STT accuracy.** Measured on synthesized speech (0–2.8% WER);
   5-minute phone runbook ready — `docs/real-speech-stt-runbook.md`.
3. **Public-cloud deploy** and **paid-tier capacity** — WSL2 Ubuntu deploy is
   done (`DEPLOY.md` §6); cloud + paid-tier retest need credentials
   (`DEPLOY.md` §6b/§9). The 10–20 concurrent ceiling is a *free-tier*
   number, not the system's inherent limit.
4. **This host fights back**: thermal hibernates under sustained build load,
   WSL2 self-stops when idle, and Windows→guest TCP is blocked here — all
   documented in `DEPLOY.md` §6c with workarounds. A cooler, unlocked machine
   (or real cloud) removes all three.

## One-line viva answer to "could this actually ship?"

Yes for a small pilot: it runs on one VM, costs ~$5/10k queries on a paid NIM
key, has real auth + data deletion + backup, and the only blockers are the two
human-in-the-loop validations above (screen-reader and accented-speech), which
are documented procedures, not unknowns.
