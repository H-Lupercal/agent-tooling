#!/usr/bin/env bash
set -euo pipefail

if [[ "${RUN_LIVE:-}" != "1" ]]; then
  echo "Set RUN_LIVE=1 to run live smoke tests."
  exit 0
fi

echo "Live smoke placeholder: run only after approving Codex/API spend."
