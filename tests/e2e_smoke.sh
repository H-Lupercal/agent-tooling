#!/usr/bin/env bash
# Hermetic black-box smoke: drives the installed `toolbelt` CLI against a
# throwaway repo using the fake claude/codex bins and the e2e test catalog.
# Mutates only $tmp; never touches real harness state.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

mkdir -p "$tmp/.git"
printf 'hello\n' > "$tmp/app.txt"

export TOOLBELT_CATALOG="$repo/tests/fixtures/e2e_catalog.toml"
export TOOLBELT_CLAUDE_BIN="$repo/tests/fake_bin/claude"
export TOOLBELT_CODEX_BIN="$repo/tests/fake_bin/codex"
export FAKE_BIN_LOG="$tmp/fake.log"
export TOOLBELT_CLAUDE_STATE="$tmp/claude_state.json"
export TOOLBELT_CODEX_CONFIG="$tmp/codex_config.toml"
export TOOLBELT_CLAUDE_PLUGINS="$tmp/installed_plugins.json"
: > "$FAKE_BIN_LOG"

fail() { printf 'e2e FAIL: %s\n' "$1" >&2; exit 1; }

if command -v toolbelt >/dev/null 2>&1; then
  toolbelt_cli=(toolbelt)
else
  export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"
  toolbelt_cli=(python3 -m toolbelt)
fi

run_toolbelt() { "${toolbelt_cli[@]}" "$@"; }

run_toolbelt scan --path "$tmp" >/dev/null || fail "scan exited nonzero"
run_toolbelt plan --path "$tmp" >/dev/null || fail "plan exited nonzero"
[ -f "$tmp/.toolbelt/plan.json" ] || fail "plan.json not written"

run_toolbelt apply --path "$tmp" --yes >/dev/null || fail "apply exited nonzero"
grep -q "mcp add" "$FAKE_BIN_LOG" || fail "no 'mcp add' in fake log"
grep -q "plugin install" "$FAKE_BIN_LOG" || fail "no 'plugin install' in fake log"
[ -f "$tmp/.claude/skills/e2e/SKILL.md" ] || fail "scaffold file not created"
grep -q "toolbelt managed" "$tmp/.gitignore" || fail "managed .gitignore block missing"
python3 - "$tmp" <<'PY' || fail "e2e-mcp not recorded installed"
import json, sys
m = json.load(open(f"{sys.argv[1]}/.toolbelt/manifest.json"))
assert m["tools"]["e2e-mcp"]["state"] == "installed", m["tools"]["e2e-mcp"]["state"]
PY

run_toolbelt status --path "$tmp" --json >/dev/null || fail "status exited nonzero"
run_toolbelt verify --path "$tmp" --json >/dev/null || fail "verify exited nonzero"
run_toolbelt reconcile --path "$tmp" >/dev/null || fail "reconcile exited nonzero"
run_toolbelt guard --path "$tmp" >/dev/null || fail "guard exited nonzero"

out="$(run_toolbelt remove --path "$tmp" --tool e2e-skill --dry-run)" || fail "remove exited nonzero"
printf '%s\n' "$out" | grep -q "remove e2e-skill" || fail "remove card missing tool id"

printf 'e2e PASS\n'
