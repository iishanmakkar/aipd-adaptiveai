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

## Intent Categories → Agents

| Intent | Target Agent | Description |
|--------|--------------|-------------|
| `form_help` | `form_agent` | Form field explanations, filling help |
| `document_help` | `document_agent` | Document summarization, Q&A |
| `web_navigation_help` | `web_agent` | Website navigation, UI explanation |
| `education_help` | `education_agent` | Educational concept explanations |
| `general_query` | `general_agent` | Greetings, unclear queries |

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
  "reasoning": "User asking about specific form field, screen context shows form"
}
```

### GET /intent/session/{session_id}/history
Get conversation history for a session.

### DELETE /intent/session/{session_id}
Clear session history.

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
# Run accuracy test (requires service running on port 8001)
cd tests
python test_classifier.py
```

Expected output: 80%+ accuracy on 20+ test cases.

## Integration

The backend (Ishan's service, port 8000) calls this service at:
- `INTENT_SERVICE_URL` (default: http://localhost:8001)
- Endpoint: `POST /intent/classify`

No code changes needed in backend when this service is ready - just update the URL in docker-compose.yml.

## Key Features

1. **LLM-based classification** using NVIDIA NIM (OpenAI-compatible)
2. **Keyword fallback** - never fails, always returns a classification
3. **Session context memory** - last 5 turns per session_id for follow-up resolution
4. **Screen context awareness** - uses VLM description from frontend
5. **Configurable** via environment variables