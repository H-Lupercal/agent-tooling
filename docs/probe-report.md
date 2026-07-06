# Probe Report

Status: offline/manual-derived scaffold.

The implementation follows the current official Codex manual for user hook
installation: `~/.codex/hooks.json` with CamelCase event names
`SessionStart`, `PreToolUse`, `SubagentStart`, and `SubagentStop`.

Live probes were not run during this build to avoid spending Codex/API usage.
Before relying on this in an expensive production workflow, run:

```bash
cd /path/to/codex-conductor
RUN_LIVE=1 make probe
```

The hook payload adapter is intentionally tolerant of both documented
CamelCase event names and earlier snake_case binary strings.
