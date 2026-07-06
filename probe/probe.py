from __future__ import annotations

import os
import sys


def main() -> int:
    if os.environ.get("RUN_LIVE") != "1":
        print("Set RUN_LIVE=1 to run live Codex probes.")
        return 0
    print("Live probe harness placeholder: install hooks with --dry-run, then run codex exec probes manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
