# AdaptiveAI — Feature Enhancement Plan (from Competitive Analysis)

Based on analysis of 7 similar projects: VoxSurf, PhysiologicAILab, AURA, yuktai, Granite Assistant, Google NAI, AdaptAble.

---

## Phase 1: High-Impact / Low-Effort (Week 1-2)

### 1.1 Disability Profiles (from Granite Assistant, AURA, PhysiologicAILab)
**Add to:** `backend/app/schemas/preference.py` + `backend/app/models/preference.py` + `frontend/src/types/accessibility.ts`

```python
# New enum in backend
class DisabilityProfile(str, Enum):
    BLIND = "blind"
    LOW_VISION = "low_vision"
    COGNITIVE = "cognitive"
    MOTOR = "motor"
    NONE = "none"

# Preference model additions
disability_profile: DisabilityProfile = DisabilityProfile.NONE
verbosity_level: VerbosityLevel = VerbosityLevel.STANDARD  # existing
speech_rate: float = 1.0  # existing (voice_speed)
language_complexity: Literal["simple", "standard", "technical"] = "standard"
```

**Policy Engine rules** (backend/app/services/policy_engine.py):
- `blind` → "Respond with clear step-by-step verbal instructions. Avoid visual references."
- `low_vision` → "High contrast descriptions, larger font references"
- `cognitive` → "Simple language, short steps, no jargon"
- `motor` → "Minimize required interactions, voice-first"

### 1.2 Behavior-Adaptive Parameters (from AURA, yuktai)
**Add tracking** in `backend/app/services/policy_engine.py`:

```python
# Track per-session (in-memory + persist to Message.meta)
behavior_signals = {
    "replay_count": 0,      # user asked "repeat" or replayed TTS
    "skip_count": 0,        # user interrupted/cancelled TTS
    "avg_listen_time": 0.0, # seconds per response
}
# Adjust verbosity/speech_rate/complexity in real-time
```

### 1.3 In-Browser RAG (from yuktai, Granite Assistant)
**Add to frontend:** `frontend/src/hooks/useInTabRAG.ts`
- Use Transformers.js (DistilBERT/flan-t5-small) for offline embeddings
- Index current page DOM + chat history
- "Ask this page" button in ChatInterface
- Falls back to backend RAG when online

---

## Phase 2: Core Architecture Enhancements (Week 3-4)

### 2.1 Specialized Agent Orchestrator (from VoxSurf, Google NAI, PhysiologicAILab)
**Current:** Single `POST /agent/respond` with `agent` literal
**New:** Orchestrator agent that routes to specialists

```
Orchestrator (NEW)
├── FormAgent (existing)
├── DocumentAgent (existing)
├── WebAgent (existing)
├── EducationAgent (existing)
├── GeneralAgent (existing)
├── UIAdjusterAgent (NEW) — adjusts frontend: contrast, font, layout, focus
├── ContentExplainerAgent (NEW) — explains screen content in simple language
├── ProfileUpdaterAgent (NEW) — manages disability profile + preferences
└── NavigationAgent (NEW) — "go to checkout", "find contact form"
```

**Implementation:**
- `agents/agents/orchestrator.py` with LLM-based routing
- `POST /agent/orchestrate` accepts natural language goal → returns plan + executes
- Frontend: "Autonomous mode" toggle in ChatInterface

### 2.2 Multimodal Context Fusion (from VoxSurf, Google NAI)
**Current:** `screen_context` string passed separately
**New:** Unified context object

```typescript
// frontend/src/types/api.ts
interface UnifiedContext {
  screen_text: string;           // OCR/extracted text
  dom_snapshot: string;          // simplified DOM
  screenshot_b64?: string;       // compressed image
  vlm_description?: string;      // from VLM
  user_intent?: string;          // from intent engine
  disability_profile: DisabilityProfile;
  behavior_signals: BehaviorSignals;
}
```

### 2.3 Session Memory with TTL + LRU (fixes known issue #10, #20)
**Current:** Unbounded `_session_memory` dict
**New:** `backend/app/services/session_memory.py` (or intent-engine)

```python
class SessionMemory:
    max_sessions: int = 1000
    session_ttl_seconds: int = 3600
    max_turns_per_session: int = 5
    
    # LRU eviction + TTL cleanup on access
    # Persist to Redis/Postgres for multi-instance
```

---

## Phase 3: Accessibility-First Features (Week 5-6)

### 3.1 Screen Reader Optimization (from all projects)
- **Frontend:** ARIA live regions for every agent response
- **Frontend:** `role="status"` for "Thinking...", "Listening..."
- **Frontend:** Skip links, heading structure (h1→h2→h3)
- **Backend:** Response formatting per disability profile:
  - `blind`: Numbered steps, no "click here", spatial descriptions
  - `cognitive`: Max 2 clauses/sentence, bullet points
  - `low_vision`: High-contrast color references, size descriptors

### 3.2 Voice-First Navigation (from VoxSurf, AdaptAble, yuktai)
**Add to frontend:**
- `useVoiceCommands.ts` hook: "go back", "read that again", "bigger text", "high contrast"
- Wake word detection (optional, privacy-first)
- Command palette (Cmd+K) with voice search

### 3.3 Form Autofill + Guidance (from VoxSurf, Granite Assistant)
**New Agent capability:** `FormAgent.handle()` returns:
```python
{
  "answer": "...",
  "sources_used": [...],
  "suggested_action": "highlight_field",
  "field_actions": [  # NEW
    {"field_id": "email", "action": "fill", "value": "user@example.com"},
    {"field_id": "dob", "action": "explain", "text": "Format: DD/MM/YYYY"}
  ],
  "form_progress": {"completed": 3, "total": 8, "next_field": "phone"}
}
```

---

## Phase 4: Advanced / Differentiators (Week 7-8)

### 4.1 Offline-First Mode (from yuktai, Granite Assistant)
- Service Worker caches all static assets
- IndexedDB stores: session history, preferences, RAG index
- Transformers.js models cached (flan-t5-small ~30MB)
- Queue mutations (queries, preference changes) → sync when online

### 4.2 Real-Time Collaboration (from Google NAI curb-cut effect)
- Shared session URL → caregiver/assistant can see same view
- "Watch mode" — read-only view of user's chat + screen context
- Annotations: helper highlights field → user gets voice notification

### 4.3 Braille Display Support (from Granite Assistant)
- Structured response format maps to Braille displays
- `backend/app/services/braille_formatter.py`
- Test with `brlapi` / virtual Braille display

### 4.4 Sign Language Avatar (from Granite Assistant, Google Grammar Lab)
- Frontend: Three.js avatar component (optional load)
- Backend: Response → HamNoSys/SiGML → avatar animation
- Start with ASL fingerspelling for key terms

---

## Technical Debt to Address First

| Issue | Source | Fix |
|-------|--------|-----|
| Unbounded session memory | Round 1 #10, #20 | Phase 2.3 |
| No Redis for multi-instance | Docker compose | Add Redis service |
| Single NIM key (vision only) | README R3 | Document limitation; add OpenAI/Anthropic fallback |
| No load test in CI | CI only runs offline | Add `backend/loadtest.py` to CI (small scale) |
| Frontend bundle size | 230KB JS | Code-split agents, lazy-load Transformers.js |

---

## Implementation Priority Matrix

| Feature | User Impact | Dev Effort | Dependencies | Phase |
|---------|-------------|------------|--------------|-------|
| Disability profiles | ⭐⭐⭐⭐⭐ | Low | None | 1.1 |
| Behavior adaptation | ⭐⭐⭐⭐ | Medium | Policy engine | 1.2 |
| In-tab RAG | ⭐⭐⭐⭐ | High | Transformers.js | 1.3 |
| Orchestrator agent | ⭐⭐⭐⭐⭐ | High | All agents | 2.1 |
| Multimodal context | ⭐⭐⭐⭐ | Medium | VLM + DOM | 2.2 |
| Session memory fix | ⭐⭐⭐ | Low | None | 2.3 |
| Screen reader opt | ⭐⭐⭐⭐⭐ | Medium | Frontend only | 3.1 |
| Voice commands | ⭐⭐⭐⭐ | Medium | Web Speech API | 3.2 |
| Form autofill | ⭐⭐⭐⭐ | High | FormAgent + FE | 3.3 |
| Offline mode | ⭐⭐⭐ | High | SW + IndexedDB | 4.1 |
| Braille/Sign | ⭐⭐⭐ | Very High | Hardware/lib | 4.3/4.4 |

---

## Metrics to Track

| Metric | Target | Measurement |
|--------|--------|-------------|
| Time to first useful answer | < 3s | `backend/loadtest.py` |
| STT→Intent→Agent→Response | < 20s | Round 4: 18.2s ✓ |
| Accessibility audit score | 100/100 | `frontend/a11y_audit.py` |
| Behavior adaptation convergence | < 5 turns | Simulated profiles |
| Offline query success rate | > 90% | Integration test |
| Concurrent users (NIM free tier) | 10-20 | Round 4 load test ✓ |

---

## Quick Wins (Can start today)

1. **Add `disability_profile` to Preference model** — 1 hour
2. **Policy engine reads profile → adjusts prompt** — 2 hours  
3. **Frontend accessibility toolbar adds profile selector** — 2 hours
4. **Session memory LRU+TTL** — 3 hours (fixes known bug)
5. **ARIA live regions in ChatInterface** — 2 hours

---

## References

- VoxSurf: Agentic browser, RAG on DOM, form NLP
- PhysiologicAILab: Scheduler→UIAdjuster/ProfileUpdater/ContentExplainer
- AURA: Behavior signals (replay/skip/listen) → verbosity/speed/complexity
- yuktai: In-browser RAG (Transformers.js), autonomous agent, offline-first
- Granite Assistant: Disability profiles, FAISS+MiniLM, local LLM, Braille
- Google NAI: Orchestrator+sub-agents, multimodal, curb-cut effect
- AdaptAble: Natural language → page adaptation, voice commands