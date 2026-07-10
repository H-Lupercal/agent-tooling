#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
UV="${UV:-uv}"
TMP="$($PYTHON -c 'import tempfile; print(tempfile.mkdtemp(prefix="conductor-e2e-"))')"
trap '$PYTHON -c "import shutil; shutil.rmtree(r'\''$TMP'\'', ignore_errors=True)"' EXIT

"$PYTHON" -m venv "$TMP/venv"
VENV_PY="$TMP/venv/bin/python"
VENV_CONDUCTOR="$TMP/venv/bin/conductor"
if [[ "${OS:-}" == "Windows_NT" ]]; then
  VENV_PY="$TMP/venv/Scripts/python.exe"
  VENV_CONDUCTOR="$TMP/venv/Scripts/conductor.exe"
fi

if command -v "$UV" >/dev/null 2>&1; then
  "$UV" pip install --offline --link-mode=copy --python "$VENV_PY" "$ROOT"
else
  "$VENV_PY" -m pip install -q "$ROOT"
fi
export HOME="$TMP/home"
export USERPROFILE="$HOME"
mkdir -p "$HOME"

"$VENV_CONDUCTOR" install --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md"

printf '%s\n' '{"thread_id":"e2e-run","root_thread_id":"e2e-run","model":"gpt-5.5"}' \
  | "$VENV_PY" "$HOME/.codex/conductor/hooks/session_start.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"thread_id":"e2e-run","root_thread_id":"e2e-run","model":"gpt-5.5","tool_call_id":"e2e-call","tool_name":"spawn_agent","tool_input":{"task_name":"risk-task","message":"<CONDUCTOR_TASK>{\"schema_version\":1,\"task_name\":\"risk-task\",\"task_class\":\"high_risk\",\"risk_triggers\":[],\"owned_paths\":[\"src/risk.py\"],\"acceptance_checks\":[\"pytest -q\"],\"new_task\":true}</CONDUCTOR_TASK>"}}' \
  | "$VENV_PY" "$HOME/.codex/conductor/hooks/pre_tool_use.py" \
  | "$VENV_PY" -c 'import json,sys; result=json.load(sys.stdin); assert result["decision"] == "approve", result'

printf '%s\n' '{"hook_event_name":"PostToolUse","thread_id":"e2e-run","root_thread_id":"e2e-run","tool_call_id":"e2e-call","tool_name":"spawn_agent","tool_input":{"task_name":"risk-task","message":"<CONDUCTOR_TASK>{\"schema_version\":1,\"task_name\":\"risk-task\",\"task_class\":\"high_risk\",\"risk_triggers\":[],\"owned_paths\":[\"src/risk.py\"],\"acceptance_checks\":[\"pytest -q\"],\"new_task\":true}</CONDUCTOR_TASK>"},"tool_response":{"child_id":"e2e-child"}}' \
  | "$VENV_PY" "$HOME/.codex/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"hook_event_name":"SubagentStart","root_thread_id":"e2e-run","thread_id":"e2e-child","model":"gpt-5.5"}' \
  | "$VENV_PY" "$HOME/.codex/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"hook_event_name":"SubagentStop","root_thread_id":"e2e-run","thread_id":"e2e-child","model":"gpt-5.5","status":"completed","usage":{"input_tokens":1000,"cached_input_tokens":100,"output_tokens":100,"reasoning_output_tokens":10}}' \
  | "$VENV_PY" "$HOME/.codex/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

"$VENV_CONDUCTOR" status --run e2e-run --pretty >/dev/null
"$VENV_CONDUCTOR" report --run e2e-run --json \
  | "$VENV_PY" -c 'import json,sys; report=json.load(sys.stdin); assert report["tiers"]["frontier"]["completed"] == 1, report; assert report["estimated_usd"] == 2.0, report'
"$VENV_CONDUCTOR" doctor >/dev/null
if "$VENV_CONDUCTOR" doctor --strict >/dev/null 2>&1; then
  echo "strict doctor unexpectedly accepted unverified default pricing" >&2
  exit 1
fi
"$VENV_CONDUCTOR" uninstall --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md"

echo "codex-conductor e2e: PASS"
