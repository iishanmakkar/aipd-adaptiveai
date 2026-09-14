# Deployment Guide — AdaptiveAI

This documents running AdaptiveAI on a real server, not the developer's laptop.
Everything here was validated against the local Docker Compose stack; the cloud
step is written for a standard Linux VM and has not been executed on one from
this machine (no cloud credentials in scope) — that is stated, not hidden.

## 1. Topology

Five services, one `docker compose` file:

| Service | Port (host) | Role |
|---|---|---|
| postgres | 5433 → 5432 | persistence |
| intent-engine | 8001 | intent classification (NIM) |
| agents | 8002 | 5 task agents + FAISS RAG (NIM) |
| backend | 8000 | orchestration, DB, policy engine, auth, STT, VLM proxy |
| frontend | 5173 | React UI |

## 2. One-time secrets

```bash
cp backend/.env.example backend/.env
cp intent-engine/.env.example intent-engine/.env
cp agents/.env.example agents/.env
cp frontend/.env.example frontend/.env
```

Set in each: a **real** `NIM_API_KEY`, a **strong random** `JWT_SECRET`
(`openssl rand -hex 32`), and the Postgres URL. `.env` files are gitignored and
excluded from Docker build contexts (`.dockerignore`) so they never enter image
layers.

## 3. Production flags (required)

- `DEBUG=False` in `backend/.env` and `intent-engine/.env`.
  - `DEBUG=True` allows CORS `*`, serves `/docs`, and **auto-logs every visitor
    in as the demo user** — never ship it.
- Set `ADAPTIVEAI_PRODUCTION=1` in the backend environment. With that flag set,
  the backend **refuses to boot if `DEBUG=True`** (verified: startup raises
  "Refusing to start…"). This is the guard against accidentally shipping demo
  auth.
- `FRONTEND_URL` must be your real origin; with `DEBUG=False` CORS is limited to
  it.

## 4. Database migrations

Migrations are the source of truth for the schema. On a fresh database:

```bash
docker compose up -d postgres
docker compose exec backend alembic upgrade head
```

Verified: `alembic upgrade head` against an empty Postgres creates
`users / sessions / messages / preferences` + `alembic_version`. The app also
calls `create_all` on startup as a convenience for local dev; for real
deployments run Alembic (put it in your deploy step or CI, not a manual
afterthought).

## 5. Start / restart / update

```bash
docker compose up -d --build      # build + start all five
docker compose ps                 # all should reach "healthy"
docker compose logs -f backend    # JSON access logs, one line per request
```

All services run `restart: unless-stopped`, so a crashed container restarts
with the daemon and the whole stack comes back after a host reboot without
manual intervention.

## 6. Cloud VM (standard path, not run from this machine)

Any Linux VM with Docker + Compose v2:

```bash
git clone <repo> && cd adaptiveai
# place .env files (section 2), set production flags (section 3)
docker compose up -d --build
docker compose exec backend alembic upgrade head
```

Put a TLS reverse proxy (Caddy/nginx/Traefik) in front of 5173 and 8000, or
deploy the frontend as a static `npm run build` bundle to a CDN and the three
Python services as containers. Because every browser request appears to come
from the proxy's IP, make the proxy set `X-Forwarded-For` and trust it — the
rate limiter keys on user identity when a token is present, so NAT no longer
collapses all users into one bucket.

## 7. Capacity and cost (measured, not guessed)

**Throughput is bounded by the NIM API, not by our code.** Measured with the
load harness (`backend/loadtest.py`) against the live stack:

| Concurrency | 200 | 502 | 429 | p50 latency (successful) |
|---|---|---|---|---|
| 10 | 11 | 2 | 0 | ~80 s |
| 20 | 27 | 1 | 0 | ~64 s |
| 50 | 17 | 183 | 407 | ~119 s |

At 50 concurrent the system **sheds load correctly** (rate limiter returns 429
rather than collapsing), but only ~3% of requests succeed. Practical ceiling on
this key/tier is roughly **10–20 concurrent users** before latency and 502s
degrade the experience. Single-request latency is 3.5–15 s for one NIM
completion; a full query chains 2–3 of them (intent + agent + policy rewrite).

**Cost.** NVIDIA's hosted NIM endpoint used here is a **free tier** with a
per-minute rate limit — that is why heavy concurrency 502s. On a paid
NIM/on-demand plan, llama-3.x-8b-class models are billed per token; a query is
~700–1,200 prompt tokens (system prompt + 3 retrieved docs + question) and
~200–400 completion tokens, so **~1,200 tokens per query**. At a representative
$0.35 / 1M input + $1.00 / 1M output, that is **~$0.0006 per query** → about
**$5/month per 10,000 queries**, plus a small VM (~$5–20/mo) and hosting. The
free tier costs $0 but caps concurrency as measured above.

## 8. What is NOT yet done for a real launch

- Human screen-reader (NVDA/JAWS/VoiceOver) validation — automated ARIA/keyboard
  contract passes and NVDA 2026.2 is confirmed installable + running on Windows,
  but verbatim speech capture needs a human ear. Runbook:
  `docs/screen-reader-test-script.md`.
- Human-speech STT WER — measured only on synthesized speech. Runbook + tool:
  `docs/real-speech-stt-runbook.md`, `backend/stt_wer.py`.
- No HTTPS/auth hardening beyond JWT; no refresh tokens, so rotating
  `JWT_SECRET` logs everyone out (verified 401 on old tokens).
- Cloud path above is documented, not executed from here (no cloud credentials).

Backup/restore is now **done** — see `docs/backup-restore.md` (validated:
dump → destroy volume → restore → row counts matched exactly).

## 9. Paid-tier capacity test (run when a paid NIM key exists)

The concurrency ceiling in §7 is measured on the **free** tier. With a paid key,
re-run and record whether it rises:

```bash
# set the paid key in all three service .env files, then:
docker compose up -d --build
cd backend
python loadtest.py 10 60
python loadtest.py 20 60
python loadtest.py 50 60
```

Watch for: (a) whether 429/502 rates at 50 concurrent drop (free tier shed ~67%
of requests as 429 at 50); (b) whether p50 latency improves (free tier p50
64–119s under load); (c) the concurrency at which errors first appear. Until run,
**10–20 concurrent users is a free-tier number only** — not the system's inherent
capacity.
