# Tool activity

No code authorship attributed to Toolbelt or Conductor.

| Actor | Operation | Evidence |
|---|---|---|
| toolbelt | scan | `toolbelt scan --path . --json` |
| toolbelt | discover | `toolbelt discover --path . --json` |
| conductor | status | `conductor status --last --pretty` |
| verification | test | `PYTHONPATH=src ../codex-conductor/.venv/bin/python -m pytest tests/test_activity.py -q` |
| codex | author | `git diff -- install-rehearsal` |
