# AdaptiveAI — Task Agents + RAG Service

Kartik Bareja's module: **Task Agents + RAG Knowledge Base** (Port 8002)

Generates grounded, task-specific answers for visually impaired users using retrieval-augmented generation.

## Architecture

```
POST /agent/respond
    │
    ├── Retrieves top-3 relevant docs from FAISS
    ├── Builds prompt with query + retrieved context
    ├── Calls LLM (OpenAI/Anthropic, configurable)
    └── Returns answer + sources_used + suggested_action
```

## Agents

| Agent | Purpose | Example |
|-------|---------|---------|
| `form_agent` | Explain form fields in plain language | "Permanent Address = your ID-proof address" |
| `document_agent` | Answer questions about uploaded document text | "What's the deadline in this brochure?" |
| `web_agent` | Explain webpage element purpose/navigation | "What does the Submit button do?" |
| `education_agent` | Simplify/explain educational concepts | "Explain photosynthesis simply" |
| `general_agent` | Fallback for general queries | "Hello, how can you help?" |

## Quick Start

### 1. Install Dependencies
```bash
cd agents
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file:
```bash
# Choose one:
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=sk-your-openai-key

# OR
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-haiku-20240307
LLM_API_KEY=sk-ant-your-anthropic-key
```

### 3. Run Service
```bash
uvicorn main:app --port 8002 --reload
```

Service runs at `http://localhost:8002`

## API Contract

### Request
```json
{
  "session_id": "abc123",
  "agent": "form_agent",
  "query": "What is this field asking for?",
  "entity": "Permanent Address field",
  "extra_context": "form with fields: Name, DOB, Permanent Address, Aadhaar Number"
}
```

### Response
```json
{
  "answer": "This field asks for your permanent address as listed on your ID proof (Aadhaar/Passport), not your current residence.",
  "sources_used": ["form_permanent_address"],
  "suggested_action": "highlight_field"
}
```

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| GET | `/agents` | List available agents |
| POST | `/agent/respond` | Main agent endpoint |

## Knowledge Base (RAG)

- **Vector DB**: FAISS (persistent, file-based at `./data/chroma`)
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local, no API key)
- **Seed Documents**: 20 documents
  - 10 Form-field glossary entries (permanent_address, aadhar_number, pan_number, etc.)
  - 10 Accessibility FAQ entries (screen_reader_navigation, keyboard_only_forms, etc.)

## Testing

### Run Pipeline Validation (no API key required)
```bash
python tests/run_pipeline_test.py
```

This validates the full RAG + Agent pipeline using a mock LLM.

### Run Full Test Suite (requires LLM API key)
```bash
python -m tests.run_tests
```

Outputs:
- Console summary with pass/fail per test
- JSON report: `test_results_YYYYMMDD_HHMMSS.json`

### Test Coverage
- **form_agent**: 10 queries (field explanations, formats, examples)
- **document_agent**: 10 queries (summarization, extraction, facts)
- **web_agent**: 10 queries (navigation, elements, interactions)
- **education_agent**: 10 queries (concepts, examples, comparisons)
- **general_agent**: 2 queries (greeting, capabilities)

## Development

### Project Structure
```
agents/
├── main.py                 # FastAPI app (port 8002)
├── config.py               # Settings (env-configurable)
├── requirements.txt        # Dependencies
├── .env                    # Local config (not committed)
├── .env.example            # Example config template
├── agents/
│   ├── base.py             # BaseAgent abstract class
│   ├── form_agent.py       # Form field explainer
│   ├── document_agent.py   # Document Q&A
│   ├── web_agent.py        # Web navigation explainer
│   ├── education_agent.py  # Concept simplifier
│   ├── general_agent.py    # Fallback agent
│   └── registry.py         # Agent factory
├── rag/
│   ├── vector_store.py     # FAISS wrapper
│   ├── embeddings.py       # Sentence-transformers wrapper
│   ├── seed_data.py        # 20 seed documents
│   └── retriever.py        # Top-k retrieval + formatting
├── llm/
│   ├── client.py           # OpenAI/Anthropic client
│   ├── mock_client.py      # Mock LLM for testing
│   └── prompts.py          # Agent system prompts
├── schemas/
│   ├── request.py          # AgentRespondRequest
│   └── response.py         # AgentRespondResponse
└── tests/
    ├── test_queries.py     # 40+ test cases
    ├── run_tests.py        # Test runner (requires LLM API key)
    └── run_pipeline_test.py # Pipeline validation (no API key)
```

### Adding Seed Documents
Edit `rag/seed_data.py` and restart service (auto-reloads on startup).

### Adding New Agent
1. Create `agents/new_agent.py` extending `BaseAgent`
2. Add system prompt to `llm/prompts.py`
3. Register in `agents/registry.py`

## Integration

Called by Ishan's Backend (Port 8000) after Kakul's Intent Engine (Port 8001) selects the agent.

```
Frontend (8080) → Backend (8000) → Intent Engine (8001) → Agents (8002)
```

## Notes

- **Prototype system** — designed to demonstrate the architecture; production hardening needed
- **LLM costs** — each query makes 1 LLM call; monitor usage
- **Offline embeddings** — sentence-transformers runs locally, no API cost
- **FAISS persistence** — survives restarts in `./data/chroma`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `LLM_API_KEY not set` | Add to `.env` or export in shell |
| `FAISS error` | Delete `./data/chroma` and restart |
| `Import errors` | Run `pip install -r requirements.txt` |
| `Slow first request` | Embedding model loads on first use (~5s) |
| `HF Hub connection error` | Set `HF_TOKEN` or use `HF_HUB_DISABLE_SYMLINKS_WARNING=1` |