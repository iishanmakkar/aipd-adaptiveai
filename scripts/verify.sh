#!/usr/bin/env bash
# Runs each service's offline suite INSIDE its container.
#
# The Windows host cannot run these. Measured 2026-10-21: host `python -m pytest`
# fails at collection for backend, agents and intent-engine, running zero tests -
# host deps are absent (`ModuleNotFoundError: No module named 'jose'`) and
# `import app` resolves to D:\geospatial\geomeasure\app, an unrelated project that
# a site-packages entry puts on sys.path. Reading a host collection failure as a
# quiet pass is how the previous 454-test baseline went stale.
#
# Usage:
#   bash scripts/verify.sh                 # all four Python services
#   bash scripts/verify.sh backend         # one service
set -uo pipefail

if [ $# -eq 0 ]; then
  services=(backend agents intent-engine browser-agent)
else
  services=("$@")
fi

# Preflight: a dead Docker Desktop is an ENVIRONMENT failure, not a test failure.
# Without this, every `docker compose exec` below returns "failed to connect to
# the docker API", the suites all report exit 1, and a crashed daemon is
# indistinguishable from broken code - the exact ambiguity this pass exists to
# remove. Exit 2 means "verify nothing, fix the daemon".
if ! docker info --format '{{.ServerVersion}}' >/dev/null 2>&1; then
  echo "verify.sh: cannot reach the Docker daemon." >&2
  echo "  Start Docker Desktop and wait for it to report running, then re-run." >&2
  echo "  Nothing below was tested; exit 2 means NOT VERIFIED, not FAILED." >&2
  exit 2
fi

rc=0
for svc in "${services[@]}"; do
  case "$svc" in
    # No extra -q here: every service's pytest.ini already passes -q in addopts,
    # and -q twice silences the "N passed" summary line this script exists to read.
    browser-agent) cmd='python -m pytest -p no:warnings -m "not live"' ;;
    backend|agents|intent-engine) cmd='python -m pytest -p no:warnings' ;;
    *) echo "unknown service: $svc"; exit 2 ;;
  esac

  printf '\n=== %s: %s\n' "$svc" "$cmd"

  # The backend RUNTIME image deliberately ships no test deps (its Dockerfile
  # installs requirements.txt only; CI adds -dev on a throwaway runner). So the
  # long-lived dev container has no pytest and no requirements-dev.txt on disk.
  # Copy the dev contract in and install it into this container only - the
  # production image stays lean, and a rebuild drops it again.
  if [ "$svc" = backend ]; then
    docker compose exec -T backend python -c "import pytest" >/dev/null 2>&1 || {
      echo "(installing backend test deps into the dev container)"
      docker compose cp backend/requirements-dev.txt backend:/app/requirements-dev.txt
      docker compose exec -T backend pip install -q -r requirements-dev.txt
    }
  fi

  out=$(docker compose exec -T "$svc" sh -c "$cmd" 2>&1)
  status=$?
  # Always surface the counts: a suite that ran 0 tests must be visible as such,
  # not inferred from the absence of failures.
  echo "$out" | tail -n 3
  if [ $status -ne 0 ]; then
    echo "$out" | grep -E "^(FAILED|ERROR)" | head -n 20
  fi

  if [ $status -ne 0 ]; then
    echo "!! $svc exited $status"
    rc=1
  fi
  # pytest exits 4 on a collection error and prints "0 passed", which is
  # indistinguishable from a quiet green run unless you look for it.
  if echo "$out" | grep -qE "no tests ran|errors during collection|Interrupted: [0-9]+ error"; then
    echo "!! $svc collected ZERO tests - the suite is not running, not passing"
    rc=1
  fi
done

printf '\n=== verify.sh exit %s\n' "$rc"
exit "$rc"
