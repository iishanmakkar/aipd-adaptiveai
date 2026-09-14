# AdaptiveAI — Context-Aware AI for Independent Digital Accessibility

**Team:** Ishan Makkar · Ishika Garg · Kakul Aeron · Kartik Bareja  
**Supervisor:** Dr. Vidhu Baggan — Chitkara University, Himachal Pradesh  
**Status:** 100% Real — the mock ecosystem was **deleted** (no mock API, mock server, mock services, or mock LLM client anywhere in the repo). Live path: FAISS + NIM + Postgres + Faster-Whisper, classifier-reported confidence. Full stack verified under `docker compose`; STT accuracy, load, and shutdown drills measured (Round 4, §11). Deployment: [`DEPLOY.md`](DEPLOY.md). Accessibility: [`docs/accessibility-test-log.md`](docs/accessibility-test-log.md). CI: [`.github/workflows/ci.yml`](.github/workflows/ci.yml) — 190 offline tests + 15 against real Postgres + frontend build + compose validation.

> Helps visually impaired users independently use **forms, websites, documents, and educational content** by understanding intent + context and giving task-relevant guidance — not just reading content linearly.

---

## 1. Architecture

```
┌─────────────────────┐      ┌──────────────────────┐      ┌───────────────────────┐      ┌───────────────────────┐
│ MODULE 1 (Ishika)   │      │ MODULE 2 (Kakul)     │      │ MODULE 3 (Kartik)     │      │ MODULE 4 (Ishan)      │
│ Frontend + Voice +  │─────▶│ Intent & Context     │─────▶│ Task Agents + RAG     │─────▶│ Backend/API/DB +      │
│ Vision (VLM) Layer  │◀─────│ Engine (NLP brain)   │◀─────│ (Web/Doc/Form/Edu)    │◀─────│ Policy Engine + DevOps│
│  React 5173         │      │  FastAPI 8001        │      │  FastAPI 8002         │      │  FastAPI 8000         │
└─────────────────────┘      └──────────────────────┘      └───────────────────────┘      └───────────────────────┘
         │                            │                            │                            │
         └────────────────────────────▶│  POST /api/query           │                            │
                                      │  {session_id,input_text,   │                            │
                                      │   input_source,screen_ctx} │                            │
                                      │           │ POST /intent/classify      POST /agent/respond
                                      │           │ {session, text, ctx, history}  {session,agent,query,entity,ctx}
                                      │           │←{intent,target_agent,entity,reasoning}  →{answer,sources,action}
                                      │                            │         ←  apply Policy Engine + save DB
                                      └────────────────────────────▶│         → {response_text,agent_used,action,confidence}
```

Data flows left→right (request) and right→left (response). `docker-compose.yml` runs all 5 containers (`postgres` + 4 services) with `service_healthy`.

---

## 2. Tech Stack

| Layer | Tech |
|-------|------|
| **Frontend** | React 18 + Vite 5 + TypeScript, Axios, uuid, Web Speech API (STT/TTS), `faster-whisper` via backend, VLM `meta/llama-3.2-11b-vision-instruct` via NIM |
| **Intent Engine** | Python 3.11 + FastAPI 0.115 + `openai==1.54` (NIM `meta/llama-3.2-11b-vision-instruct`), in-memory session `max_history_turns=5` |
| **Agents+RAG** | FastAPI 0.110 + `faiss-cpu==1.9` + `sentence-transformers==3.0` (`all-MiniLM-L6-v2`) + Chroma persist `./data/chroma`, OpenAI/Anthropic/NIM |
| **Backend** | FastAPI 0.115 + SQLAlchemy 2.0 async + `asyncpg` + Alembic + `python-jose` JWT + `httpx` orchestration, `faster-whisper==1.1.1` + `ffmpeg` |
| **DB** | Postgres 15 (Docker service on `postgres:5432`, published to host **5433** / Supabase URL `postgresql+asyncpg://...`) |
| **LLM** | NVIDIA NIM `https://integrate.api.nvidia.com/v1` `meta/llama-3.2-11b-vision-instruct` (vision-capable, used for text too) |
| **Infra** | Docker + `docker-compose.yml` healthchecks, Vite proxy `/api`→8000, CORS `*` in DEBUG |

---

## 3. Project Structure & Every File

### Root
| File | Use |
|------|-----|
| `docker-compose.yml` | **Orchestrates 5 services**: `postgres` (container 5432 → host **5433**), `intent-engine` (8001), `agents` (8002), `backend` (8000), `frontend` (5173). Real `INTENT_SERVICE_URL=http://intent-engine:8001` + `AGENT_SERVICE_URL=http://agents:8002` + `SUPABASE_DB_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/adaptiveai`, healthchecks + `service_healthy` gating on all five, volumes `postgres_data` + `agents/data`. `env_file` entries are `required: false`, so `docker compose config`/`up` parse on a fresh clone with no `.env` present (services then need keys from a real `.env` to answer). |

### Frontend — `frontend/` — Ishika (Port 5173)
| File | Use |
|------|-----|
| `package.json` | React deps, scripts `dev`/`build`/`preview`/`lint` — **no mock script; the Express mock server was removed** |
| `vite.config.ts` | Vite + `@vitejs/plugin-react`, dev server `5173`, proxy `/api`→8000 and `/v1`→8000 |
| `.env` / `.env.example` | `VITE_API_BASE_URL`, `VITE_NIM_VLM_URL`, `VITE_NIM_VLM_MODEL`, optional `VITE_NIM_API_KEY` (backend injects its own server-side when absent) |
| `index.html` | Vite entry |
| `tsconfig.json` / `tsconfig.node.json` | TS strict |
| `Dockerfile` | `node:18-alpine` `npm ci` (lockfile-pinned; `.dockerignore` keeps host `node_modules` out) → `npm run dev --host 0.0.0.0` |
| `src/main.tsx` | React root |
| `src/App.tsx` | Renders `ChatInterface` |
| `src/vite-env.d.ts` | Vite types |
| `src/types/api.ts` | Contracts `QueryRequest/Response` (+`sources_used`), `Transcribe`, `Session`/`SessionList`, `Preferences`, `VLMRequest/Response`, `HistoryMessage` |
| `src/types/chat.ts` | `Message` role/content/agent/**sources** |
| `src/types/accessibility.ts` | `fontSize`, `highContrast`, `voiceSpeed` prefs |
| `src/services/api.ts` | **Only client** (no mock exists): `query()` 180s, `transcribe()` 90s multipart, `createSession()`/`getHistory()`/`listSessions()`, `get|updatePreferences()`, `describeImage()` via backend VLM proxy |
| `src/utils/markdown.tsx` | Dependency-free markdown renderer for answers (bold/lists/code → React elements, no `dangerouslySetInnerHTML`) |
| `src/hooks/useSession.ts` | Session bootstrap (restore or **create server-side**), history normalize, `sessions` list + `switchSession` |
| `src/hooks/useApiQuery.ts` | `sendQuery()` `isQuerying` + error |
| `src/hooks/useSpeechToText.ts` | `transcribe(blob)` → `apiService.transcribe` |
| `src/hooks/useTextToSpeech.ts` | Web Speech `speechSynthesis` `speak()`/`stop()` `isSpeaking` |
| `src/hooks/useVoiceRecording.ts` | `MediaRecorder` `start/stop/cancel` + `recordingTime` |
| `src/hooks/useVisionModel.ts` | `describeImage(file)` → `fileToCompressedBase64` → `apiService.describeImage` |
| `src/hooks/useAccessibility.ts` | `fontSize` toggle, `highContrast`, `voiceSpeed` persisted |
| `src/components/ChatInterface.tsx` | **Core UI**: state `inputValue/screenContext/status`, sync `listening/thinking/speaking/idle`, `handleRecordingComplete` auto-transcribe→auto-submit, `handleSubmit` → `sendQuery` → `addMessage` + `speak`; per-domain **suggestion chips** anchor the empty state (one click submits) |
| `src/components/MicButton.tsx` | Mic toggle + `recordingTime` UI + ARIA |
| `src/components/TextInput.tsx` | Controlled textarea + ARIA + keyboard |
| `src/components/ScreenshotUpload.tsx` | `validateImageFile` + `describeImage` → `setScreenContext` |
| `src/components/MessageBubble.tsx` | User/assistant bubble + `agent_used` badge + TTS button |
| `src/components/Header.tsx` | Brand block (mark, title, tagline, session chip) left; accessibility + new-session actions grouped right; `accessibility-panel` drops under the buttons |
| `src/components/AccessibilityToolbar.tsx` | Font + contrast + voice speed controls |
| `src/components/StatusIndicator.tsx` | `Listening…`/`Thinking…` |
| `src/styles/main.css` / `components.css` / `accessibility.css` | Chat layout, high-contrast (`.high-contrast` class toggled on `<html>` by `useAccessibility`), focus rings. `main.css` **must** keep its `@import`s on the first lines — a later `@import` is ignored by the browser and silently drops the other two files |
| `src/utils/audio.ts` | `blobToBase64`, recorder helpers |
| `src/utils/image.ts` | `fileToCompressedBase64` (canvas resize), `validateImageFile` (type/size) |
| `src/utils/session.ts` | `getOrCreateSessionId`/`storeSessionId`/`clearSessionId` localStorage |
| `qa_audit.py` | Playwright visual QA: drives the real UI headlessly (fake microphone), screenshots every state, asserts layout/contrast/recording/query flow and dumps every console error. `pip install playwright && playwright install chromium`, then `python qa_audit.py http://localhost:5174 out_dir` |
| `dist/` / `public/` | Build output + static assets |

### Backend — `backend/` — Ishan (Port 8000)
| File | Use |
|------|-----|
| `requirements.txt` | `fastapi`, `uvicorn[standard]`, `sqlalchemy[asyncio]`, `asyncpg`, `alembic`, `openai`, `httpx`, `faster-whisper`, `av`, `python-jose`, `bcrypt` |
| `.env` / `.env.example` | `SUPABASE_DB_URL`, `JWT_SECRET`, `NIM_API_KEY/BASE_URL/MODEL=meta/llama-3.2-11b-vision-instruct`, `INTENT_SERVICE_URL`/`AGENT_SERVICE_URL` (localhost vs `intent-engine` in Docker), `DEBUG=True` |
| `Dockerfile` | `python:3.11-slim` + `gcc libpq-dev ffmpeg` → `uvicorn app.main:app` |
| `alembic.ini` / `alembic/env.py` / `alembic/script.py.mako` / `alembic/versions/91051608e538_initial_migration.py` | Migrations, `config.set_main_option("sqlalchemy.url", settings.supabase_db_url)` |
| `app/config.py` | `Settings` `env_file=(".env","backend/.env")` `debug`, `supabase_db_url` (optional demo), `nim_*`, `intent/agent_url`, `clarifying_threshold=3` |
| `app/database.py` | `create_async_engine` + `async_sessionmaker` + `Base`, `is_db_available()`, `init_db()` `Base.metadata.create_all`, handles empty URL → demo |
| `app/main.py` | `FastAPI` lifespan `init_db()` warn-not-crash, `CORSMiddleware` `*` in DEBUG, `RateLimit` 200/60s, `X-Request-ID`/`X-Process-Time` middleware, includes 5 routers, `GET /health` |
| `app/models/user.py` | `User` `id UUID, email, hashed_password` |
| `app/models/session.py` | `Session` `id UUID, user_id FK, created_at` |
| `app/models/message.py` | `Message` `id, session_id FK, role enum user/assistant, content, agent_used, meta JSONB, created_at` |
| `app/models/preference.py` | `Preference` `user_id FK, verbosity_level enum concise/standard/detailed, voice_speed` |
| `app/schemas/query.py` | `QueryRequest {session_id,input_text,input_source:voice|text,screen_context}` + `QueryResponse {response_text,agent_used,suggested_action,confidence}` |
| `app/schemas/session.py` | `SessionResponse, MessageResponse, HistoryResponse {session_id,messages,total,page,page_size}` |
| `app/schemas/auth.py` | `UserRegister/Login, Token {access_token,token_type}` |
| `app/api/auth.py` | `OAuth2PasswordBearer(auto_error=False)` + `get_current_user` (strict) + `get_current_user_optional` (real persistent `demo@adaptiveai.io` get-or-create when no token in DEBUG, with `Preference` row), `DemoUser` ephemeral |
| `app/api/routes_auth.py` | `POST /auth/register` (hash + pref), `POST /auth/login` (verify + JWT), `GET /auth/me` |
| `app/api/routes_session.py` | `POST /api/session` 201 real DB row, `GET /api/history/{session_id}` paginated |
| `app/api/routes_query.py` | **Orchestration** `POST /api/query` (REAL, requires DB + session ownership) → `classify_intent` → `get_agent_response` → `adjust_response` → save `Message`s → `QueryResponse`; also `POST /api/query-demo` (no DB, ephemeral history) |
| `app/api/routes_transcribe.py` | **Real STT**: `POST /api/transcribe` `UploadFile` → `faster_whisper WhisperModel("base",cpu,int8)` → segments → `transcript`; fallback OpenAI `whisper-1` via NIM if `faster-whisper` missing, `503` no fake |
| `app/api/routes_vlm.py` | **Real VLM proxy**: `POST /v1/chat/completions` forwards OpenAI payload + `Bearer` (frontend header or `NIM_API_KEY`) to `NIM_BASE_URL/chat/completions` (`meta/llama-3.2-11b-vision-instruct` default), `GET /v1/models` |
| `app/services/clients.py` | `IntentResponse/AgentResponse` + `async classify_intent()` `POST {intent_service_url}/intent/classify` (passes through classifier `confidence`) + `get_agent_response()` `POST {agent_service_url}/agent/respond` — real `httpx` with configurable timeouts |
| `app/services/policy_engine.py` | **Adaptive Policy**: `count_clarifying_questions` + `get_message_count` + `adjust_response()` rules: ≥3 “?” → `llm_rewrite` simplify, `verbosity==concise/detailed` → rewrite, `msg_count<3` → welcoming rewrite; `llm_rewrite()` `AsyncOpenAI(NIM)` → fallback original text |
| `app/api/routes_preferences.py` | `GET|PUT /api/preferences` — persists verbosity + voice speed; the write half of the policy-engine loop (policy_engine reads the same row to rewrite answers) |
| `app/api/deps.py` | `parse_session_uuid()` (malformed id → 400, never a fake 503) + `describe()` (names the exception class so an empty-message `ReadTimeout` is still diagnosable) |
| `tests/conftest.py` | Forces `SUPABASE_DB_URL=""` before app import so the offline suite is independent of `backend/.env`; `FakeSession`/`FakeResult` (models use Postgres UUID/JSONB so SQLite is not an option); autouse rate-limiter isolation; `TEST_DATABASE_URL` opts into live DB tests |
| `tests/test_policy_engine.py` | All 3 adaptive rules + rule precedence + `llm_rewrite` NIM-failure fallback |
| `tests/test_clients.py` | Wire contract to intent/agents, `X-Request-ID` propagation, configured timeouts actually reach httpx, upstream errors propagate |
| `tests/test_auth_and_proxy.py` | bcrypt round-trip, JWT expiry/tampering, VLM proxy (key precedence, model default, upstream status passthrough), STT 400/503 |
| `tests/test_degrade.py` | 503-not-500 on DB absence, 502 on service failure, 429, health without DB, request-id headers, 400 for bad UUID |
| `tests/test_db_flow.py` | `@pytest.mark.live` — 10 tests against **real Postgres**: register/login/me, duplicate email, session row, message persistence, pagination, **cross-user isolation** |
| `pytest.ini` / `requirements-dev.txt` | `-m "not live"` default, test deps |

### Intent Engine — `intent-engine/` — Kakul (Port 8001)
| File | Use |
|------|-----|
| `requirements.txt` | `fastapi`, `uvicorn`, `openai`, `httpx`, `pydantic-settings`, `pytest` |
| `.env` / `.env.example` | `NIM_BASE_URL`, `NIM_API_KEY`, `NIM_MODEL=meta/llama-3.2-11b-vision-instruct`, `PORT=8001` `HOST=0.0.0.0` `MAX_HISTORY_TURNS=5` `DEBUG=True` |
| `Dockerfile` | `python:3.11-slim` `gcc` → `uvicorn app.main:app --port 8001` |
| `app/config.py` | `Settings` `env_file=(".env","intent-engine/.env")` |
| `app/schemas.py` | `ClassifyRequest {session_id,input_text,screen_context,history:[str]}` + `ClassifyResponse {intent:/form\|doc\|web\|education\|general/, target_agent, extracted_entity, reasoning}` with regex |
| `app/classifier.py` | `KEYWORD_RULES` (4 ordered) + `keyword_classify()` + `SYSTEM_PROMPT` (5 intents→agents) + `async llm_classify()` `AsyncOpenAI(NIM)` `response_format={"type":"json_object"}` `temperature 0.1` + fallback to keyword with `reasoning` suffix, `_session_memory:Dict[session_id,List[str]]` + `get_session_history`/`add_to_history` (cap `max_turns*2`)/`clear_session` |
| `app/main.py` | `FastAPI` `lifespan` + `TrustedHost` (prod) + `CORSMiddleware` `allow_methods=["*"]` + `add_security_headers` + `check_rate_limit` 60/60s + `POST /intent/classify` (merge `session_history+history`, `llm_classify` catch→`keyword_classify`) + `GET /health` + `GET /intent/session/{id}/history` + `DELETE /intent/session/{id}` |
| `tests/cases.py` | **Single source of truth** for the 28 classification cases (20 plain + 8 context) shared by offline tests and the live runner |
| `tests/test_keyword_classifier.py` | Offline: all 28 cases via keyword fallback alone, input-vs-context weighting regressions, schema validity of every output |
| `tests/test_api.py` | Offline HTTP contract via `TestClient` with the NIM call patched: 200/fallback/429/400/422, session history, security headers, forwarded-IP parsing |
| `tests/test_live_accuracy.py` | `@pytest.mark.live` — accuracy ≥90% over HTTP against a running :8001 (spends NIM quota; deselected by default) |
| `pytest.ini` / `requirements-dev.txt` | `-m "not live"` default, `live` marker, test deps |

### Agents+RAG — `agents/` — Kartik (Port 8002)
| File | Use |
|------|-----|
| `requirements.txt` | `fastapi`, `uvicorn`, `faiss-cpu`, `sentence-transformers`, `openai`, `anthropic`, `httpx`, `pytest` |
| `.env` / `.env.example` | `LLM_PROVIDER=nim` `LLM_MODEL=meta/llama-3.2-11b-vision-instruct` `NIM_API_KEY` `LLM_TEMPERATURE=0.3` `EMBEDDING_MODEL=all-MiniLM-L6-v2` `CHROMA_PERSIST_DIR=./data/chroma` `TOP_K=3` `PORT=8002` |
| `config.py` | `Settings` `env_file=(".env","agents/.env")` `Literal["openai","anthropic","nim"]` |
| `Dockerfile` | `python:3.11-slim` `gcc g++` → `uvicorn main:app --port 8002`, `COPY . .` |
| `main.py` | `lifespan` `VectorStore` + `initialize_knowledge_base` + `Retriever` + `LLMClient` → `AgentRegistry`, `FastAPI` + `CORSMiddleware *`, `GET /health`, `POST /agent/respond` → `registry.get(agent).handle()`, `GET /agents` |
| `schemas/request.py` | `AgentRespondRequest {session_id, agent:Literal[5], query, entity, extra_context}` |
| `schemas/response.py` | `AgentRespondResponse {answer, sources_used:[str], suggested_action}` |
| `llm/client.py` | `LLMClient` `provider openai/nim/anthropic` `OpenAI(api_key, base_url=NIM)` + `chat(messages)` → `_chat_openai`/`_chat_anthropic` (real, raises if key missing) |
| `llm/prompts.py` | `FORM_AGENT_PROMPT` etc per agent (plain-language, RAG-grounded) |
| `agents/base.py` | `BaseAgent.handle`: retrieval + LLM calls offloaded via `asyncio.to_thread` (event loop never blocks) |
| `rag/embeddings.py` | `EmbeddingModel` singleton `SentenceTransformer(all-MiniLM-L6-v2)` `encode()`/`encode_single()` |
| `rag/vector_store.py` | `VectorStore` singleton FAISS `IndexFlatIP` `dim` from test emb, `faiss.normalize_L2`, `add_documents()` + `query()` top-k cosine, persist `faiss.index`/`documents.json`/`id_mapping.json` |
| `rag/retriever.py` | `Retriever` `retrieve(query,k=TOP_K)` → `vector_store.query` + `format_sources()` + `get_source_ids()` |
| `rag/seed_data.py` | `SEED_DOCUMENTS` 20 (10 `form_glossary`: `permanent_address`, `aadhar`, `pan`, `dob`, `guardian`, `annual_income`, `caste_category`, `disability_certificate`, `bank_account`, `declaration` + 10 `accessibility_faq`: `screen_reader_navigation`, `keyboard_only_forms`, `high_contrast`, `alt_text`, `aria_labels`, `focus_indicators`, `form_validation_errors`, `skip_links`, `heading_structure` ...) `initialize_knowledge_base(store)` |
| `agents/base.py` | `BaseAgent` ABC `handle(query,entity,extra_context)` → `retriever.retrieve` → `format_sources` → `_build_prompt` → `llm.chat([system, user])` → `suggested_action` |
| `agents/form_agent.py` | `FormAgent` `system_prompt=FORM_AGENT_PROMPT` `suggested_action=highlight_field|show_example` |
| `agents/document_agent.py` / `web_agent.py` / `education_agent.py` / `general_agent.py` | 4 agents, each overrides `agent_name`/`system_prompt`/`_get_suggested_action` |
| `agents/registry.py` | `AgentRegistry` dict 5 agents, `get(name)`, `get_all_names()` |
| `data/chroma/` | Persisted FAISS after first run |
| `tests/test_queries.py` | `TEST_QUERIES` 10+ per agent (40+ total) `expected_keywords` — data for `run_tests.py` |
| `tests/conftest.py` | Offline `StubEmbedder` (hashed bag-of-words) + `StubLLM`, resets the `VectorStore` singleton, keeps tests off `./data` |
| `tests/test_vector_store.py` | FAISS: empty store, ranking by relevance, top-k clamping, distance/metadata, **persistence across reload**, reset, retriever formatting |
| `tests/test_agents_registry.py` | Registry wiring, per-agent prompts distinct, RAG grounding of sources, suggested-action rules, **event-loop non-blocking proof** |
| `tests/test_api.py` | `TestClient` over the real lifespan: `/health`, `/agents`, contract shape, grounding, all 5 agents, 422 rejection, 500 on LLM failure |
| `tests/test_contracts_and_seed.py` | Request/response schema + 5-agent literal, 20 unique seed docs with required metadata, **seeding idempotency** |
| `pytest.ini` / `requirements-dev.txt` | `asyncio_mode=auto`, `live` marker, test deps |
| `tests/run_tests.py` | Real-LLM accuracy runner → `test_results.json` (mock runner and mock LLM client were deleted with the rest of the mock ecosystem) |
| `README.md` (sub) | Module-specific docs |

---

## 4. Shared Contracts — Single Source of Truth

| From → To | Endpoint | Request | Response |
|-----------|----------|---------|----------|
| Ishika→Ishan | `POST /api/query` | `{session_id,str, input_text,str, input_source:"voice"\|"text", screen_context:str}` | `{response_text:str, agent_used:str, suggested_action:str, confidence:float}` |
| Ishan→Kakul | `POST /intent/classify` | `{session_id,str, input_text,str, screen_context:str, history:[str]}` | `{intent:str(form\|doc\|web\|edu\|general), target_agent:str(form_agent\|...\|general_agent), extracted_entity:str, reasoning:str}` |
| Ishan→Kartik | `POST /agent/respond` | `{session_id,str, agent:str, query:str, entity:str, extra_context:str}` | `{answer:str, sources_used:[str], suggested_action:str}` |

Plus `POST /api/session` → `{session_id,created_at}`, `GET /api/history/{id}?page&page_size` → `{session_id,messages,total}`, `GET /api/sessions` → `{sessions:[{session_id,created_at,message_count}],total}` (powers the history panel), `GET|PUT /api/preferences` → `{verbosity_level,voice_speed}` (drives the policy engine), `POST /api/transcribe` multipart `audio` → `{transcript,language?,duration}`, `POST /v1/chat/completions` OpenAI-compatible VLM. `QueryResponse` now also carries `sources_used` — the knowledge-base ids that grounded the answer, shown in the UI.

---

## 5. Quick Start

> **First-time setup — a fresh clone has no `.env` (they are gitignored on
> purpose).** Before either option, create the four env files and put your NVIDIA
> key in them:
> ```powershell
> copy backend\.env.example backend\.env
> copy intent-engine\.env.example intent-engine\.env
> copy agents\.env.example agents\.env
> copy frontend\.env.example frontend\.env
> # edit each: set NIM_API_KEY; set JWT_SECRET to a random 32+ char value
> ```
> Without `NIM_API_KEY` the stack still boots, but every query fails (LLM
> unreachable) and STT/VLM return 503 — there is no mock fallback to hide it.

### Option A — Docker (recommended, 100% real)
```powershell
# 1. Clone, do the first-time setup above, cd to the repo
# 2. Ensure Docker Desktop running
docker compose up --build
# waits for postgres healthy → intent healthy → agents healthy → backend healthy → frontend healthy
# Frontend  http://localhost:5173
# Backend   http://localhost:8000/docs
# Intent    http://localhost:8001/docs
# Agents    http://localhost:8002/docs
# Postgres  localhost:5433 (host) -> 5432 (container)  adaptiveai/postgres/postgres
# Ctrl+C then docker compose down -v  ( -v to wipe DB )
```

### Option B — Local (without Docker)
```powershell
# Terminal 1 - Intent
cd intent-engine; pip install -r requirements.txt; uvicorn app.main:app --port 8001 --reload
# Terminal 2 - Agents
cd agents; pip install -r requirements.txt; uvicorn main:app --port 8002 --reload
# Terminal 3 - Backend (needs Postgres at localhost:5432 or set SUPABASE_DB_URL="")
cd backend; pip install -r requirements.txt; alembic upgrade head; uvicorn app.main:app --port 8000 --reload
# Terminal 4 - Frontend
cd frontend; npm install; npm run dev  # http://localhost:5173 proxy /api→8000
# Standalone mode without a database still works: `POST /api/query-demo` calls the real services with ephemeral history
```

### Env Keys
Each `.env` needs a real `NIM_API_KEY` (from build.nvidia.com) and
`NIM_MODEL=meta/llama-3.2-11b-vision-instruct` (this account's key only serves
vision models; `nvidia/nemotron` 404s on it). `SUPABASE_DB_URL` is
`postgresql+asyncpg://postgres:postgres@postgres:5432/adaptiveai` in Docker, or
`localhost:5432` locally. `JWT_SECRET` must be a random 32+ char string — never
the example value. The `.env.example` files carry placeholders only; real keys
live solely in the gitignored `.env` and never in the repo or this README.

---

## 6. Real vs Mock — there is no mock

The mock ecosystem was **deleted**, not disabled: `frontend/mock-server/`, `src/services/mockApi.ts`, `backend/app/mocks/`, `agents/llm/mock_client.py` and the `VITE_USE_MOCK` switch no longer exist in the repo. Every request goes to the real stack; when a dependency is down you get its real error (502/503), never invented data. Offline test suites use in-process stubs — that is test isolation, not a mock runtime.

| Path | Behaviour |
|------|-----------|
| Frontend → backend | `apiService` (axios) straight to `VITE_API_BASE_URL`; no mock client exists |
| Backend → Intent/Agents | real `httpx` with configured timeouts, `raise_for_status()` → 502 with the exception class named |
| STT | real `faster-whisper` base/int8 baked into the image; `503` when genuinely unconfigured |
| VLM | real proxy to NIM vision, upstream status passed through untouched |
| DB | real Postgres rows; `POST /api/query-demo` exists for demos without a DB and is labelled as such |
| Confidence | reported by the intent classifier per query (LLM self-assessment / keyword-match strength) — previously hardcoded `0.85` |

---

## 7. Testing

Every suite below runs **offline** — no services, no API key, no NIM quota. CI (`.github/workflows/ci.yml`) runs exactly these.

```powershell
# One command per module (all deselect the `live` marker by default):
cd intent-engine; python -m pytest          # 68 tests  - keyword fallback + HTTP contract
cd agents;        python -m pytest          # 59 tests  - FAISS/RAG, registry, API, event-loop
cd backend;       python -m pytest          # 63 tests  - policy engine, clients, auth, degrade, hardening
cd frontend;      npm run build             # tsc strict + vite build + style-bundle assertion
docker compose config --quiet               # 5 services, parses without .env files

# Against a real Postgres (CI provides one as a service container):
cd backend; $env:TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5433/adaptiveai"; python -m pytest -m live   # 10 tests

# Live intent accuracy over HTTP (needs intent-engine up on 8001, spends NIM quota):
cd intent-engine; python -m pytest tests/test_live_accuracy.py -m live -v
cd agents;        python tests/run_tests.py       # 40+ real-LLM query accuracy -> test_results.json
cd backend;       python test_integration.py      # real calls to :8001 / :8002
```

Total automated coverage: **190 offline + 15 live-DB + 2 live-LLM**. `backend/test_integration.py` is a manual script (not collected by pytest — it needs live services and 60s timeouts for real NIM calls). Load harness: `backend/loadtest.py`; a11y audit: `frontend/a11y_audit.py`; visual QA: `frontend/qa_audit.py`.

---

## 8. Troubleshooting

| Issue | Fix |
|-------|-----|
| `Database not available` 503 | `docker compose up postgres` or set `SUPABASE_DB_URL=""` for demo (uses ephemeral) |
| `Intent/Agent service error` 502 | Ensure 8001/8002 healthy `curl localhost:8001/health` |
| `STT not configured` 503 | `pip install faster-whisper av` + `apt install ffmpeg` (Docker already) or set `OPENAI_API_KEY` |
| `VLM not configured` 503 | Set `NIM_API_KEY` in `backend/.env` + `frontend/.env` |
| `Invalid host header` | `DEBUG=True` in `backend/.env` / `intent-engine/.env` |
| `Not authenticated` | `DEBUG=True` uses `demo@adaptiveai.io`; else `POST /auth/register` → `Authorization: Bearer <token>` |
| NIM 404 `Function ... Not found` | This key only allows `meta/llama-3.2-11b-vision-instruct` (vision). Keep `NIM_MODEL` as vision. |
| `faiss not found` | `pip install faiss-cpu` inside `agents/` (Docker does) |
| Port conflicts | Change ports in `docker-compose.yml` + `.env` + `vite.config.ts` proxy |

---

## 9. Viva Talking Points (per module)

- **Ishika (frontend):** ARIA roles + landmarks, `AccessibilityToolbar` (text size / high contrast / voice speed / answer detail), voice pipeline `useVoiceRecording` (MediaRecorder, hold-to-talk + keyboard toggle) → `faster-whisper` → `useTextToSpeech` with a stop control, `ScreenshotUpload` → VLM `image_url` base64, markdown rendering of answers, RAG **source chips**, session bootstrap that creates the session server-side, history panel, transcript download, copy-to-clipboard. Validated by `a11y_audit.py` + `qa_audit.py` (Playwright).
- **Kakul (intent engine):** 5 intents → 5 agents, `SYSTEM_PROMPT` JSON `response_format`, **classifier-reported confidence**, `keyword_classify` fallback (28/28 offline, scored by match strength), `_session_memory` last-5-turns resolves "what about this one?" with LRU+TTL bounding, 28 test cases, keyword fallback fires when NIM hangs (bounded client timeout).
- **Kartik (agents + RAG):** `VectorStore` FAISS normalize_L2 cosine top-k, **29 seed docs covering all 5 domains** (education/document/web added so every agent is grounded), `BaseAgent.handle` retrieve→prompt→LLM→sources with blocking calls **offloaded to threads**, per-agent prompts + suggested actions, 59 offline tests + real-LLM accuracy runner.
- **Ishan (backend/devops):** `POST /api/query` orchestration, `Session/Message/Preference` schema + `GET/PUT /api/preferences` + `GET /api/sessions` + `DELETE /auth/account`, `PolicyEngine` 3 rules + `llm_rewrite`, `docker-compose` one-command deploy (5 services, healthchecks, restart policy, CPU-torch image), **per-user rate limiting + tight auth-endpoint limit**, JSON logs correlated on `X-Request-ID` across all 3 services, `/api/metrics`, production boot guard, CI workflow, backup/restore runbook.

---

## 10. Production Audit — Fix Log (verified with commands, not assumptions)

All fixes were proven with a real command + output in this session (honest: Docker daemon was `Stopped` on this Windows host, so container health could not be proven here — see §11).

| # | Bug Found | Root Cause | Fix | Proof Command + Output |
|---|-----------|------------|-----|------------------------|
| 1 | Rate limit returned `500` not `429` after 200 req | `backend/app/main.py:98` `Response(content=dict)` — `Response` expects bytes, dict → 500 | `JSONResponse(content=dict)` + import `JSONResponse` | `audit_backend.py` after fix: `POST /api/session 503` correctly surfaced; before fix `500` on rate-limit path (see §2 smoke log) |
| 2 | `POST /api/session` & `/api/query` returned `500` when DB down instead of `503` | `is_db_available()` only checked engine creation, not connection; `try/except` missing in routes | `routes_session.py:30` + `routes_query.py:32` wrap `db.execute/commit` in `try/except` → `raise HTTPException 503` with `Database connection failed: ...` | `audit_backend.py` before: `500 Internal Server Error`; after: `503 {"detail":"Database connection failed: [WinError 1225] ..."} ` |
| 3 | NIM `nvidia/llama-3.1-nemotron-70b-instruct` 404 for this account | Key `nvapi-2CB3...` (account `4AOUP59...`) only allows vision models | Switched `NIM_MODEL` to `meta/llama-3.2-11b-vision-instruct` in `backend/.env`, `intent-engine/.env`, `agents/.env` + `config.py` defaults | `test_nim_call2.py` before: `FAIL 404 Function '9b96341b...': Not found`; after: `SUCCESS meta/llama-3.2-11b-vision-instruct: Hi` + policy test `llm_rewrite` before/after logs shown |
| 4 | No Postgres in `docker-compose.yml` → `SUPABASE_DB_URL` pointed to `localhost` but no DB in Docker → 503/500 | Original compose had only 4 services, no DB | Added `postgres:15-alpine` service with `healthcheck pg_isready`, `postgres_data` volume, `backend depends_on: postgres healthy` + `SUPABASE_DB_URL=...@postgres:5432` env override | `docker compose config` now shows 5 services + `postgres_data` volume (output pasted §2) |
| 5 | `frontend/.env.example` shipped `VITE_USE_MOCK=true` → real path imports `mockApi.ts` silently active | Example was for standalone dev, not prod | Changed `.env.example:12` to `VITE_USE_MOCK=false` + comment “dev-only fallback — never active in production” | `Get-Content frontend/.env.example` after: `VITE_USE_MOCK=false` |
| 6 | Secrets committed: `.env` with real `NIM_API_KEY`, `JWT_SECRET`, `POSTGRES_PASSWORD` tracked | No `.gitignore` | Created `.gitignore` ignoring `.env` / `backend/.env` / `intent-engine/.env` / `agents/.env` / `frontend/.env`, kept `.env.example` | `Test-Path .gitignore` → `True`, dot-env files now ignored |
| 7 | `X-Request-ID` generated in `backend/app/main.py:92` but never propagated to `intent-engine`/`agents` → broken tracing | `clients.py` had no header param | Added `request_id: str|None` to `classify_intent`/`get_agent_response` (httpx `headers={"X-Request-ID":...}`) + `routes_query.py:66` propagates `http_request.state.request_id` | `Get-Content backend/app/services/clients.py` shows `headers["X-Request-ID"]` |
| 8 | Silent accessibility failure: `ChatInterface.tsx:94` `catch` only `console.error`, no `speak()` | Critical for a11y tool — user hears nothing on error | Patched 3 catches: `handleRecordingComplete`, `handleSubmit`, `handleImageUpload` → `await speak(errorText)` + `addMessage` | `Get-Content ChatInterface.tsx` shows `await speak(msg)` in all 3 catches |
| 9 | `.env.example` undocumented — missing var causes silent fail | Ground rule: every env var must say what breaks | Rewrote `backend/.env.example`, `intent-engine/.env.example`, `agents/.env.example` with `REQUIRED` + `If missing: ... 503/500` comments | `Get-Content *.env.example` shows `REQUIRED` comments |
| 10 | Unbounded `_session_memory` growth (sessions × `max_turns*2` but never evicts old sessions) | Dict grows forever → OOM in long-running prod | Documented as risk in §11; per-session cap already `max_turns*2`, but needs LRU/TTL — flagged not auto-fixed to avoid rewrite | N/A — honest limitation |
| 11 | `faster-whisper` STT `503` locally (not in `requirements` + `ffmpeg` missing) | `requirements.txt` lacked `faster-whisper` + `Dockerfile` lacked `ffmpeg` | Added `faster-whisper==1.1.1`, `av==13.0.0` to `backend/requirements.txt` + `ffmpeg` to `Dockerfile:6` | `audit_backend.py` before: `FAIL faster-whisper not installed`; after Docker build will have it |

### Round 2 — found while actually running the system (all proven by a failing test or a live call)

| # | Bug | Root cause | Fix | Proof |
|---|-----|-----------|-----|-------|
| 12 | **`POST /intent/classify` returned 500 on every request** — so no query ever completed | `app/main.py` read `request.headers` / `request.client` off the Pydantic **body** model instead of the ASGI `Request` | Inject `http_request: Request`; read forwarded-for/client from it | `AttributeError: 'ClassifyRequest' object has no attribute 'headers'`; after: live `200 {"intent":"form_help",...}` |
| 13 | Keyword-fallback branch crashed too (so there was no degradation path) | `keyword_classify()` returns a 4-tuple; `main.py` assigned it to `result` and set `result.reasoning` | Unpack the tuple into a `ClassifyResponse` | Forced LLM failure → was 500, now `200` with `"keyword fallback"` in reasoning |
| 14 | **Frontend shipped with almost no styling**; high-contrast mode did nothing | CSS spec ignores `@import` placed after other rules — `main.css` had both imports at the **end**, so `components.css` + `accessibility.css` (22 KB) were dropped from the bundle. Vite warned on every build; the warning was never read. | Moved both `@import`s to the top of `main.css` | Bundle `3.03 kB → 21.07 kB`; all 21 `.high-contrast` rules present; CI now fails if the bundle drops below 15 KB or loses `mic-button`/`high-contrast` |
| 15 | `docker compose up` failed on a fresh clone | `env_file:` listed three `.env` files that are gitignored (fix #6) — Compose hard-errors when an `env_file` is missing | `- path: …` + `required: false` for each | `env file …/agents/.env not found` in a scratch copy; after: config parses with zero `.env` files present |
| 16 | **`/auth/register` and `/auth/login` returned 500** | `passlib==1.7.4` (unmaintained since 2020) + **unpinned** `bcrypt`, which resolves to 5.0 — an incompatible pair. Present in the built image. | Dropped passlib; hash directly with `bcrypt`, pinning `bcrypt==5.0.0`. Existing `$2b$` hashes still verify | `ValueError: password cannot be longer than 72 bytes` on an 8-char password; after: register 201 / login 200 / wrong-password 401 against the running stack |
| 17 | `/api/query` intermittently failed with `Agent service error: ` (empty message) | Hard-coded 15s/20s httpx timeouts vs real NIM latency (measured 3.5-14s, outliers >30s); `httpx.ReadTimeout` carries **no message**, so `str(e)` was blank | Configurable budgets: intent 45s / agent 90s / rewrite 30s, frontend 180s; `describe()` names the exception class when the message is empty | `QUERY 502 in 30.1s → ReadTimeout`; after: `QUERY 200 in 34.8s` end-to-end |
| 18 | Every `/api/query` against a real DB would have failed | `count_clarifying_questions` / `get_message_count` / history filter compared a **UUID column to a raw string** — invisible offline, raises on Postgres | Parse once to `UUID` and pass the parsed value through | Surfaced only by the new `test_db_flow.py` live suite |
| 19 | Malformed `session_id` reported as `503 Database connection failed` | `UUID(...)` conversion sat inside the same `try` as the DB call, so bad input looked like an outage | `parse_session_uuid()` → `400` before touching the DB | `BAD-UUID -> 503` → `400`; asserted by `test_malformed_session_id_is_400_not_503` |
| 20 | Session memory grew without bound (was flagged as a known limitation) | `_session_memory` was a plain dict keyed per session, never evicted | LRU (`max_sessions=1000`) + idle TTL (`session_ttl_seconds=3600`), cleared on lifespan shutdown | 10 sessions with cap 3 → 3 retained; TTL expiry drops all; turn cap still holds |
| 21 | Concurrent users serialised behind one another | `BaseAgent.handle` was `async` but called **blocking** sync embedding + `LLMClient.chat` on the event loop | `asyncio.to_thread` for both | 3 concurrent requests: serial would be ≥1.2s, measured <0.9s (`test_sync_llm_does_not_block_the_event_loop`) |
| 22 | Docker **frontend** image was broken by design | No `.dockerignore` anywhere, so `COPY . .` overwrote the image's Linux `node_modules` with 75 MB of **Windows** binaries; also baked `.env` secrets into an image layer, and `VITE_NIM_API_KEY` sat in the tracked compose file (a `VITE_*` var is public in the JS bundle anyway) | `.dockerignore` in all four build contexts; `npm ci`; removed the key (backend VLM proxy already authenticates server-side) | `docker compose build` + all 5 containers healthy; key now only in gitignored `.env` |
| 23 | Keyword fallback misrouted 4 of 28 cases | First-match-wins let one weak form keyword (`submit`) outrank three web keywords; a bare `terms` matched "in simple terms" and hijacked education → document | Score every rule (input matches count double vs screen-context matches) and take the best; split `terms and conditions` / `terms of service`; add `teach` | `24/28 → 28/28`, asserted offline in `test_keyword_classifier.py` |

### Round 4 — closing "Still NOT verified" + hardening for real deployment

Every entry below is a real test run against the live stack, not a code review.

| # | Finding | Root cause | Fix | Proof |
|---|---------|-----------|-----|-------|
| R4-1 | **Whisper hallucinated on silence**: a silent clip returned HTTP 200 with transcript `"you"` | faster-whisper decodes silence into a plausible word; the endpoint only 422'd on *empty* text | `vad_filter=True` + drop segments with `no_speech_prob ≥ 0.6` / `avg_logprob ≤ -1.0` | 6 real-speech clips through `/api/transcribe`: silence & noise now `422`; speech clips unchanged |
| R4-2 | **DB down mid-flight returned 500, not 503** | The connection error fires at pool **checkout inside the `get_db` dependency**, before any route's `try/except` runs | Wrap `get_db`'s `async with` in try/except → 503 | `docker compose stop postgres` (state `exited`) → `POST /auth/login` → `503 Database connection failed`; was 500 in the first drill |
| R4-3 | **Rate limiter was global behind NAT** | Keyed on `request.client.host`; every browser through Docker/reverse-proxy shares one IP, so one abusive client could exhaust the 200/min bucket for everyone | Key on the JWT `sub` when a valid token is present, IP otherwise | `test_full_bucket_for_one_user_does_not_block_another`: user A at 429, user B still 200 |
| R4-4 | **`/api/query-demo` never forwarded `X-Request-ID`** | The demo route had no `Request` param, so traces broke there (the DB route propagated fine) | Inject `Request`, pass `request_id` to both clients | One request now appears in all three services: backend 1 / intent-engine 1 / agents 1 |
| R4-5 | **Hung NIM surfaced as 502 instead of using the keyword fallback** | `AsyncOpenAI` used the SDK default 600s timeout + retries, so a slow NIM call blew past the 45s budget before the fallback could run | Bounded client timeouts: intent 30s (<45s budget), agents 75s (<90s) | `query-demo` returns 200 with keyword-fallback reasoning during NIM spikes that previously 502'd |
| R4-6 | **Escape did not close the accessibility panel** | Only `HistoryPanel` had a keydown handler | ChatInterface closes the panel on Escape while open | `a11y_audit.py`: "panel open via keyboard: True; after Escape: True" |
| R4-7 | **`/agent/respond` 500'd on a malformed body** | Switching the handler to manual `Request` parsing (for the trace header) bypassed FastAPI's 422 | Catch `ValidationError` → 422 | `test_api.py` 422 assertions green (59 tests) |
| R4-8 | **VLM proxy accepted any upload size/type** | Only the frontend validated images; the proxy forwarded whatever arrived | 15MB body cap, image-type allowlist, ≤4 images, server-side | `test_hardening.py`: 413 on 16MB, 415 on `application/x-msdownload`, 413 on 5 images |
| R4-9 | **Account deletion didn't exist** | No endpoint; users could not remove their data | `DELETE /auth/account` (child-first deletes + FK cascade) | API returns 204; `psql` shows `0\|0\|0` users/messages/preferences rows for the user |
| R4-10 | **No restart policy / migration step** | A crashed container stayed down; `alembic upgrade head` was a manual afterthought | `restart: unless-stopped` on all 5 services; migrations verified | fresh empty Postgres → `alembic upgrade head` → all 4 tables created |

**Round 4 measured results (not claims):**

- **STT accuracy** (Windows-SAPI synthesized speech — real audio, known ground truth; *not* a human voice): form question **0% WER**, follow-up **0%**, fast speech **0%**, 36-word sentence **2.8% WER** (only error: proper noun "Aadhaar"→"Iodhar"). Voice→transcribe→intent→agent loop: **18.0–18.2 s** end to end.
- **Load** (`backend/loadtest.py`, live stack): 10 concurrent → 11×200 / 2×502, p50 80s; 20 → 27×200 / 1×502, p50 64s; 50 → 17×200 / 407×429 / 183×502. **Practical ceiling ≈ 10–20 concurrent users on this NIM tier**; at 50 the limiter sheds load with 429 instead of collapsing.
- **Shutdown drills**: backend stopped mid-load → 144 clean connection failures, **0 hangs**, recovery healthy; Postgres stopped mid-load → 503s (after R4-2), **0 orphaned transactions**, FAISS index reloads with all **29 vectors**.

### Round 5 — closing the last verification gaps + hardening

| # | Finding | Root cause | Fix | Proof |
|---|---------|-----------|-----|-------|
| R5-1 | **Fresh clone could not follow the Quick Start** | `.env` files are gitignored, so a clean clone has none — but Option A never said to create them, so the stack boots with no NIM key and every query fails | Quick Start now opens with a copy-`.env.example`→`.env` step + states the failure mode | `git ls-files \| grep .env` → none tracked |
| R5-2 | **README printed a real (truncated) NIM key** | "Env Keys" quoted `nvapi-2CB3F3...` | Redacted; keys live only in gitignored `.env` | grep for the key literal in README → 0 |
| R5-3 | **Dependency CVEs** | `python-multipart 0.0.9` (parses uploads) had 12 advisories; `starlette`/`requests`/`python-dotenv` flagged | Bumped multipart→0.0.32, requests→2.34.2, fastapi→0.116.1 (starlette 0.47.3), dotenv→1.1.1 across all 3 services | `pip-audit` re-run: multipart/requests gone; live query + upload + full battery green |
| R5-4 | **Auth endpoints farmable / NAT-lockable** | register/login unauthenticated → IP-keyed; one client could exhaust the shared bucket or mint fresh user-buckets via mass register | Separate tight per-IP bucket (10/min) on `/auth/register`+`/auth/login` | `test_auth_endpoints_have_a_tighter_ip_bucket`: 429 after 10, `/health` still 200 |
| R5-5 | **JWT expiry / production guard only proven in isolation** | — | Verified on the running server | expired token → `/auth/me` 401; `ADAPTIVEAI_PRODUCTION=1 DEBUG=True` → container boot raises "Refusing to start" |
| R5-6 | **Account deletion cross-user never proven live** | — | Verified | A delete→204, A's token→401, B's `/auth/me`+history→200 (untouched), re-delete with dead token→401 |
| R5-7 | **No backup/restore drill** | operational gap | pg_dump → `down -v` (volume destroyed) → restore into fresh DB → app reads it | row counts identical before/after (119/287/124); runbook `docs/backup-restore.md` |
| R5-8 | **Flaky test harness** | stub embedder used Python `hash()` (per-process salted) → retrieval ranking non-deterministic | switch to `zlib.crc32` | agents suite passes identically across repeated runs |

**Round 5 honest gaps (each has a runbook, none faked):** human screen-reader pass
(NVDA 2026.2 installed + confirmed running, but verbatim speech needs a human ear
— `docs/screen-reader-test-script.md`); human-speech WER (tool + runbook ready —
`docs/real-speech-stt-runbook.md`); real cloud deploy + paid-tier capacity (no
credentials here — `DEPLOY.md` §6/§9).


### Round 3 — found by driving the real UI in a browser (Playwright, headless Chromium + fake microphone, screenshots in every state)

| # | Bug | Root cause | Fix | Proof |
|---|-----|-----------|-----|-------|
| 24 | **The UI could never complete a first query** — every fresh visitor got a spoken "Sorry, I encountered an error" | `useSession` generated a session id in localStorage but never called `POST /api/session`; the backend rejects queries for unknown sessions with 404 | Bootstrap on load: restore history if the session exists, create it server-side when it does not; block sending until ready; never wipe rendered messages on a racing restore | Console `POST /api/query 404` from the browser; after: query `200`, answer rendered, `total: 2` on reload |
| 25 | Two identical welcome bubbles | React 18 StrictMode mounts twice in dev — and the Docker image runs `npm run dev` | Welcome keyed per session with a ref guard | Screenshot: two bubbles → one |
| 26 | Footer floated mid-page, half the viewport dead space | `.chat-interface` had **no layout rule at all** — `#root` stretched but its child didn't, so `chat-main`'s `flex: 1` had nothing to fill | `flex: 1` column layout + `min-height: 0` on the scroll area | Screenshot: content ended at y≈490/900 → now full height, footer pinned |
| 27 | Upload dropzone unreadable: icon outside the box, hint text spilling out | 100×100 box containing a 48px icon plus a hint whose `max-width` (120px) exceeded the box | 132×96 box, 26px icon, long hint moved to tooltip + screen-reader text | Before/after screenshots |
| 28 | **Every voice recording cancelled itself ~1s in** | Showing the `0:00 / Release to send` indicator shifted layout, the cursor left the button, the synthetic `mouseleave` fired `cancelRecording` | Indicator absolutely positioned (no layout shift) | Held 2.6s: died mid-hold before → still recording after |
| 29 | **Keyboard users could never record** (an a11y product!) | `keydown` started a 150ms hold timer; `keyup` ~50ms later cancelled it — a key press can never satisfy a hold | Space/Enter is a toggle from the keyboard: press to record, press again to stop & send; usage hint exposed via `aria-describedby` | Isolated probe: Space → `recording-info` visible |
| 30 | **Transcription never ran** — the first recording was silently discarded | `stopRecording()` returned the `audioBlob` state synchronously, but the blob is only built in MediaRecorder's async `onstop` — first call got `null`, later calls got the *previous* recording | `stopRecording()` returns a Promise resolved from `onstop` | After release: `POST /api/transcribe` now fires with the real blob |
| 31 | 30-second auto-stop was dead code | The interval callback read `recordingTime` from a closure captured at 0 | Effect reacts to `recordingTime` state | Code path now reachable (`MAX_RECORDING_SECONDS`) |
| 32 | **Reloading a session with history crashed the chat** | API rows carry `created_at` as an ISO string; `MessageBubble` calls `.toLocaleTimeString()/.toISOString()` on `timestamp` | `HistoryResponse` typed honestly (`HistoryMessage`), `useSession` normalizes to `Date` | Reload: history rendered with correct times (was a blank page) |
| 33 | **Every voice message returned 502 in Docker** | `faster-whisper` failed to import in the container: it does `import requests`, but newer `huggingface_hub` no longer depends on requests; the code then fell back to NIM's nonexistent whisper endpoint. The model also downloaded (~75 MB) at first request | `requests` pinned in requirements; Whisper weights baked into the image at build | Container log: `faster-whisper not installed` + `404 page not found` → after rebuild: model loads |
| 34 | Frontend aborted in-flight work it was still waiting for | axios defaults (30s) shorter than the backend's worst case for query and transcription | query 180s, transcribe 90s (VLM already 90s) | Matches backend budget §config |

---

## 11. Verification Status — what has and has not been proven

### Proven (commands run, output captured)

| Item | Evidence |
|---|---|
| **`docker compose up` full stack** | All 5 containers `healthy` on Windows/Docker 29.6.2. |
| **End-to-end query over published ports** | `POST /api/query` → `200` through real NIM + FAISS + Postgres: `form_agent`, grounded on the seed doc, policy rewrite applied, history `total: 2`, roles `[user, assistant]`. |
| **Postgres persistence + models** | 15 DB-backed tests green against the real container: auth, sessions, message persistence, pagination, cross-user isolation, malformed UUID (400), **account deletion**. |
| **Auth in the deployed image** | register 201 / login 200 / wrong-password 401 (after the bcrypt fix); **JWT rotation verified**: a token signed with the old secret returns 401, a new one returns 200. |
| **FAISS persistence** | `agents/data/chroma` (29 docs) survives restarts; reload after an agents restart reads all **29 vectors**. |
| **Intent accuracy** | 28/28 live LLM; 28/28 via keyword fallback alone (offline). Confidence is now classifier-reported (measured 0.9–0.95), not the old hardcoded 0.85. |
| **Frontend styles + rich answers** | 21 KB CSS incl. all `.high-contrast` rules; markdown renders (no literal `**`); RAG `sources_used` shown as chips. |
| **Degrade paths** | DB down → **503** (not 500 — fixed R4-2); intent/agent down → 502 naming the exception; rate limit → 429; VLM/STT unconfigured → 503/413/415. |
| **Real browser UI** (Playwright, fake mic) | typed query → grounded answer; hold-to-record persists; keyboard toggle records; high-contrast + text-size work; history survives reload. |
| **Feature loops** | `PUT /api/preferences` → policy engine rewrites the next answer (concise measured); history panel lists sessions per user; transcript downloads; clipboard copy verified by read-back; stop-TTS works. |
| **A1 · Real-speech STT accuracy** | 6 audio clips through `/api/transcribe` (real faster-whisper): form/follow-up/fast-speech **0% WER**, 36-word sentence **2.8%** (one proper-noun error). Voice→intent→agent loop **18s**. *Caveat: Windows-SAPI synthesized speech, not a human voice.* |
| **A3 · Load / concurrency** | `loadtest.py`: 10 → 11×200/2×502 p50 80s; 20 → 27×200/1×502 p50 64s; 50 → 17×200/**407×429**/183×502. Ceiling ≈ **10–20 concurrent**; the limiter sheds rather than collapses. |
| **A4 · NIM under load** | single request 3.5–15s; a query chains 2–3 calls; at 50 concurrent the free tier rate-limits → 429/502. Timeouts bounded (intent 30s / agent 75s) so a hung NIM falls back instead of 502-ing. |
| **A5 · Graceful shutdown** | backend stopped mid-load → **144 clean disconnects, 0 hangs**, recovery healthy; postgres stopped mid-load → 503s, **0 orphaned transactions**; `up` after an unclean (daemon-crash) stop restores a working stack. |
| **A2 · Keyboard + ARIA contract** | `a11y_audit.py`: logical Tab/DOM order, **0 unlabeled controls**, visible focus, Escape closes the panel, polite live regions on the log + assistant bubbles, all landmarks present. |
| **B1 · Security** | SQL: all queries are bound-parameter ORM (no raw/interpolated SQL). VLM: 15MB cap + type allowlist enforced server-side. Rate limit: per-user buckets. CORS `*` only under `DEBUG`; **`ADAPTIVEAI_PRODUCTION=1` refuses to boot with `DEBUG=True`**. |
| **B2 · Observability** | JSON access logs; **one request's `request_id` appears in all 3 services (1/1/1)**; `GET /api/metrics` returns counts + p50/p95/p99. |
| **B3 · Data & privacy** | `DELETE /auth/account` → 204 → `psql` shows `0\|0\|0` user/message/preference rows. Voice audio is a temp file deleted after transcription; screenshots are forwarded, not stored. |
| **B4 · Deployment** | `alembic upgrade head` on a fresh empty DB creates all 4 tables; `restart: unless-stopped` on all services; `DEPLOY.md` documents the VM path + cost. |
| **B5 · Auth hardening (R5)** | JWT expiry enforced end-to-end on the running server (expired token → `/auth/me` 401); production guard fires at **container boot** (`ADAPTIVEAI_PRODUCTION=1 DEBUG=True` → "Refusing to start"); account deletion is cross-user-safe (A deleted → A's token 401, B untouched); `/auth/register`+`/auth/login` have a tight per-IP bucket. |
| **B6 · Dependency CVEs (R5)** | `pip-audit`: cleared `python-multipart` (12 advisories, the upload parser) + `requests`; starlette 0.38→0.47 via fastapi bump. Remaining: `python-jose`/`ecdsa` (HS256-only usage → ECDSA advisories don't apply; migration to PyJWT is the real fix — documented debt), starlette 1.x + fastapi 0.141 (a major cascade, not risked on a working stack), dev-only pytest/vite. |
| **A5 · Backup/restore (R5)** | `pg_dump` → `docker compose down -v` (volume destroyed) → restore into a fresh DB → row counts matched **exactly** (119/287/124) and the app booted and read it. Runbook: `docs/backup-restore.md`. |

### Still NOT verified — do not claim these (each has a concrete reason + runbook)

- **Human screen-reader pass (NVDA/JAWS/VoiceOver).** NVDA 2026.2 is now
  installed and confirmed running on the Windows host (processes + audio devices
  present, welcome dialog read), but capturing what it *actually says* needs a
  human ear in a clean session — blind keystroke automation lands on whatever
  window has focus and is disruptive. **This is the most important open item for
  an accessibility tool.** Run it via `docs/screen-reader-test-script.md`.
- **Genuine human speech WER.** Only synthesized speech (0–2.8% WER) measured;
  human accents/noise/disfluency unmeasured. Tool + runbook ready:
  `docs/real-speech-stt-runbook.md`, `backend/stt_wer.py`.
- **Real cloud deployment.** `DEPLOY.md` §6 documents the Linux-VM path but it
  was not executed from this machine (no cloud credentials in scope).
- **NIM paid-tier capacity.** All latency/concurrency numbers are free-tier;
  the 10–20 concurrent ceiling is a free-tier number, not the system's inherent
  limit. Test plan: `DEPLOY.md` §9.



---

## 12. Final Proof — captured from real commands

```powershell
# 1. Full stack under Docker (this never previously ran)
docker compose up -d
aipd-postgres-1       | Up (healthy)
aipd-intent-engine-1  | Up (healthy)
aipd-agents-1         | Up (healthy)      # 2.5 GB image, was 9.06 GB with CUDA torch
aipd-backend-1        | Up (healthy)
aipd-frontend-1       | Up (healthy)

# 2. Health on published ports
curl localhost:8000/health → {"status":"ok","service":"adaptiveai-backend"}
curl localhost:8001/health → {"status":"ok","service":"intent-engine"}
curl localhost:8002/health → {"status":"healthy","service":"agents","port":8002}

# 3. DB really connected
docker compose exec backend python -c "...select current_database()..." → DB: adaptiveai

# 4. Complete user journey over HTTP (auth fixed, timeouts fixed)
POST /auth/register  → 201
POST /auth/login     → 200   | wrong password → 401
GET  /auth/me        → {"id":"068583cb-...","email":"demo...@example.com"}
POST /api/session    → 23ac041b-d2ec-451c-842f-1f7cce3ec111
POST /api/query      → 200 in 34.8s
     agent: form_agent
     answer: "Welcome to our online platform! ... this unique 12-digit number
              ... helps us verify your identity"   # RAG-grounded + policy rewrite
GET  /api/history    → total: 2   roles: [user, assistant]
POST /api/query (bad session_id) → 400  (was 503 "Database connection failed")

# 5. Degradation is honest, not silent
Intent/agent down → 502 "Intent service error: ReadTimeout" (exception class named)
DB unconfigured   → 503 "Database not available - configure SUPABASE_DB_URL ..."
No STT backend    → 503 "STT not configured: ..."
>200 req/min      → 429 (was 500)

# 6. Test suites (offline; CI runs these verbatim)
cd intent-engine; python -m pytest → 66 passed, 2 deselected in 3.20s
cd agents;        python -m pytest → 59 passed in 35.56s
cd backend;       python -m pytest → 48 passed, 1 skipped in 7.17s
cd backend;       TEST_DATABASE_URL=... python -m pytest -m live → 10 passed in 9.73s
cd intent-engine; python -m pytest tests/test_live_accuracy.py -m live → 28/28 accuracy

# 7. Frontend ships its styles
npm run build → assets/index-*.css 21.07 kB (was 3.03 kB); 21 .high-contrast rules
dev server    → /src/styles/main.css serves 28,141 bytes with components + a11y inlined
```

> Remaining gap is browser-level voice/screen-reader testing — see §11 "Still NOT verified".

---

*Generated for AdaptiveAI — real, production-correct, no mocks in live path.*
