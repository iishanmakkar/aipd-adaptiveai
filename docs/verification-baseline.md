# Verification baseline

Measured **2026-10-21** on the working tree at `ad4a0db` + Task 1 changes, with
`docker compose up -d` (7 services healthy) and:

```bash
bash scripts/verify.sh
```

| Service | Result | Deselected | Skipped |
|---|---|---|---|
| backend | **198 passed** | 0 | 1 |
| agents | **101 passed** | 1 | 0 |
| intent-engine | **129 passed** | 2 | 0 |
| browser-agent | **44 passed** | 0 | 0 |
| **Python total** | **472 passed** | 3 | 1 |

Frontend `npm run build` (tsc strict + Vite) passes on the host.

---

## Why the host cannot run these suites

`README.md` §5 previously documented `cd <service>; python -m pytest` **on the host**
and certified "454 passed, verified 2026-10-06". That is not reproducible on this
machine, and the failure mode is the dangerous kind — it looks like a pass:

1. **Host dependencies are absent.** `python -m pytest` in `backend` dies at
   collection with `ModuleNotFoundError: No module named 'jose'`. The active
   interpreter is `Python 3.14.7`; `py -3.11` is not installed.
2. **A sibling project shadows the package name.** `import app` resolves to
   `D:\geospatial\geomeasure\app\__init__.py`, not `D:\aipd\backend\app`, because
   that directory is on `sys.path` through a site-packages entry. The error names a
   *submodule* (`No module named 'app.api.routes_query'`), so it reads like the
   project is broken when it is the host that is polluted.
3. **Containers were no better, for a different reason.** The backend runtime image
   ships neither the test suite nor its config, so `docker compose exec backend
   python -m pytest` reported `no tests ran` and **exit 5**:

   - `backend/Dockerfile` copies only `./app` and `./alembic` — no `tests/`.
   - It also does not copy `pytest.ini`, which is what sets `asyncio_mode = auto`.
     With it absent, every async test failed as "async def functions are not
     natively supported" — 46 failures that looked like a broken codebase but were
     a missing config file.
   - `requirements-dev.txt` (pytest, pytest-asyncio, httpx) is installed by CI on a
     throwaway runner but never inside the image, by design.

`docker-compose.yml` now bind-mounts `backend/tests` and `backend/pytest.ini`
read-only for dev, and `scripts/verify.sh` copies in and installs
`requirements-dev.txt` on first use. The production image stays lean; a rebuild
drops the test deps again.

## The real bug this found

With Redis actually running (the compose stack provides it), two backend tests failed
that had passed silently whenever Redis was down:

`SharedStore.set()` wrote TTLs with `setex(max(1, ceil(ttl_seconds)))`. A 0.05 s TTL
therefore lived **1 full second in Redis** while the write-through local copy expired
after 0.05 s — and `get()` reads Redis first. Expired state kept reading back as live
in the store that holds **pending confirmations, narration cursors, session flags and
share tokens**: an expired confirmation stayed actionable, a revoked share link stayed
readable.

Fixed by writing `px=max(1, round(ttl_seconds * 1000))` so both layers carry the same
lifetime, with `max(1, …)` preserving the original guard against rounding a live TTL
down to 0 (which Redis treats as no expiry). `tests/test_round_fixes.py`'s
ceil-to-1s assertion was retargeted to the millisecond contract rather than deleted —
its intent ("a TTL must never become zero") still holds.

This is a bug that **only reproduces in a correct environment**, which is exactly why
an unverifiable test command is itself a defect.

## Reproducing

```powershell
docker compose up -d --build      # Docker Desktop must be running on this host
bash scripts/verify.sh            # all four Python services, non-zero on any failure
bash scripts/verify.sh backend    # one service
```

`verify.sh` treats a suite that collects zero tests as a **failure**, not a pass.

## Host stability caveat

During this work Docker Desktop restarted twice mid-run and the machine rebooted once
under sustained container load — the condition `DEPLOY.md` §6c already documents for
this box. Test numbers above are from a completed run; if `verify.sh` reports
`failed to connect to the docker API`, restart Docker Desktop and re-run rather than
reading it as a test failure.
