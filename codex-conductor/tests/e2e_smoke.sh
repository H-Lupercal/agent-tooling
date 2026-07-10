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
  "$UV" pip install --link-mode=copy --python "$VENV_PY" "$ROOT"
else
  "$VENV_PY" -m pip install -q "$ROOT"
fi
export HOME="$TMP/home"
export USERPROFILE="$HOME"
mkdir -p "$HOME/.codex" "$HOME/.claude" "$TMP/bin"

# Doctor must be deterministic in CI, where the provider CLIs are not installed.
printf '%s\n' '#!/usr/bin/env bash' 'printf "codex-cli 0.5.0\\n"' >"$TMP/bin/codex"
printf '%s\n' '#!/usr/bin/env bash' 'printf "claude-code 2.0.0\\n"' >"$TMP/bin/claude"
chmod +x "$TMP/bin/codex" "$TMP/bin/claude"
export PATH="$TMP/bin:$PATH"

verify_pricing() {
  "$VENV_PY" -c \
    'from pathlib import Path; p=Path(__import__("sys").argv[1]); p.write_text(p.read_text(encoding="utf-8").replace("= 0.0", "= 1.0"), encoding="utf-8")' \
    "$1"
}

printf '%s\n' '[project]' 'name = "preserved-codex-setting"' >"$HOME/.codex/config.toml"
printf '%s\n' 'Preserve this operator policy.' >"$HOME/AGENTS.md"

"$VENV_CONDUCTOR" install --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md"
verify_pricing "$HOME/.codex/conductor/conductor.toml"
printf '%s\n' '{"models":[{"slug":"gpt-5.5"},{"slug":"gpt-5.4"},{"slug":"gpt-5.4-mini"},{"slug":"gpt-5.3-codex-spark"}]}' >"$HOME/.codex/models_cache.json"

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
  | "$VENV_PY" -c 'import json,sys; report=json.load(sys.stdin); assert report["tiers"]["frontier"]["completed"] == 1, report; assert report["measured_usd"] > 0, report; assert report["estimated_usd"] == 0, report; assert report["pricing_verified"], report'
"$VENV_CONDUCTOR" doctor --strict >/dev/null

printf '%s\n' '# tampered' >"$HOME/.codex/conductor/hooks/lifecycle.py"
if "$VENV_CONDUCTOR" install --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md" >/dev/null 2>&1; then
  echo "install unexpectedly replaced a modified managed file without --repair" >&2
  exit 1
fi
"$VENV_CONDUCTOR" install --repair --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md" >/dev/null
"$VENV_CONDUCTOR" doctor --strict >/dev/null
"$VENV_CONDUCTOR" uninstall --codex-home "$HOME/.codex" --agents-path "$HOME/AGENTS.md"
"$VENV_PY" -c \
  'from pathlib import Path; import sys; home=Path(sys.argv[1]); assert "preserved-codex-setting" in (home/".codex/config.toml").read_text(); assert "Preserve this operator policy." in (home/"AGENTS.md").read_text(); assert not (home/".codex/hooks.json").exists()' \
  "$HOME"

printf '%s\n' '{"permissions":{"allow":["Read"]},"hooks":{"Notification":[]}}' >"$HOME/.claude/settings.json"
printf '%s\n' 'Preserve this Claude policy.' >"$HOME/.claude/CLAUDE.md"
"$VENV_CONDUCTOR" install \
  --provider claude \
  --claude-home "$HOME/.claude" \
  --claude-md-path "$HOME/.claude/CLAUDE.md"
verify_pricing "$HOME/.claude/conductor/conductor.toml"

printf '%s\n' '{"session_id":"claude-run","model":"claude-opus-4-8"}' \
  | "$VENV_PY" "$HOME/.claude/conductor/hooks/session_start.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"session_id":"claude-run","model":"claude-opus-4-8","tool_use_id":"claude-call","tool_name":"Task","tool_input":{"subagent_type":"general-purpose","model":"sonnet","description":"implementation-task","prompt":"<CONDUCTOR_TASK>{\"schema_version\":1,\"task_name\":\"implementation-task\",\"task_class\":\"implementation\",\"risk_triggers\":[],\"owned_paths\":[\"src/implementation.py\"],\"acceptance_checks\":[\"pytest -q\"],\"new_task\":true}</CONDUCTOR_TASK>"}}' \
  | "$VENV_PY" "$HOME/.claude/conductor/hooks/pre_tool_use.py" \
  | "$VENV_PY" -c 'import json,sys; result=json.load(sys.stdin); assert result["hookSpecificOutput"]["permissionDecision"] == "allow", result'

printf '%s\n' '{"hook_event_name":"PostToolUse","session_id":"claude-run","tool_use_id":"claude-call","tool_name":"Task","tool_input":{"subagent_type":"general-purpose","model":"sonnet","description":"implementation-task","prompt":"<CONDUCTOR_TASK>{\"schema_version\":1,\"task_name\":\"implementation-task\",\"task_class\":\"implementation\",\"risk_triggers\":[],\"owned_paths\":[\"src/implementation.py\"],\"acceptance_checks\":[\"pytest -q\"],\"new_task\":true}</CONDUCTOR_TASK>"},"tool_response":{"agentId":"claude-child"}}' \
  | "$VENV_PY" "$HOME/.claude/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"hook_event_name":"SubagentStart","session_id":"claude-run","agent_id":"claude-child"}' \
  | "$VENV_PY" "$HOME/.claude/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

printf '%s\n' '{"hook_event_name":"SubagentStop","session_id":"claude-run","agent_id":"claude-child","status":"completed","usage":{"input_tokens":1000,"cache_read_input_tokens":100,"cache_creation_input_tokens":50,"output_tokens":100}}' \
  | "$VENV_PY" "$HOME/.claude/conductor/hooks/lifecycle.py" \
  | "$VENV_PY" -c 'import json,sys; assert json.load(sys.stdin) == {}'

"$VENV_CONDUCTOR" status --provider claude --run claude-run --pretty >/dev/null
"$VENV_CONDUCTOR" report --provider claude --run claude-run --json \
  | "$VENV_PY" -c 'import json,sys; report=json.load(sys.stdin); assert report["provider"] == "claude", report; assert report["tiers"]["standard"]["completed"] == 1, report; assert report["measured_usd"] > 0, report; assert report["estimated_usd"] == 0, report; assert report["pricing_verified"], report'
"$VENV_CONDUCTOR" doctor --provider claude --strict >/dev/null

printf '%s\n' '# tampered' >"$HOME/.claude/conductor/hooks/pre_tool_use.py"
if "$VENV_CONDUCTOR" install --provider claude --claude-home "$HOME/.claude" --claude-md-path "$HOME/.claude/CLAUDE.md" >/dev/null 2>&1; then
  echo "Claude install unexpectedly replaced a modified managed file without --repair" >&2
  exit 1
fi
"$VENV_CONDUCTOR" install \
  --provider claude \
  --repair \
  --claude-home "$HOME/.claude" \
  --claude-md-path "$HOME/.claude/CLAUDE.md" >/dev/null
"$VENV_CONDUCTOR" doctor --provider claude --strict >/dev/null
"$VENV_CONDUCTOR" uninstall \
  --provider claude \
  --claude-home "$HOME/.claude" \
  --claude-md-path "$HOME/.claude/CLAUDE.md"
"$VENV_PY" -c \
  'from pathlib import Path; import json,sys; home=Path(sys.argv[1]); settings=json.loads((home/".claude/settings.json").read_text()); assert settings["permissions"] == {"allow":["Read"]}; assert settings["hooks"] == {"Notification":[]}; assert "Preserve this Claude policy." in (home/".claude/CLAUDE.md").read_text()' \
  "$HOME"

echo "codex-conductor e2e: PASS"
