# Intent & Context Engine (Module 2 - Kakul)

FastAPI service for classifying user intent and selecting the appropriate task agent.

## Architecture

```
User Input + Screen Context + History
         │
         ▼
┌────────────────────────┐
│  LLM Classifier (NIM)  │  ──► intent + target_agent + entity + reasoning
│  Keyword Fallback      │
└────────────────────────┘
         │
         ▼
Session Memory (in-memory, last 5 turns)
```

## Intent Categories -> Agents

Thirteen intents (the pattern is pinned in `app/schemas.py`, 2026-10-24):

| Intent | Target Agent | Description |
|--------|--------------|-------------|
| `form_help` | `form_agent` | Form field explanations, filling help |
| `document_help` | `document_agent` | Document summarization, Q&A |
| `web_navigation_help` | `web_agent` | Website navigation, UI explanation |
| `education_help` | `education_agent` | Educational concept explanations |
| `general_query` | `general_agent` | Greetings, unclear queries |
| `browser_inspect` | `browser_agent` | Ask about the open live page (read-only) |
| `browser_act` | `browser_agent` | Act on the open live page (gated) |
| `ui_help` | `ui_adjuster_agent` | Contrast/font/layout/focus changes |
| `content_explain` | `content_explainer_agent` | Explain the current screen simply |
| `profile_update` | `profile_updater_agent` | Store/change disability preferences |
| `navigation_help` | `navigation_agent` | Find a place or next step |
| `scheduler_help` | `scheduler_agent` | Reminders and time-shaped requests |
| `translation_help` | `translator_agent` | Translate/explain in another language |

`browser_*` routing is gated on the backend's own `Live page:` marker (anchored
to a line start) - page text cannot mint it.

## API

### POST /intent/classify

**Request:**
```json
{
  "session_id": "uuid",
  "input_text": "What is this field asking for?",
  "screen_context": "form with fields: Name, DOB, Address",
  "history": ["User: I want to fill this form", "System: Classified as form_help"]
}
```

**Response:**
```json
{
  "intent": "form_help",
  "target_agent": "form_agent",
  "extracted_entity": "Permanent Address field",
  "reasoning": "User asking about specific form field, screen context shows form",
  "confidence": 0.9,
  "confidence_source": "llm",
  "ambiguous": false
}
```

`confidence_source` says who produced the number (`llm` or `keyword`); it is
never a constant. `ambiguous` is true when a keyword no-match (0.3) needs one
clarifying question instead of a guess.

### GET /intent/session/{session_id}/history
Get conversation history for a session.

### DELETE /intent/session/{session_id}
Clear session history.

### GET /health
Liveness probe (`{"status": "ok", "service": "intent-engine"}`).

## Quick Start

### 1. Environment Setup
```bash
cd intent-engine
cp .env.example .env
# Edit .env with your NIM_API_KEY
```

### 2. Run Locally
```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8001
```

### 3. Run with Docker
```bash
docker build -t adaptiveai-intent .
docker run -p 8001:8001 --env-file .env adaptiveai-intent
```

## Testing

```bash
# 135 tests as of 2026-10-24 - offline, no API key
python -m pytest

# Live accuracy against the running service + real NIM (spends quota):
python -m pytest tests -m live
```

The 48 shared classification cases (34 plain, 8 context, 6 browser) live in
`tests/cases.py`, used by both the
offline keyword tests and the live runner. The old `tests/test_classifier.py`
(which collected zero tests) was deleted; pytest is the entry point.

Rate limit: 60 requests/minute per client IP (429 above it). `X-Forwarded-For`
is honoured only when `TRUST_PROXY_HEADERS=1` says a trusted proxy overwrites
it; the default key is the socket peer, because the first XFF hop is
client-supplied.

## Integration

The backend (Ishan's service, port 8000) calls this service at:
- `INTENT_SERVICE_URL` (default: http://localhost:8001)
- Endpoint: `POST /intent/classify`

No code changes needed in backend when this service is ready - just update the URL in docker-compose.yml.

## Key Features

1. **LLM-based classification** using NVIDIA NIM (OpenAI-compatible)
2. **Keyword fallback** - never fails, always returns a classification
3. **Session context memory** - last 5 turns per session_id, TTL/LRU bounded,
   with a per-session turn lock so concurrent turns cannot drop each other
4. **Screen context awareness** - uses VLM description from frontend
5. **Configurable** via environment variables