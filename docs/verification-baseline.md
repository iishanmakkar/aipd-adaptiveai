# Verification baseline

## Current: this host, no Docker — 2026-10-24 (after the full-tree bug sweep)

Measured on the working tree at `4d9f8e5`, with

```bash
bash scripts/verify-host.sh        # all five suites, non-zero on any failure
```

| Suite | Result |
|---|---|
| backend | **253 passed**, 1 skipped |
| agents | **103 passed**, 1 deselected |
| intent-engine | **135 passed**, 2 deselected |
| browser-agent | **63 passed** |
| extension (real Chromium) | **140 passed** |
| **Python total** | **694 passed**, 1 skipped, 3 deselected |

Frontend `npm run build` (tsc strict + Vite) is clean on the same tree. Every
number above was produced by running the suites on this host, each exiting 0;
the totals in earlier versions of this file came from a different tree and are
kept below for history.

### Previous: 2026-10-21 (kept for history)

Measured **2026-10-21** on the working tree at `1fc6aba` + the voice path, with

```bash
bash scripts/verify-host.sh        # all five suites, non-zero on any failure
bash scripts/verify-host.sh backend
```

| Suite | Result |
|---|---|
| backend | **248 passed**, 1 skipped |
| agents | **102 passed**, 1 deselected |
| intent-engine | **134 passed**, 2 deselected |
| browser-agent | **62 passed** |
| extension (real Chromium) | **122 passed** |
| **Python total** | **668 passed**, 1 skipped, 3 deselected |

Interpreter: `Python 3.14.7` in `.venv`, created with `--system-site-packages`.

## The two proofs that leave the suite

```bash
.venv/Scripts/python.exe scripts/stt_local_proof.py           # exit 0 here
.venv/Scripts/python.exe scripts/extension_step_live_proof.py # exit 3 here
```

Re-run **2026-10-24** on this tree: `stt_local_proof.py` exited **0** — the OS
voice spoke "book two tickets for the seven pm show" (135 KB WAV), the real
`/api/transcribe` route decoded it with faster-whisper and returned **"book 2
tickets for the 7 p.m. show."**; `extension_step_live_proof.py` exited **3**,
inconclusive: `backend/.env` still holds the placeholder key, NIM answered 401
("Invalid JWT serialization"), and the script said so instead of passing.

`stt_local_proof.py` speaks "book two tickets for the seven pm show" through the
operating system's own text-to-speech, uploads the WAV to the real
`/api/transcribe`, and gets back **"book 2 tickets for the 7 p.m. show."** —
decoded locally by faster-whisper, no cloud key involved. It found two things on
the way: `faster-whisper` calls `av.open(..., metadata_errors=...)`, which
**PyAV 19 removed**, so the host needs `av==15.1.0` (the pinned `av==13.0.0` has
no Python 3.14 wheel at all); and the route's response field is `transcript`, while
the extension's worker was reading `text` — so every successful transcription would
have come back as "I heard no words in that". The second is fixed; the first is an
environment deviation, not the shipped dependency set.

`extension_step_live_proof.py` exits **3, inconclusive**: `backend/.env` on this
machine holds `NIM_API_KEY=your-nim-api-key`, a placeholder, so NIM answers 401 and
no live-model claim in this repository is reproducible here. It is not a pass, and
the script says so rather than falling through to green.

Interpreter: `Python 3.14.7` in `.venv`, created with `--system-site-packages`.

**What that number does and does not mean.** The venv inherits the host's
site-packages, so these runs used the host's `fastapi 0.143.0`, `pydantic 2.14.1`,
`httpx` pinned down to the project's `0.27.2`, `SQLAlchemy 2.1.4`, `uvicorn 0.54.0`
and `faiss-cpu 1.15.1` — not the versions pinned in each service's
`requirements.txt` (`fastapi==0.119.0`, `pydantic==2.9.2`, `SQLAlchemy==2.0.36`,
`faiss-cpu==1.9.0`). A green host run is evidence about **this code**, not about
**the shipped dependency set**. `scripts/verify.sh` (compose) remains the
authoritative run for that.

To recreate this environment from scratch:

```bash
python -m venv --system-site-packages .venv
.venv/Scripts/python.exe -m pip install "python-jose[cryptography]==3.4.0" bcrypt==5.0.0 \
  redis==5.2.1 email-validator==2.2.0 openai==1.54.0 httpx==0.27.2 pytest==8.4.2 \
  pytest-asyncio==0.26.0 "sentence-transformers==3.2.0" faiss-cpu
# only for scripts/stt_local_proof.py - see "The two proofs that leave the suite"
.venv/Scripts/python.exe -m pip install "faster-whisper==1.1.1" "av==15.1.0"
```

`asyncpg` cannot be installed here at all (no wheel for Python 3.14 and no C
compiler), so the `live` Postgres-marked tests stay deselected — 3 of them, which
is why the totals show deselections rather than failures.

## Earlier: the compose stack

Measured the same day at `ad4a0db` + Task 1 changes with `docker compose up -d`
(7 services healthy) and `bash scripts/verify.sh`:

| Service | Result | Deselected | Skipped |
|---|---|---|---|
| backend | **198 passed** | 0 | 1 |
| agents | **101 passed** | 1 | 0 |
| intent-engine | **129 passed** | 2 | 0 |
| browser-agent | **44 passed** | 0 | 0 |
| **Python total** | **472 passed** | 3 | 1 |

The extension suite (`extension/test`, 112 tests) did not exist for that run, and
backend gained tests since. Frontend `npm run build` (tsc strict + Vite) passes on
the host.

## A correction to what this document used to claim

This file previously explained the host failure as **host pollution**:

> The error names a submodule (`No module named 'app.api.routes_query'`), so it
> reads like the project is broken when it is the host that is polluted.

That was wrong, and the wrong part matters: it described a defect in this
repository as an environmental condition nobody had to fix.

`backend/app` shipped no `__init__.py` while `app/agents`, `app/models` and
`app/schemas` all had one. Without it `app` is a *namespace portion*, and
Python's path finder prefers any **regular** package it finds later on `sys.path`
— which on this machine is `D:\geospatial\geomeasure\app`. The fix was four
package markers, not a cleaner machine. `tests` had the same shape in reverse:
eight modules imported `tests.conftest` and got the other project's conftest,
while four imported the flat `from conftest import`, which only resolves while the
directory is *not* a package. All twelve now use `from tests.conftest import`.

Two real defects fell out of finally being able to run these suites here:

1. **intent-engine's contract test was stale.** `test_response_is_always_schema_valid`
   still asserted the six-key response body from before `confidence_source` was
   added, so it failed against a correct response and passed against a wrong one.
2. **A declared-production boot with no `REDIS_URL` still started on the
   per-process fallback.** Task 10 only refused a *configured but unreachable*
   store; the likelier misconfiguration — never setting it — warned nothing and
   partitioned share tokens, pending confirmations and monitor cursors across
   replicas. It now refuses at `app/main.py`'s boot guard, next to the `DEBUG` and
   `JWT_SECRET` refusals, instead of raising from a service module a router
   imported first (which is what preempted those guards' messages).

## The real bug the container run found

With Redis actually running (the compose stack provides it), two backend tests
failed that had passed silently whenever Redis was down:

`SharedStore.set()` wrote TTLs with `setex(max(1, ceil(ttl_seconds)))`. A 0.05 s
TTL therefore lived **1 full second in Redis** while the write-through local copy
expired after 0.05 s — and `get()` reads Redis first. Expired state kept reading
back as live in the store that holds **pending confirmations, narration cursors,
session flags and share tokens**: an expired confirmation stayed actionable, a
revoked share link stayed readable.

Fixed by writing `px=max(1, round(ttl_seconds * 1000))` so both layers carry the
same lifetime, with `max(1, …)` preserving the original guard against rounding a
live TTL down to 0 (which Redis treats as no expiry).
`tests/test_round_fixes.py`'s ceil-to-1s assertion was retargeted to the
millisecond contract rather than deleted — its intent ("a TTL must never become
zero") still holds.

This is a bug that **only reproduces in a correct environment**, which is exactly
why an unverifiable test command is itself a defect.

## Reproducing either run

```bash
bash scripts/verify-host.sh          # this machine, no Docker, 694 passed (2026-10-24)
bash scripts/verify.sh               # compose stack: docker compose up -d first
bash scripts/verify.sh backend       # one service
```

Both scripts treat a suite that collects **zero** tests as a failure, not a pass.
`verify.sh` exits 2 with `NOT VERIFIED` when the Docker daemon is unreachable —
Docker Desktop restarted twice mid-run on this box and the machine rebooted once
under sustained container load (`DEPLOY.md` §6c). That is an environment
condition, and it is reported as such rather than as a test failure.
