#!/usr/bin/env bash
# Hermetic black-box smoke for the installed v2 CLI. All writes stay inside a
# throwaway repository and apply is preflight-only.
set -euo pipefail

repo="$(cd "$(dirname "$0")/.." && pwd)"
tmp="$(mktemp -d)"

cleanup() {
  python3 -c 'import shutil, sys; shutil.rmtree(sys.argv[1])' "$tmp"
}
trap cleanup EXIT

printf '%s\n' '[project]' 'name = "fixture"' 'version = "1.0.0"' 'dependencies = ["pytest"]' >"$tmp/pyproject.toml"
printf '%s\n' \
  '{' \
  '  "schema_version": 2,' \
  '  "provider": "combined",' \
  '  "provider_version": null,' \
  '  "status": "known",' \
  '  "native": [],' \
  '  "installed": [],' \
  '  "managed": [],' \
  '  "errors": []' \
  '}' >"$tmp/capabilities.json"

if command -v toolbelt >/dev/null 2>&1; then
  toolbelt_cli=(toolbelt)
elif [[ -x "$repo/.venv/bin/python" ]]; then
  toolbelt_cli=("$repo/.venv/bin/python" -m toolbelt)
else
  export PYTHONPATH="$repo/src${PYTHONPATH:+:$PYTHONPATH}"
  toolbelt_cli=(python3 -m toolbelt)
fi

run_toolbelt() { "${toolbelt_cli[@]}" "$@"; }

run_toolbelt catalog validate --json >/dev/null
run_toolbelt scan --path "$tmp" --json >/dev/null
run_toolbelt discover --path "$tmp" --capabilities "$tmp/capabilities.json" --json >/dev/null
run_toolbelt plan \
  --path "$tmp" \
  --capabilities "$tmp/capabilities.json" \
  --allow-network \
  --out .toolbelt/plan.json \
  --json >/dev/null
run_toolbelt apply \
  --path "$tmp" \
  --capabilities "$tmp/capabilities.json" \
  --allow-network \
  --plan "$tmp/.toolbelt/plan.json" \
  --dry-run \
  --json >/dev/null
run_toolbelt status --path "$tmp" --json >/dev/null
run_toolbelt doctor --path "$tmp" --capabilities "$tmp/capabilities.json" --json >/dev/null

printf 'e2e PASS\n'
