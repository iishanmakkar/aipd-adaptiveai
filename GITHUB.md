# AdaptiveAI — GitHub Workflow & Team Roles

> **Repo:** `https://github.com/iishanmakkar/aipd-adaptiveai.git`  
> **Default branch:** `main` @ `37bf6fc`  
> **Created branches:** `ishan`, `kakul`, `kartik`, `ishika` (all from `main`, pushed to origin)

---

## 1. Branches — Proof

```powershell
git ls-remote --heads origin
# 37bf6fc  refs/heads/main
# 37bf6fc  refs/heads/ishan
# 37bf6fc  refs/heads/kakul
# 37bf6fc  refs/heads/kartik
# 37bf6fc  refs/heads/ishika

git branch -a
#   ishan
#   ishika
#   kakul
#   kartik
# * main
#   remotes/origin/ishan
#   remotes/origin/ishika
#   remotes/origin/kakul
#   remotes/origin/kartik
#   remotes/origin/main
```

All 4 branches are clean copies of `main`. Working tree is clean (`git status` → `nothing to commit`).  
Architecture reference: `README.md:15-29` + `docker-compose.yml:1-96`.

---

## 2. Team Roles & Ownership

| Person | Branch | Module (README) | Port | Own ONLY | Key Files — Do Not Edit Others |
|--------|--------|-----------------|------|----------|-------------------------------|
| **Ishan** | `ishan` | Backend/API/DB + Policy Engine + DevOps | `8000` | `backend/` `alembic/` `docker-compose.yml` `.github/` | `backend/app/main.py:1`, `backend/app/api/routes_query.py:15`, `backend/app/services/policy_engine.py:1`, `backend/app/services/clients.py:1`, `backend/app/models/` |
| **Ishika** | `ishika` | Frontend + Voice + Vision (VLM) | `5173` | `frontend/` | `frontend/src/components/ChatInterface.tsx:1`, `frontend/src/hooks/useVoiceRecording.ts:1`, `frontend/src/services/api.ts:1`, `frontend/src/utils/image.ts:1` |
| **Kakul** | `kakul` | Intent & Context Engine | `8001` | `intent-engine/` | `intent-engine/app/classifier.py:1`, `intent-engine/app/main.py:1`, `intent-engine/app/schemas.py:1` |
| **Kartik** | `kartik` | Task Agents + RAG | `8002` | `agents/` | `agents/main.py:1`, `agents/agents/base.py:1`, `agents/rag/vector_store.py:1`, `agents/llm/client.py:1` |

**Shared contracts — change only via PR + team review:** `README.md:164-171`

```
Ishika → Ishan : POST /api/query  {session_id,input_text,input_source,screen_context}
Ishan  → Kakul : POST /intent/classify {session_id,input_text,screen_context,history}
Ishan  → Kartik: POST /agent/respond   {session_id,agent,query,entity,extra_context}
```
Types: `frontend/src/types/api.ts:1` ↔ `backend/app/schemas/query.py:1` ↔ `intent-engine/app/schemas.py:1` ↔ `agents/schemas/request.py:1`

**Integrator:** Ishan merges to `main` and resolves `docker-compose.yml:1` conflicts.

---

## 3. One-Time Setup — Example Per Person

Each person runs this **once** on their laptop. Replace name/email.

### Example — Ishan (Backend)
```powershell
git clone https://github.com/iishanmakkar/aipd-adaptiveai.git
cd aipd-adaptiveai
git config user.name "Ishan Makkar"
git config user.email "ishanmakkar651@gmail.com"
git fetch origin
git checkout ishan
git branch -vv  # should show: ishan -> origin/ishan
```

### Example — Ishika (Frontend)
```powershell
git clone https://github.com/iishanmakkar/aipd-adaptiveai.git
cd aipd-adaptiveai
git config user.name "Ishika Garg"
git config user.email "ishika@example.com"
git fetch origin
git checkout ishika
```

### Example — Kakul (Intent Engine)
```powershell
git clone https://github.com/iishanmakkar/aipd-adaptiveai.git
cd aipd-adaptiveai
git config user.name "Kakul Aeron"
git config user.email "kakul@example.com"
git fetch origin
git checkout kakul
```

### Example — Kartik (Agents/RAG)
```powershell
git clone https://github.com/iishanmakkar/aipd-adaptiveai.git
cd aipd-adaptiveai
git config user.name "Kartik Bareja"
git config user.email "kartik@example.com"
git fetch origin
git checkout kartik
```

**Verify you are on your branch:**
```powershell
git status
# On branch ishika  (or your name)
# Your branch is up to date with 'origin/ishika'.
```

---

## 4. Daily Work Loop — How Each Person Does Code

> **Golden rule:** `git checkout <your_branch>` → edit ONLY your folder → test → commit → push → PR to `main`.  
> Never commit to `main` directly. Never edit another person's folder.

### 4.1 Ishika — Frontend Example (add mic animation)
```powershell
git checkout ishika
git fetch origin
git rebase origin/main   # pull latest main into your branch

# work only in frontend/
code frontend/src/components/MicButton.tsx
# ... edit MicButton.tsx:1, e.g., add pulse animation ...

# test locally (no Docker needed)
cd frontend
npm install
npm run build   # must be zero TS errors (tsc && vite build)
cd ..

git status  # should show only frontend/ modified
git add frontend/src/components/MicButton.tsx
git commit -m "feat(frontend): add pulse animation to MicButton"
git push origin ishika
# -> go to GitHub -> Pull Request: ishika -> main -> Request review from Ishan
```

### 4.2 Kakul — Intent Engine Example (tune classifier)
```powershell
git checkout kakul
git fetch origin
git rebase origin/main

code intent-engine/app/classifier.py
# ... edit KEYWORD_RULES or SYSTEM_PROMPT in classifier.py:1 ...

cd intent-engine
pip install -r requirements.txt
python -m pytest tests/test_classifier.py -v  # 20 cases must pass
cd ..

git add intent-engine/app/classifier.py
git commit -m "feat(intent): improve form_help keyword fallback"
git push origin kakul
```

### 4.3 Kartik — Agents/RAG Example (add FAQ doc)
```powershell
git checkout kartik
git fetch origin
git rebase origin/main

code agents/rag/seed_data.py
# ... add new doc to SEED_DOCUMENTS in seed_data.py:1 ...

cd agents
pip install -r requirements.txt
python tests/run_tests.py        # real LLM test, check accuracy
# or: python tests/run_tests_mock.py
cd ..

git add agents/rag/seed_data.py
git commit -m "feat(agents): add disability_certificate FAQ to RAG"
git push origin kartik
```

### 4.4 Ishan — Backend Example (adjust policy threshold)
```powershell
git checkout ishan
git fetch origin
git rebase origin/main

code backend/app/services/policy_engine.py
# ... edit clarifying_threshold or adjust_response() in policy_engine.py:1 ...

cd backend
pip install -r requirements.txt
python test_integration.py   # httpx to 8001/8002
docker compose config        # validate 5 services
cd ..

git add backend/app/services/policy_engine.py
git commit -m "feat(backend): lower clarifying threshold to 2"
git push origin ishan
```

---

## 5. Commit Convention

```
feat(frontend): ...   # new UI/hook
feat(intent): ...     # classifier / intent logic
feat(agents): ...     # RAG / agent prompt
feat(backend): ...    # API / DB / policy
fix(...): ...         # bug fix
docs(...): ...        # README / GITHUB.md
chore(...): ...       # config / deps
```

Examples:
```powershell
git commit -m "fix(intent): handle empty screen_context in classify"
git commit -m "docs(github): add workflow examples"
```

---

## 6. Testing Checklist Before Push

| Person | Command | Must Pass |
|--------|---------|-----------|
| Ishika | `cd frontend; npm run build` | `tsc && vite build` zero errors |
| Kakul | `cd intent-engine; python -m pytest tests/test_classifier.py -v` | 20 cases |
| Kartik | `cd agents; python tests/run_tests.py` | 40+ queries grounded |
| Ishan | `cd backend; docker compose config` + `python test_integration.py` | 5 services valid, 8001/8002 healthy |

Full Docker smoke (Ishan only, optional):
```powershell
docker compose up --build
# Frontend  http://localhost:5173
# Backend   http://localhost:8000/docs
# Intent    http://localhost:8001/docs
# Agents    http://localhost:8002/docs
curl http://localhost:8000/health
curl http://localhost:8001/health
curl http://localhost:8002/health
docker compose down
```

---

## 7. Pull Request Workflow — Example

**On GitHub UI (recommended):**
1. Push your branch: `git push origin ishika`
2. GitHub banner → `Compare & pull request` → base: `main` ← compare: `ishika`
3. Title: `feat(frontend): add pulse animation` — Description: what + why + test proof
4. Request reviewer: `iishanmakkar` (integrator)
5. Wait for review → Address comments → `Squash and merge` → Delete branch (remote retains; local stays)

**After merge — everyone updates:**
```powershell
git checkout main
git pull origin main
git checkout <your_branch>
git rebase origin/main   # or: git merge main
git push origin <your_branch> --force-with-lease  # if rebased
```

**Example rebase session (Kakul after Ishan merged policy fix):**
```powershell
git checkout kakul
git fetch origin
git rebase origin/main
# if conflict:
#   fix file -> git add <file> -> git rebase --continue
git push origin kakul --force-with-lease
```

---

## 8. Handling Conflicts — Example

You edited `docker-compose.yml:1` locally but `main` also changed:

```powershell
git fetch origin
git rebase origin/main
# Auto-merging docker-compose.yml
# CONFLICT (content): Merge conflict in docker-compose.yml
code docker-compose.yml  # resolve <<<<<<< HEAD vs your changes
git add docker-compose.yml
git rebase --continue
git push origin ishan --force-with-lease
```

**Prevention:** Only Ishan edits `docker-compose.yml:1`. Frontend/Intent/Agents never touch it directly — open issue/PR instead.

---

## 9. Rules to Avoid Breakage

1. **Never commit `.env`** — ` .gitignore:1` ignores `*.env`. Use `.env.example` as template. If you need a key, copy: `Copy-Item .env.example .env` and fill locally.
2. **Never push to `main`** directly: `git push origin main` is blocked by workflow — always PR.
3. **Only edit your folder:** `frontend/` → Ishika, `intent-engine/` → Kakul, `agents/` → Kartik, `backend/` → Ishan. Shared files (`README.md:1`, `GITHUB.md:1`) via PR + review.
4. **`VITE_USE_MOCK=false` in `frontend/.env:1`** for real path. `true` only for isolated frontend mock (`frontend/mock-server/server.js:1`).
5. **Keep commits small** — one feature per commit, prefix with `feat(frontend/intent/agents/backend):`.
6. **Pull before push** — `git fetch && git rebase origin/main` daily.

---

## 10. .env Handling — Example

```powershell
# new clone has no .env (ignored)
Get-ChildItem -Force | Where-Object Name -like ".env*"
# .env.example exists, .env missing -> create it

Copy-Item frontend/.env.example frontend/.env
Copy-Item backend/.env.example backend/.env
Copy-Item intent-engine/.env.example intent-engine/.env
Copy-Item agents/.env.example agents/.env

# edit keys (NIM_API_KEY already real in examples, don't commit)
code backend/.env  # SUPABASE_DB_URL, JWT_SECRET, NIM_API_KEY
```

If `git status` shows `.env` untracked → **do not `git add` it**. It is ignored intentionally (`README.md:274` fix #6).

---

## 11. Quick Reference — All Commands Per Person

**Ishika:**
```powershell
git checkout ishika; git pull origin ishika
# edit frontend/src/components/* , frontend/src/hooks/* , frontend/src/styles/*
cd frontend; npm run build; cd ..
git add frontend/; git commit -m "feat(frontend): ..."; git push origin ishika
```

**Kakul:**
```powershell
git checkout kakul; git pull origin kakul
# edit intent-engine/app/classifier.py , schemas.py , main.py
cd intent-engine; python -m pytest tests/test_classifier.py -v; cd ..
git add intent-engine/; git commit -m "feat(intent): ..."; git push origin kakul
```

**Kartik:**
```powershell
git checkout kartik; git pull origin kartik
# edit agents/rag/* , agents/agents/* , agents/llm/* , agents/main.py
cd agents; python tests/run_tests_mock.py; cd ..
git add agents/; git commit -m "feat(agents): ..."; git push origin kartik
```

**Ishan:**
```powershell
git checkout ishan; git pull origin ishan
# edit backend/app/* , alembic/* , docker-compose.yml
docker compose config; cd backend; python test_integration.py; cd ..
git add backend/ docker-compose.yml; git commit -m "feat(backend): ..."; git push origin ishan
```

---

## 12. Emergency — Undo & Help

```powershell
# discard local edits (careful!)
git restore <file>
git restore --staged <file>

# undo last commit (keep changes)
git reset --soft HEAD~1

# stash dirty work to switch branch
git stash push -m "wip: temp"
git stash pop

# see what changed vs main
git diff main...<your_branch> --stat
git log main..HEAD --oneline

# clean working tree?
git status
# must be: On branch <your_branch>, Your branch is up to date with 'origin/<your_branch>', nothing to commit
```

---

*Generated for AdaptiveAI — each branch (`ishan/kakul/kartik/ishika`) is ready to code. Follow §4 example for your role, push, then PR to `main`.*
