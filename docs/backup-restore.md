# Backup & Restore Runbook — AdaptiveAI Postgres

Validated end-to-end on this repo: dump → **destroy the volume** → restore →
row counts matched exactly (119 users / 287 sessions / 124 messages) and the
application booted and read the restored data.

## Backup

```bash
# from the repo root, stack running
docker compose exec -T postgres pg_dump -U postgres -d adaptiveai \
  > backup-$(date +%Y%m%d-%H%M%S).sql
```

`pg_dump` runs inside the container, so no client tooling is needed on the host.
The `-T` keeps it non-interactive (safe for cron). To back up on a schedule,
cron the command above and rotate the files.

## Restore

Restore into an **empty** database *before* the app starts. The app calls
`create_all` on boot (which skips existing tables), but a plain dump contains
`CREATE TABLE` statements that would collide with tables the app already made —
so restore first, then start the rest.

```bash
# 1. tear everything down, destroying the data volume (DESTRUCTIVE)
docker compose down -v

# 2. start ONLY postgres (fresh, empty)
docker compose up -d postgres
sleep 10

# 3. restore the dump
docker compose exec -T postgres psql -U postgres -d adaptiveai < backup-YYYYMMDD-HHMMSS.sql

# 4. start the rest of the stack
docker compose up -d
```

## Verify (do this every time — "no errors" is not proof)

```bash
# row counts before vs after must match
docker compose exec -T postgres psql -U postgres -d adaptiveai -tAc \
  "SELECT 'users='||count(*) FROM users;
   SELECT 'sessions='||count(*) FROM sessions;
   SELECT 'messages='||count(*) FROM messages;"

# the app must read it, not just psql
curl -s http://localhost:8000/health
```

## What this does NOT cover (honest)

- **Point-in-time recovery / WAL archiving** — this is a logical dump, so
  restoring loses everything after the dump timestamp. For continuous recovery
  you need WAL archiving or a managed Postgres with PITR.
- **The FAISS index** (`agents/data/chroma`) is not in the dump. It is
  rebuildable from the seed data on agents start, so it is not backed up here —
  but any runtime-added documents would be lost. If you add documents at
  runtime, back up that directory too.
- **`.env` secrets** are never in a DB dump; keep them in your secret store.
- **Off-host copy** — the dump lands on the same disk as the database. A real
  backup goes to object storage / another machine.
