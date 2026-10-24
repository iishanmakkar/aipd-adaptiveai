# AdaptiveAI Backend (Module 4 - Ishan)

Backend API, Database, Policy Engine & Integration for AdaptiveAI.

## Architecture

```
Frontend (React/Vite, port 5173)
    │
    ▼
Backend API (FastAPI, port 8000) ◄──► PostgreSQL (Supabase/Neon)
    │
    ├──► Intent & Context Engine (port 8001) - Kakul's service
    └──► Task Agents + RAG (port 8002) - Kartik's service
```

## Quick Start

### 1. Environment Setup

```bash
cd backend
cp .env.example .env
# Edit .env with your values:
# - SUPABASE_DB_URL (from Supabase/Neon)
# - JWT_SECRET (generate: openssl rand -hex 32)
# - NIM_API_KEY (from NVIDIA NIM)
```

### 2. Run with Docker Compose (Recommended)

```bash
# From repo root
docker-compose up --build
```

This starts:
- Backend API on http://localhost:8000
- Real Intent Engine on http://localhost:8001
- Real Agents + RAG on http://localhost:8002
- Browser agent (real Playwright Chromium) on http://localhost:8003
- Postgres on localhost:5433 (host) -> 5432 (container)
- Redis on localhost:6379 (TTL shared store)
- Frontend on http://localhost:5173

### 3. Run Locally (without Docker)

```bash
cd backend
pip install -r requirements.txt

# Terminal 1: Intent Engine (real)
cd ../intent-engine; uvicorn app.main:app --reload --port 8001

# Terminal 2: Agents + RAG (real)
cd ../agents; uvicorn main:app --reload --port 8002

# Terminal 3: Backend
cd ../backend; uvicorn app.main:app --reload --port 8000
```

## API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/register` | Register new user |
| POST | `/auth/login` | Login, returns JWT |
| GET | `/auth/me` | Get current user |

### Sessions
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/session` | Create new session |
| GET | `/api/history/{session_id}` | Get message history (paginated) |

### Main Query (Orchestration)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/query` | Process user query through full pipeline |
| POST | `/api/query-demo` | Same pipeline without the browser turns (demo) |

### Browser, forms and monitoring
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/form-fill` | Discover -> cache -> replay -> heal in live Chromium |
| POST | `/api/page-context` | Read a public page (title, fields, VLM description) |
| POST | `/api/monitor/start`, `/stop`, `/status`, `/events` | Round 9 change narration for the live session |

### Voice, vision, accessibility, sharing
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/transcribe` | multipart audio -> `transcript` (422 on silence) |
| POST | `/v1/chat/completions` | NIM vision proxy (server-side key, image required) |
| GET | `/v1/models` | Vision models this proxy allows |
| POST | `/api/alt/braille` | Shaped 40-cell lines + Grade-1 Unicode braille |
| POST | `/api/share`, `GET /api/share/{token}`, `POST /api/share/{token}/annotate` | Caregiver read-only transcript + notes |
| POST | `/api/behavior-event` | Replay/skip/listen signals feeding policy Rule 5 |
| GET/PUT | `/api/preferences` | Verbosity, voice speed, disability profile, complexity |
| GET | `/api/sessions`, `GET /api/history/{session_id}` | Session list + paginated history |
| GET | `/api/metrics` | Request counters |
| POST | `/api/extension/step` | The MV3 extension's planner: structure in, one step out |
| DELETE | `/auth/account` | Deletes the account and its rows (204) |

Full live inventory: `GET /openapi.json` (27 paths as of 2026-10-24).

#### `/api/query` Request
```json
{
  "session_id": "uuid",
  "input_text": "What is this field asking for?",
  "input_source": "text",
  "screen_context": "optional VLM description"
}
```

#### `/api/query` Response
```json
{
  "response_text": "This field asks for your permanent address...",
  "agent_used": "form_agent",
  "suggested_action": "highlight_field",
  "confidence": 0.87,
  "confidence_source": "llm",
  "sources_used": ["form_permanent_address"]
}
```

## Service Contracts (Source of Truth)

### Backend → Intent Service (port 8001)
```
POST /intent/classify
Request:  { session_id, input_text, screen_context, history }
Response: { intent, target_agent, extracted_entity, reasoning }
```

### Backend → Agent Service (port 8002)
```
POST /agent/respond
Request:  { session_id, agent, query, entity, extra_context }
Response: { answer, sources_used, suggested_action }
```

## Policy Engine

Located at `app/services/policy_engine.py`. Adjusts agent responses by priority:
1. **Rule 1** - high confusion (>=3 clarifying questions -> simplify)
2. **Rule 2** - disability profile + language complexity + verbosity (always applies)
3. **Rule 3** - verbosity folded into Rule 2 (no longer reachable alone)
4. **Rule 4** - first-time user (<3 messages -> add orientation)
5. **Rule 5** - observed behavior (lowest priority, defaults only; explicit prefs win)

Uses NVIDIA NIM (OpenAI-compatible) for LLM rewrites.

## Database Schema

- `users` - email, hashed_password
- `sessions` - user_id, context (JSON)
- `messages` - session_id, role, content, agent_used, meta (JSON, indexed)
- `preferences` - user_id, verbosity_level, voice_speed, disability_profile, language_complexity
- `behavior_signals` - replay/skip/listen signals (policy Rule 5)

Migrations via Alembic: `alembic upgrade head` (four revisions: initial,
disability_profile, behavior_signals, history_indexes).

## Service Wiring (all real — the mock ecosystem was deleted)

`INTENT_SERVICE_URL` and `AGENT_SERVICE_URL` in `backend/.env` point at the real
services (`http://localhost:8001` / `8002` locally, `http://intent-engine:8001` /
`http://agents:8002` in Docker). No code changes needed — contracts are fixed
(see root `README.md` §4).

## Testing

```bash
# Offline unit suite (no services, no API key) - 253 tests as of 2026-10-24
cd backend
pytest

# Against real Postgres (see root README.md §7 for TEST_DATABASE_URL)
pytest -m live
```

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| SUPABASE_DB_URL | Yes | PostgreSQL connection string |
| JWT_SECRET | Yes | Min 32 chars, generate with `openssl rand -hex 32` |
| NIM_API_KEY | Yes | NVIDIA NIM API key |
| NIM_BASE_URL | No | Default: https://integrate.api.nvidia.com/v1 |
| NIM_MODEL | No | Default: nvidia/llama-3.1-nemotron-70b-instruct |
| INTENT_SERVICE_URL | No | Default: http://localhost:8001 |
| AGENT_SERVICE_URL | No | Default: http://localhost:8002 |
| FRONTEND_URL | No | Default: http://localhost:5173 |