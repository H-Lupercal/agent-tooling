# Probe Report

Status: offline/manual-derived scaffold.

The Codex implementation follows the current official Codex manual for user
hook installation: `~/.codex/hooks.json` with CamelCase event names
`SessionStart`, `PreToolUse`, `SubagentStart`, and `SubagentStop`.

The Claude Code implementation follows Claude's hook schema in
`~/.claude/settings.json`, merging managed entries for `SessionStart`,
`PreToolUse`, `SubagentStart`, and `SubagentStop` while preserving existing
non-conductor hooks.

Live probes were not run during this build to avoid spending Codex/API usage or
Claude usage.
Before relying on this in an expensive production workflow, run:

```bash
cd /path/to/codex-conductor
RUN_LIVE=1 make probe
```

The hook payload adapters are intentionally tolerant of documented CamelCase
event names and earlier snake_case binary strings.
