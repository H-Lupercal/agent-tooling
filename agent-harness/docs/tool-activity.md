# Tool activity

This ledger distinguishes tooling observations from implementation authorship. Commands are
recorded only when they were actually run, with machine-readable counterparts in
[`tool-activity.jsonl`](tool-activity.jsonl).

| Tool | Operation | Evidence | Outcome |
| --- | --- | --- | --- |
| Toolbelt | Repository scan | `toolbelt scan --path . --json` | Scanned 221 files and wrote no files. |
| Toolbelt | Capability discovery | `toolbelt discover --path . --json` | Observed Ruff and Pyright; adopted no managed tools. |
| Toolbelt | Readiness check | `toolbelt doctor --path . --json` | Ready, with a warning that no v2 declaration exists. |
| Conductor | Admission status | `conductor status --last --pretty` | Admission mode; pricing unverified; no routing savings claimed. |
| Toolbelt | Package scan | `toolbelt scan --path agent-harness --json` | Scanned 33 files (218,163 bytes), with no warnings or writes. |
| Toolbelt | Package capability discovery | `toolbelt discover --path agent-harness --json` | Detected unmanaged Ruff and Pyright plus the Codex-native filesystem and Git capabilities; changed no declarations. |
| Toolbelt | Package readiness | `toolbelt doctor --path agent-harness --json` | Ready with zero errors and the expected warning that no v2 declaration exists. |
| Conductor | Final run report | `PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last` | Run `019f5538-c3c6-7021-b0dd-87e383790d8f`: admission mode, 2 unknown-tier reservations completed, pricing unverified, measured and estimated cost $0, savings unavailable outside routing mode. |

No code authorship attributed to Toolbelt or Conductor.

The first final-report attempt was sandboxed and could not create SQLite sidecar access for
the read-only database under `~/.codex`. Re-running the same report with approved access
succeeded; the successful result above is the final evidence.
