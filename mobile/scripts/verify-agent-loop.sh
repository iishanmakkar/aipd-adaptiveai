#!/usr/bin/env bash
# Host proof of the AdaptiveAI agent loop against LIVE NVIDIA NIM.
#
# Transpiles the shipped src/services/{nim,agent}.ts and runs them with a simulated Android
# device (scripts/agent-harness/native/assist.js), so the prompt, tool protocol, JSON
# extraction, model resolution and confirm gate under test are the real code.
#
# Env: NIM_KEY (defaults to backend/.env), INSTRUCTION, MAX_STEPS
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
node "$ROOT/scripts/agent-harness/transpile.js"
node "$ROOT/scripts/agent-harness/run.js"
