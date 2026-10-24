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

Eleven agents (verified from `AgentRegistry.__init__`, 2026-10-24):

| Agent | Purpose | Example |
|-------|---------|---------|
| `form_agent` | Explain form fields in plain language | "Permanent Address = your ID-proof address" |
| `document_agent` | Answer questions about uploaded document text | "What's the deadline in this brochure?" |
| `web_agent` | Explain webpage element purpose/navigation | "What does the Submit button do?" |
| `education_agent` | Simplify/explain educational concepts | "Explain photosynthesis simply" |
| `general_agent` | Fallback for general queries | "Hello, how can you help?" |
| `ui_adjuster_agent` | Suggest contrast/font/layout/focus adjustments | "Make this easier to read" |
| `content_explainer_agent` | Explain what is on screen in simpler language | "What does this page say?" |
| `profile_updater_agent` | Update the stored disability profile/preferences | "Remember that I am blind" |
| `navigation_agent` | Find a place/step on the page or site | "Where is the checkout button?" |
| `scheduler_agent` | Time/reminder-shaped requests | "Remind me at 5pm" |
| `translator_agent` | Translate/explain in another language | "Say that in Hindi" |

## Quick Start

### 1. Install Dependencies
```bash
cd agents
pip install -r requirements.txt
```

### 2. Configure Environment
Create `.env` file:
```bash
LLM_PROVIDER=nim
LLM_MODEL=meta/llama-3.2-11b-vision-instruct
NIM_API_KEY=nvapi-your-nvidia-key
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
| GET | `/agents` | List the 11 live agents |
| POST | `/agent/respond` | One agent answers (validated 422, upstream failures 5xx) |
| POST | `/agent/orchestrate` | Natural-language goal -> LLM route with keyword fallback -> specialist + plan |

## Knowledge Base (RAG)

- **Vector DB**: FAISS (persistent, file-based at `./data/chroma`); falls back to a
  numpy exact-inner-product index when Windows Smart App Control blocks the faiss DLL
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2` (local, no API key)
- **Seed Documents**: **34** documents in 7 categories (form glossary 10,
  accessibility FAQ 10, education 4, document guides 3, language guides 3,
  web navigation 2, productivity 2) grounding all 11 agents — no agent answers
  ungrounded. Count is pinned by `tests/test_contracts_and_seed.py`.

## Testing

### Run Offline Suite (no API key required)
```bash
python -m pytest   # 103 tests as of 2026-10-24: FAISS store, registry (11 agents),
                   # API contract, prompt contracts (untrusted-context fencing),
                   # orchestrator, seed grounding
```

Offline tests use in-process stubs (test isolation). The mock LLM client was
deleted; real-LLM accuracy runs via:

```bash
python tests/run_tests.py   # 40+ real-LLM queries -> test_results.json (spends NIM quota)
```

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
│   ├── base.py             # BaseAgent: retrieval, fenced prompts, single-pass slots
│   ├── form_agent.py       # Form field explainer
│   ├── document_agent.py   # Document Q&A
│   ├── web_agent.py        # Web navigation explainer
│   ├── education_agent.py  # Concept simplifier
│   ├── general_agent.py    # Fallback agent
│   ├── ui_adjuster_agent.py / content_explainer_agent.py /
│   │   profile_updater_agent.py / navigation_agent.py /
│   │   scheduler_agent.py / translator_agent.py
│   ├── orchestrator.py     # Goal -> route -> plan (POST /agent/orchestrate)
│   └── registry.py         # Agent factory (11 agents)
├── rag/
│   ├── vector_store.py     # FAISS wrapper (+ numpy exact-IP fallback)
│   ├── embeddings.py       # Sentence-transformers wrapper
│   ├── seed_data.py        # 34 seed documents / 7 categories
│   └── retriever.py        # Top-k retrieval + formatting
├── llm/
│   ├── client.py           # OpenAI-compatible client (NIM) + Anthropic
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
Frontend (5173) → Backend (8000) → Intent Engine (8001) → Agents (8002)
```

## Notes

- **Prototype system** — hardened for auth/rate limits/degradation, but not a commercial SLA
- **LLM costs** — each query makes 1 LLM call; monitor usage
- **Offline embeddings** — sentence-transformers runs locally, no API cost
- **FAISS persistence** — survives restarts in `./data/chroma`

## Troubleshooting

| Issue | Fix |
|-------|-----|
| `LLM_API_KEY not set` / `NIM_API_KEY not set` | Add to `.env` or export in shell |
| `FAISS error` | Delete `./data/chroma` and restart |
| `Import errors` | Run `pip install -r requirements.txt` |
| `Slow first request` | Embedding model loads on first use (~5s) |
| `HF Hub connection error` | Set `HF_TOKEN` or use `HF_HUB_DISABLE_SYMLINKS_WARNING=1` |