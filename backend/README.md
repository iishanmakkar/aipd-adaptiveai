# AdaptiveAI Backend (Module 4 - Ishan)

Backend API, Database, Policy Engine & Integration for AdaptiveAI.

## Architecture

```
Frontend (React/Vite, port 3000)
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
- Mock Intent Service on http://localhost:8001
- Mock Agent Service on http://localhost:8002

### 3. Run Locally (without Docker)

```bash
cd backend
pip install -r requirements.txt

# Terminal 1: Mock Intent
uvicorn app.mocks.mock_intent:app --reload --port 8001

# Terminal 2: Mock Agent
uvicorn app.mocks.mock_agent:app --reload --port 8002

# Terminal 3: Backend
uvicorn app.main:app --reload --port 8000
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
  "confidence": 0.87
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

Located at `app/services/policy_engine.py`. Adjusts agent responses based on:
1. **Clarifying questions** (≥3 in recent history → simplify)
2. **Verbosity preference** (concise/standard/detailed)
3. **First-time user** (<3 messages → add orientation)

Uses NVIDIA NIM (OpenAI-compatible) for LLM rewrites.

## Database Schema

- `users` - email, hashed_password
- `sessions` - user_id, context (JSON)
- `messages` - session_id, role, content, agent_used, meta (JSON)
- `preferences` - user_id, verbosity_level, voice_speed

Migrations via Alembic: `alembic upgrade head`

## Replacing Mocks with Real Services

When teammates complete their services:

1. **Kakul's Intent Engine**: Replace `mock-intent` in docker-compose.yml with `build: ./intent-engine`
2. **Kartik's Agents**: Replace `mock-agent` in docker-compose.yml with `build: ./agents`
3. Update `INTENT_SERVICE_URL` and `AGENT_SERVICE_URL` in backend `.env`

No code changes needed in backend - contracts are fixed.

## Testing

```bash
# Test mocks
cd backend
python test_integration.py

# Run backend tests (when added)
pytest
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
| FRONTEND_URL | No | Default: http://localhost:3000 |