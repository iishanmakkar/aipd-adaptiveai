# Contributing / New-developer guide

Everything a new developer needs to run, test and extend this project — with
the **measured** state as of 2026-10-24, not aspirational claims. If a command
here fails, that is a bug in this file; fix the file with the PR.

- Architecture and proof tables: [`README.md`](README.md)
- What is verified where: [`docs/verification-baseline.md`](docs/verification-baseline.md)
- Module docs: [`backend/`](backend/README.md), [`intent-engine/`](intent-engine/README.md),
  [`agents/`](agents/README.md), [`browser-agent/`](browser-agent/README.md),
  [`frontend/`](frontend/README.md), [`extension/`](extension/README.md)
- Automation safety rule (read before writing any browser script):
  [`AUTOMATION_SAFETY.md`](AUTOMATION_SAFETY.md)

---

## 1. What this is (30 seconds)

Seven services in one Docker Compose stack:

| Service | Port | What it does | Code owner (historical) |
|---|---|---|---|
| frontend | 5173 | React UI, voice, VLM upload, caregiver view | Ishika |
| backend | 8000 | orchestration, auth, DB, policy, STT, VLM proxy, form-fill, extension planner | Ishan |
| intent-engine | 8001 | 13-intent classifier + session memory | Kakul |
| agents | 8002 | 11 RAG agents + orchestrator | Kartik |
| browser-agent | 8003 | real Playwright Chromium, sessions, monitoring | — |
| postgres | 5433→5432 | persistence | — |
| redis | 6379 | TTL shared store (pending confirms, cursors, share tokens) | — |

Plus `extension/`: an MV3 browser extension (no port) that operates the user's
own logged-in browser. It is a separate deliverable and is loaded unpacked.

Request flow: voice/text → Whisper STT → intent → RAG-grounded agent → policy
rewrite (disability profile + verbosity + observed behaviour) → TTS.

**Honest ceiling:** no booking has ever been completed on a vendor site. The
extension has read RailYatri's live homepage and driven this repo's own demo
form end to end; vendor flows stay blocked/untested by design. Read
`README.md` §6 before making a claim in a report or demo.

---

## 2. Prerequisites

| Need | Why |
|---|---|
| Docker Desktop 4.x with Compose v2 | runs the 7 services |
| ~8 GB free RAM, ~10 GB free disk | torch, Chromium, Whisper images |
| NVIDIA NIM API key from https://build.nvidia.com | classifier, RAG answers, VLM, policy rewrites |
| Free ports 5173, 8000–8003, 5433, 6379 | bindings |
| Node 18+ (only for frontend dev) | `npm ci`, `npm run build` |
| Python 3.11 in containers; 3.14 host venv works for tests | see §5 |
| Playwright Chromium (installed by `extension/requirements-dev.txt`) | real-browser tests |

Without `NIM_API_KEY` everything still boots: queries/STT/VLM return honest
502/503, and the live-model proof exits 3. There is no mock path that hides it —
do not add one.

---

## 3. Start it with Docker (normal path)

```bash
git clone https://github.com/iishanmakkar/aipd-adaptiveai.git
cd aipd-adaptiveai

# 1. env files (gitignored; templates are committed)
cp backend/.env.example backend/.env
cp intent-engine/.env.example intent-engine/.env
cp agents/.env.example agents/.env
cp browser-agent/.env.example browser-agent/.env
cp frontend/.env.example frontend/.env
```

Then edit the `.env` files:

| File | Must set |
|---|---|
| `backend/.env` | `NIM_API_KEY=nvapi-...`, `JWT_SECRET=<random 32+ chars>` |
| `intent-engine/.env` | `NIM_API_KEY` |
| `agents/.env` | `NIM_API_KEY` (or `LLM_API_KEY`) |
| `browser-agent/.env` | `NIM_API_KEY` (vision narration; `/browse`, `/fill` work without) |
| `frontend/.env` | usually nothing — defaults to `http://localhost:8000` |

Never put a real key in a `VITE_*` variable: it bakes into the public JS
bundle. Vision goes through the backend proxy, which injects the key.

```bash
# 2. build + start (first build 2–5 min)
docker compose up -d --build

# 3. database (fresh volume only)
docker compose exec backend alembic upgrade head

# 4. health
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
curl http://localhost:8003/health
# UI: http://localhost:5173
```

Migration note: `alembic upgrade head` on a **stale volume** from an older
schema can fail with `DuplicateTableError`. Back up, `docker compose down -v`,
start fresh, migrate. Do not hand-create tables.

Production overlay (publishes only 8000 + 5173, internal services stay inside):

```bash
export VITE_API_BASE_URL=https://your-api-origin   # required by the prod build
export ADAPTIVEAI_PRODUCTION=1
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec backend alembic upgrade head
```

With `ADAPTIVEAI_PRODUCTION=1`, the backend **refuses to boot** if `DEBUG=True`
or if `JWT_SECRET` is the shipped placeholder — that refusal is a feature.
`docker compose config --quiet` validates both files (the overlay needs
`VITE_API_BASE_URL` set, as above).

See [`DEPLOY.md`](DEPLOY.md) for the second-host/prod details and host caveats.

---

## 4. Run one service without rebuilding everything

```bash
docker compose up -d postgres redis
docker compose up -d --build intent-engine agents browser-agent backend frontend
docker compose logs -f backend
docker compose up -d --build agents        # rebuild one service
```

---

## 5. Run the tests (no Docker needed for the suites)

**One command, the source of truth:**

```bash
bash scripts/verify-host.sh                 # all five suites, non-zero on any failure
bash scripts/verify-host.sh backend         # or one suite
```

It prints a table and says `VERIFIED on this host` only when every suite passed.
A suite that collects **zero** tests counts as a failure.

Measured 2026-10-24 (tree `e92370f`):

| Suite | Result |
|---|---|
| backend | 253 passed, 1 skipped |
| agents | 103 passed, 1 deselected |
| intent-engine | 135 passed, 2 deselected |
| browser-agent | 63 passed |
| extension (real Chromium) | 140 passed |
| **total** | **694 passed** |

Frontend:

```bash
cd frontend && npm ci && npm run build      # tsc strict + vite
```

Host setup for the suites (no Docker):

```bash
python -m venv --system-site-packages .venv
.venv/Scripts/python.exe -m pip install "python-jose[cryptography]==3.4.0" bcrypt==5.0.0 \
  redis==5.2.1 email-validator==2.2.0 openai==1.54.0 httpx==0.27.2 pytest==8.4.2 \
  pytest-asyncio==0.26.0 "sentence-transformers==3.2.0" faiss-cpu
# only for scripts/stt_local_proof.py:
.venv/Scripts/python.exe -m pip install "faster-whisper==1.1.1" "av==15.1.0"
```

The venv uses the **host's** fastapi/pydantic; `bash scripts/verify.sh` is the
same suites inside the containers (the pinned set) and is the authoritative run
for shipping — it needs the stack up.

### Real proofs that leave the suite

```bash
.venv/Scripts/python.exe scripts/stt_local_proof.py            # exit 0: OS voice -> /api/transcribe
.venv/Scripts/python.exe scripts/extension_step_live_proof.py  # exit 3 when no NIM key (not a pass)
python scripts/real_browser_smoke.py                           # installed browser, 0 failed checks
python scripts/extension_live_site_proof.py                    # exit 0 verified / 3 nothing proven
```

Exit-code contract: **3 means inconclusive, never quote it as a pass**.

---

## 6. Where to change what

| Task | Start here |
|---|---|
| Add a RAG agent | `agents/agents/` (new file) + prompt in `agents/llm/prompts.py` + register in `agents/agents/registry.py`; add seed docs in `agents/rag/seed_data.py` |
| Add knowledge | `agents/rag/seed_data.py` (34 docs / 7 categories; count is pinned by a test) |
| Add a backend route | `backend/app/api/routes_*.py`, include the router in `backend/app/main.py`, add a test |
| Change the policy | `backend/app/services/policy_engine.py` — Rules 1–5, explicit preferences always win over Rule 5 |
| Change intent taxonomy | `intent-engine/app/schemas.py` (pattern) + classifier + `tests/cases.py` (48 shared cases) |
| Add a site recipe | `extension/recipes/*.json` + `index.json` — **data only**: role + accessible-name words, no selectors, no literal values. Validation and tests enforce this |
| Change the extension loop | `extension/src/` (planner → runner → actor → watch → gate); every action needs a readback |
| UI | `frontend/src/` (`ChatInterface`, hooks, `services/api.ts`) |
| Browser automation | `browser-agent/app/` — read §3 gates in its README first |

### Contracts (do not break silently)

```
frontend → backend   POST /api/query               {session_id,input_text,input_source,screen_context}
backend  → intent    POST /intent/classify         {session_id,input_text,screen_context,history}
backend  → agents    POST /agent/respond           {session_id,agent,query,entity,extra_context}
agents               POST /agent/orchestrate       {session_id,goal,entity,extra_context}
extension → backend  POST /api/extension/step      structure in, one verified step out
```

Types: `frontend/src/types/` ↔ `backend/app/schemas/` ↔ `intent-engine/app/schemas.py`
↔ `agents/schemas/`.

---

## 7. Rules that are not negotiable

1. **No fake success.** A status is only `verified`/`completed` when a fact was
   read back from the real system. Unavailable capability returns 502/503/422,
   never invented data. This project had a truth pass for exactly this; do not
   reintroduce a mock or a hardcoded confidence.
2. **Values never leave the device** in the extension: the planner sees
   structure; the vault resolves `profile:<label>` locally. Passwords/OTPs are
   never stored or filled.
3. **Irreversible actions are held.** The extension's spending gate and the
   browser-agent's submit confirmation are local decisions; a model response can
   never clear them.
4. **Untrusted text is data.** Page/document text is fenced in both prompt turns
   (`agents/agents/base.py`). Never interpolate it as instructions.
5. **No OS-level input for automation** (`AUTOMATION_SAFETY.md`): Playwright/CDP
   on a browser the script launched, never `pyautogui`/`SendKeys` against the
   live desktop.
6. **SSRF guards stay on.** Every browser request and robots.txt fetch is
   validated; never bypass `url_guard` for convenience.

---

## 8. Repo map

```
backend/          FastAPI: auth, query orchestration, policy, form-fill, STT, VLM proxy,
                  share, braille, monitor, /api/extension/step (27 routes)
intent-engine/    13-intent classifier + keyword fallback + session memory (4 routes)
agents/           11 RAG agents + orchestrator + FAISS/numpy index (4 routes)
browser-agent/    Playwright sessions, monitoring, safety gates (19 routes)
frontend/         React + Vite UI
extension/        MV3 extension (perception, actor, gate, recipes, voice)
demo/             this repo's own demo pages (not vendors)
scripts/          verify-host.sh, verify.sh, live proof harnesses
docs/             verification baseline, proofs/, runbooks, monitoring log
docker-compose.yml / docker-compose.prod.yml
```

---

## 9. First pull request checklist

- [ ] `bash scripts/verify-host.sh` green (or the affected suite at minimum)
- [ ] `cd frontend && npm run build` clean if you touched `frontend/`
- [ ] If you touched the extension: `cd extension && python -m pytest test` (real Chromium)
- [ ] New behaviour has a test that **fails without the change**
- [ ] No `.env`, key, or secret added; `git status` shows only intended files
- [ ] Docs updated where you changed a fact (counts, ports, endpoints, claims)

A pre-commit security scanner may flag known false positives in the QA proof
scripts (variable report paths, the login form's `autocomplete` attribute). They
are documented; do not "fix" the login form to appease it.

---

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `failed to connect to the docker API` | Docker Desktop not running |
| `POST /api/query` → 502 | intent/agents down: `docker compose ps`, check `INTENT_SERVICE_URL`/`AGENT_SERVICE_URL` |
| 503 on session/query | Postgres down: `docker compose up -d postgres`, `alembic upgrade head` |
| query/STT/VLM → 502/503 | missing/invalid `NIM_API_KEY` in that service's `.env` |
| first query 60–90 s | cold NIM model load; later queries are faster |
| `port is already allocated` | another app holds the port; change the mapping |
| extension tests fail with no content script | must use Playwright `channel="chromium"` (the headless shell cannot load extensions) |
| branded Chrome ignores `--load-extension` | Chrome 137+ removed it; use `chrome://extensions` → Load unpacked, or run the smoke (falls back to Edge) |
| agents fail on `faiss` import | Windows Smart App Control blocks the unsigned DLL; the numpy exact-IP fallback is used automatically |

---

## 11. What is still open (do not "complete" it by claiming it)

- Human NVDA/screen-reader pass with a real ear — `docs/screen-reader-test-script.md`
- Human-speech STT WER — `docs/real-speech-stt-runbook.md`
- A completed booking on a vendor site (blocked/refused by design to evade)
- Cloud deploy + paid-tier capacity — `DEPLOY.md` §6b/§9
- Rotate the NIM key that exists in old history (commit `37bf6fc`)
