#!/usr/bin/env bash
set -eu

out_dir="${1:-docs}"
state_dir="${2:-tests/fixtures/state}"
mkdir -p "$out_dir" "$state_dir"

report="$out_dir/probe-report.md"
{
  printf '# Probe Report\n\n'
  printf 'Generated: %s\n\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  printf '## Non-Mutating CLI Checks\n\n'

  printf '### claude mcp list --json\n\n'
  if claude mcp list --json >/tmp/toolbelt-claude-mcp-json.out 2>/tmp/toolbelt-claude-mcp-json.err; then
    printf 'Unexpected success.\n\n'
    sed 's/^/    /' /tmp/toolbelt-claude-mcp-json.out
  else
    printf 'Unavailable as expected.\n\n'
    sed 's/^/    /' /tmp/toolbelt-claude-mcp-json.err
  fi
  printf '\n'

  printf '### claude plugin list --json\n\n'
  if claude plugin list --json >/tmp/toolbelt-claude-plugin-json.out 2>/tmp/toolbelt-claude-plugin-json.err; then
    sed 's/^/    /' /tmp/toolbelt-claude-plugin-json.out
  else
    printf 'Command failed.\n\n'
    sed 's/^/    /' /tmp/toolbelt-claude-plugin-json.err
  fi
  printf '\n'

  printf '### codex mcp list --json\n\n'
  if codex mcp list --json >/tmp/toolbelt-codex-mcp-json.out 2>/tmp/toolbelt-codex-mcp-json.err; then
    sed 's/^/    /' /tmp/toolbelt-codex-mcp-json.out
  else
    printf 'Command failed.\n\n'
    sed 's/^/    /' /tmp/toolbelt-codex-mcp-json.err
  fi
  printf '\n'
} > "$report"

printf 'wrote %s\n' "$report"
