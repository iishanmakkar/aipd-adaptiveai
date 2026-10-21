#!/usr/bin/env bash
# Run every Python suite on this machine, without Docker.
#
# scripts/verify.sh runs the same suites inside the compose stack, which is the
# environment that actually ships. This one exists because that stack was
# unrunnable here (Docker Desktop restarts mid-run on this box) while the suites
# themselves turned out to be runnable once the service trees imported correctly.
#
# Read these numbers as "the code works", never as "the shipped dependency set
# works": .venv is created with --system-site-packages, so the host's newer
# fastapi/pydantic/httpx are what ran, not the versions pinned in each service's
# requirements.txt.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$ROOT/.venv"
PY="$VENV/Scripts/python.exe"
[ -x "$PY" ] || PY="$VENV/bin/python"

if [ ! -x "$PY" ]; then
  echo "NOT VERIFIED: no $VENV. Create it first:"
  echo "  python -m venv --system-site-packages .venv"
  echo "then install what the import probe below reports as missing."
  exit 2
fi

# An environment that cannot import the code is not a failing test run. Say so
# and stop, rather than reporting a zero-collection as a defect in the project.
if ! (cd "$ROOT/backend" && "$PY" -c "import app.main" >/dev/null 2>&1); then
  echo "NOT VERIFIED: this venv cannot import the backend. Missing:"
  (cd "$ROOT/backend" && "$PY" -c "import app.main" 2>&1 \
    | grep -oE "No module named '[^']+'" | sort -u)
  echo "Install them into .venv, then re-run. Do not read this as a test failure."
  exit 2
fi

suites=(backend agents intent-engine browser-agent extension)
if [ "$#" -gt 0 ]; then suites=("$@"); fi

overall=0
rows=""
for svc in "${suites[@]}"; do
  case "$svc" in
    extension) dir="$ROOT/extension" ;;
    *)         dir="$ROOT/$svc" ;;
  esac
  if [ ! -d "$dir" ]; then echo "NOT VERIFIED: no such suite directory: $dir"; exit 2; fi
  out="$(cd "$dir" && "$PY" -m pytest -p no:warnings 2>&1)"
  summary="$(printf '%s\n' "$out" | grep -E "[0-9]+ (passed|failed|error)" | tail -1 \
             | tr -d '=' | sed -e 's/  */ /g' -e 's/^ *//' -e 's/ *$//')"
  if printf '%s\n' "$summary" | grep -qE "[0-9]+ passed" \
     && ! printf '%s\n' "$summary" | grep -qE "[0-9]+ (failed|error)"; then
    rows+="| $svc | $summary |"$'\n'
  else
    # Zero collection, a collection error, or a real failure - never a pass.
    rows+="| $svc | **FAILED** — ${summary:-nothing collected} |"$'\n'
    overall=1
    printf '%s\n' "$out" | tail -25
  fi
done

echo
echo "| suite | result |"
echo "|---|---|"
printf '%s' "$rows"
echo
echo "python: $("$PY" -V 2>&1)  venv: $VENV (--system-site-packages)"
if [ "$overall" -eq 0 ]; then
  echo "VERIFIED on this host"
else
  echo "NOT VERIFIED - see the failures above"
fi
exit "$overall"
