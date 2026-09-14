# AdaptiveAI — Executive Summary

**What it is.** A context-aware accessibility assistant that helps blind and
low-vision users use forms, documents, websites and educational content
independently — it answers *what should I do here*, not just reads the page.
Four modules (React frontend · intent engine · 5 task agents + RAG · backend
orchestration/DB/policy), running as one Docker Compose stack on real
NVIDIA-NIM LLMs, FAISS retrieval and Postgres.

**How a request flows.** Voice or text → Whisper STT → intent classifier (picks
one of form/document/web/education/general) → matching agent answers **grounded
on retrieved knowledge-base documents** → an adaptive policy engine rewrites the
reply to the user's stored verbosity preference → text-to-speech back. Screenshots
are described by a vision model and used as context.

**The most defensible claim for the viva:** *every claim in this repo is backed
by a command and its real output — including the limitations.* README §11 lists
what is proven (with numbers) and what is genuinely not, each open item with a
runbook someone can execute. Nothing is asserted from code review alone.

## Proven (measured, not claimed)

- **Works end-to-end**: full stack healthy under `docker compose`; a real query
  returns a RAG-grounded answer with classifier-reported confidence and visible
  sources; voice→STT→answer loop measured at ~18s.
- **190 automated tests** (offline, no API cost) + **15 against real Postgres**
  + CI that runs them on every push.
- **Resilience**: DB down → 503 (not 500); upstream down → 502 naming the
  cause; rate limiter sheds load (429) instead of collapsing; backend killed
  mid-load → clean failures, no hangs; Postgres backup→destroy→restore returns
  exact row counts.
- **Security/privacy**: per-user rate limits + a tight auth-endpoint limit,
  server-side upload caps, account deletion that really removes rows, JWT
  expiry + rotation enforced end-to-end, a production flag that refuses to boot
  in insecure debug mode, dependency CVEs audited and the high-exposure ones
  patched.
- **Accessibility (automated)**: keyboard-only walkthrough passes — logical focus
  order, zero unlabeled controls, visible focus, Escape closes panels, polite
  live regions on new answers, all landmarks present.

## Honest gaps (each has a runbook; none faked)

1. **Human screen-reader pass.** NVDA 2026.2 is installed and running, but
   capturing what it *says* needs a human ear — `docs/screen-reader-test-script.md`.
2. **Human-speech STT accuracy.** Measured on synthesized speech (0–2.8% WER);
   real accents/noise unmeasured — `docs/real-speech-stt-runbook.md`.
3. **Real cloud deploy** and **paid-tier capacity** — no credentials here;
   runbooks in `DEPLOY.md` §6/§9. The 10–20 concurrent ceiling is a *free-tier*
   number, not the system's inherent limit.

## One-line viva answer to "could this actually ship?"

Yes for a small pilot: it runs on one VM, costs ~$5/10k queries on a paid NIM
key, has real auth + data deletion + backup, and the only blockers are the two
human-in-the-loop validations above (screen-reader and accented-speech), which
are documented procedures, not unknowns.
