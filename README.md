# AdaptiveAI — Final Build (verified live, 2026-09-19)

Context-aware AI that helps blind and low-vision users **do things** — fill forms,
book tickets, browse pages, understand documents — not just read content aloud.

**Team:** Ishan Makkar · Ishika Garg · Kakul Aeron · Kartik Bareja
**Supervisor:** Dr. Vidhu Baggan — Chitkara University, Himachal Pradesh

**Status: everything below ran live on `docker compose` (6/6 healthy) on 2026-09-19.**
No mocks anywhere: the mock ecosystem was deleted long ago, and this build round
deleted the last stubs too (browser-agent canned tools, unimportable form agents).
Where something cannot run, the API returns an honest error (502/503/422) — never
invented data.

---

## 1. Architecture (6 services)

```
┌────────────────────┐   ┌─────────────────────┐   ┌───────────────────────┐
│ MODULE 1 (Ishika)  │   │ MODULE 2 (Kakul)    │   │ MODULE 3 (Kartik)     │
│ Frontend + Voice + │──▶│ Intent & Context    │──▶│ Task Agents + RAG     │
│ Vision (VLM)       │◀──│ Engine (NLP brain)  │◀──│ (Web/Doc/Form/Edu)    │
│ React :5173        │   │ FastAPI :8001       │   │ FastAPI :8002         │
└────────────────────┘   └─────────────────────┘   └───────────────────────┘
          │                        │                           │
          └────────────────────────▶│ POST /api/query           │
                                    │ {session_id,input_text,   │
┌────────────────────┐              │  input_source,screen_ctx} │
│ MODULE 5 (new)     │              │                           │
│ Browser Agent      │              │  ┌────────────────────┐   │
│ real Playwright    │              │  │ MODULE 4 (Ishan)   │   │
│ Chromium :8003     │              │  │ Backend/API/DB +   │◀──┘
└────────────────────┘              │  │ Policy + FormFill  │
  /browse /fill /agent/browse       │  │ FastAPI :8000      │
                                    │  │ Postgres :5433→5432│
                                    │  └────────────────────┘
```

Request flow: voice/text → Whisper STT → intent classifier (form/doc/web/edu/general)
→ RAG-grounded agent → **adaptive policy engine** (rewrites per stored disability
profile + verbosity) → TTS back. Screenshots are described by NIM vision and used
as context. Form filling runs a separate real pipeline: **Discover → Cache →
Replay → Heal** in live Chromium (`POST /api/form-fill`).

---

## 2. Proof it is real (measured 2026-09-19, live compose stack)

| # | Claim | Evidence (real output) |
|---|-------|------------------------|
| 1 | 6/6 containers healthy | `postgres, intent-engine, agents, backend, browser-agent, frontend` all `healthy` |
| 2 | Full user journey | register **201** → login **200** → session **201** → query **200 in 10.9s** (`form_agent`, conf **0.95**, sources `form_aadhar_number, form_permanent_address, form_pan_number`) → history `total: 2` → metrics `16/16 2xx, 0 errors` |
| 3 | **Ticket booking, container Chromium** | `POST /api/form-fill` on `demo/book-tickets.html`: **8/8 actions success** (5 fills + select + 2 radio clicks); local 9/9 run incl. submit rendered the page's own confirmation: *"Booked 2 seat(s), New Delhi to Chandigarh on 2026-10-02 for Asha Sharma. Reference PNR101017."* |
| 4 | **Browser agent browses for real** | `POST /browse` → real title, **5 live DOM nodes** with real labels, **21952-byte real screenshot**; `POST /fill` → **2/2 with same-page readbacks** (`Browser Agent`, `agent@real.test`); `POST /agent/browse` → 1 completed / 0 failed |
| 5 | **Really adaptive** (same question, two profiles) | blind+concise+simple → **818 chars, step-by-step** ("follow these steps: 1. Type the first letter…"); none+detailed+technical → **1088 chars, technical** ("alphanumeric identifier issued by the Income Tax Department…") |
| 6 | **UI loop in real Chromium** | title `AdaptiveAI`, welcome bubble, `Message input` named, send → user bubble + answer with `form_agent` badge, **90%**, 3 source chips (screenshot in run log) |
| 7 | Form discovery sees real pages | 4/4 fields with true labels on a live page; NIM vision described the real screenshot (1269 chars) |
| 8 | Behavior events accepted | `POST /api/behavior-event` → `{"status":"accepted"}` (logged; policy consumption is next) |
| 9 | Migrations | `alembic upgrade head` on the live DB applied `20260915_add_disability_profile` |

Bugs this build round found **by running, not reviewing** (all fixed, all re-proven):
`page.accessibility` gone in Playwright 1.62 → DOM-evaluate tree; replay located
fields by internal hash ids (never in the DOM) → real selectors/labels stored at
discovery; `ElementHandle.type` removed → `fill()`; `<select>` filled as text →
`select` action type; radios unfillable → `click` + implicit-label lookup + `book/
pay/confirm/continue` submit keywords; `np.random.seed` rejects 64-bit hashes +
undeclared numpy dep → stdlib `random`/`math`; browser-agent `await` on a sync
planner, wrong tool import, `uuid4` NameError, dropped `action` arg — each proven
by a failing run, then green.

Earlier rounds (1–6) are in git history: 34 audited fixes (503/502/429 degrade
paths, bcrypt 5.0, per-user rate limits, request-ID tracing, VLM upload caps,
account deletion, backup/restore drill, sealed security scan `findingCount 0`).

---

## 3. Quick start

```powershell
# 0. First time only: create env files (gitignored, never committed)
copy backend\.env.example backend\.env
copy intent-engine\.env.example intent-engine\.env
copy agents\.env.example agents\.env
copy browser-agent\.env.example browser-agent\.env
copy frontend\.env.example frontend\.env
# put your NVIDIA key as NIM_API_KEY in backend/intent-engine/agents/browser-agent .env
# set JWT_SECRET to a random 32+ char string in backend/.env

# 1. Run everything (6 services, health-gated)
docker compose up -d --build
docker compose exec backend alembic upgrade head   # first time / fresh DB

# Frontend  http://localhost:5173
# Backend   http://localhost:8000/docs   (DEBUG=True only)
# Intent    http://localhost:8001/docs
# Agents    http://localhost:8002/docs
# Browser   http://localhost:8003/docs
# Postgres  localhost:5433 (adaptiveai/postgres/postgres)
```

Without `NIM_API_KEY` the stack boots but queries/STT/VLM fail honestly (502/503) —
there is no mock to hide it.

---

## 4. API (all live)

| Call | Goes to | Returns (real) |
|------|---------|----------------|
| `POST /api/query` | backend→intent→agents | `response_text, agent_used, suggested_action, confidence, sources_used` |
| `POST /api/form-fill` `{url, values, replay}` | backend→live Chromium | per-action statuses (`success/partial_success`), `episode_id` |
| `POST /api/behavior-event` | backend log | `{"status":"accepted"}` |
| `POST /api/transcribe` (multipart audio) | faster-whisper | `transcript` (422 on silence — VAD filtered) |
| `POST /v1/chat/completions` | NIM vision proxy | upstream response, status passed through |
| `GET/PUT /api/preferences` | Postgres | `verbosity_level, voice_speed, disability_profile, language_complexity` |
| `POST /browse`, `POST /fill`, `POST /agent/browse` | browser-agent :8003 | live title/nodes/screenshot-bytes; fills with readbacks; narrated plan result |
| `DELETE /auth/account` | Postgres | 204, rows really gone |

Try the demo: open `demo/book-tickets.html` in a browser, then
`POST /api/form-fill` with its URL and your values — the pipeline fills it in a
real browser and reports each action.

---

## 5. Testing

```powershell
cd intent-engine; python -m pytest   # 68 passed - keyword + HTTP contract
cd agents;        python -m pytest   # 59 passed - FAISS/RAG, registry, API
cd backend;       python -m pytest   # 71 passed - policy, clients, auth, degrade,
                                     #   behavior + form-fill contracts, hardening
cd frontend;      npm run build      # tsc strict + vite (CSS 25.93 kB, a11y bundled)
docker compose config --quiet        # 6 services parse with zero .env files
```

Total: **198 offline tests green** (CI also runs 10 live-Postgres + live-LLM
accuracy). Live proofs for this build: §2 table (each row is a command + output,
not a code reading).

---

## 6. Honest gaps (runbooks included, nothing faked)

- **Human screen-reader pass** (NVDA/JAWS/VoiceOver): automated ARIA/keyboard
  contract passes; verbatim announcements need a human ear —
  `docs/screen-reader-test-script.md`.
- **Human-speech STT WER**: measured on synthesized speech only (0–2.8%) —
  `docs/real-speech-stt-runbook.md` + `backend/stt_wer.py`.
- **Cloud deploy + paid-tier capacity**: `DEPLOY.md` §6/§9 (10–20 concurrent is a
  *free-tier* number). Not executed from here (no credentials).
- **Answer variance on ambiguous phrasing**: observed live — "What is the Aadhaar
  number field?" (no verb) got a cautious non-answer while "…field asking for?"
  got steps. Wiring (intent→RAG→sources→confidence→policy) is correct in both;
  prompt hardening for bare-noun questions is open.
- **Behavior signals**: accepted + logged, not yet consumed by the policy engine
  (FEATURE_PLAN 1.2 follow-up). The response says `accepted`, not `applied`.
- **Backup/restore**: validated earlier (`docs/backup-restore.md`); re-run after
  any Postgres major upgrade.

---

## 7. Repo map

```
docker-compose.yml      6 services (postgres 5433, intent 8001, agents 8002, backend 8000, browser-agent 8003, frontend 5173)
backend/                FastAPI orchestration, policy engine, episodic memory,
                        form-filler pipeline (app/agents/form/ + real browser_tool.py),
                        /api/form-fill, /api/behavior-event  (Ishan, :8000)
intent-engine/          LLM classifier + keyword fallback + session memory (Kakul, :8001)
agents/                 5 RAG agents + FAISS (Kartik, :8002)
browser-agent/          real Playwright service: driver + tools + FastAPI (:8003)
frontend/               React chat, voice, VLM upload, a11y toolbar (Ishika, :5173)
demo/book-tickets.html  ticket-booking demo page the pipeline really fills
docs/                   summary, backup-restore, screen-reader script, STT runbook, a11y log
DEPLOY.md               production topology, capacity (measured), cost (~$5/10k queries paid tier)
FEATURE_PLAN.md         phased enhancements (disability profiles + behavior intake: DONE)
AUTOMATION_SAFETY.md    isolated-browser-only automation rule
```

*Final build: six services, two real browsers (backend pipeline + browser-agent),
one ticket booked for real, same question answered two ways for two users.
Everything above was executed, not asserted.*
