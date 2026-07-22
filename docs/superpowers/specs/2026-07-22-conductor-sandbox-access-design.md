# Conductor Sandbox Access and Claude Repair

## Summary

Keep Conductor's provider-local SQLite databases and WAL behavior unchanged. Fix the
recurring Codex diagnostic failure through narrow operational guidance: when a Codex
sandbox cannot create SQLite WAL sidecars below `~/.codex/conductor/state`, rerun only
the requested Conductor command with explicit approval outside that restriction. Repair
the existing Claude Code installation through Conductor's installer, then validate both
providers independently.

## Constraints and Assumptions

- The Codex database is healthy: schema version 3, WAL mode, and SQLite integrity check
  all passed outside the sandbox.
- Do not use SQLite `immutable=1`, `nolock=1`, or a copied live database as a reporting
  fallback because those approaches can omit or race WAL data.
- Do not relocate either provider's database or change the schema.
- Do not broaden access to all of `~/.codex` or `~/.claude`; escalation must be limited
  to the requested Conductor command.
- The user's approval authorizes repairing the live Claude Code Conductor installation.
- Claude Code does not need Codex-specific escalation syntax. Its instructions must use
  the Claude provider explicitly.

## Affected Files and State

- `/home/neil/AGENTS.md`: add durable Codex executor guidance for provider-aware
  Conductor diagnostics and narrow escalation on the known SQLite access failure.
- `/home/neil/CLAUDE.md`: add planner-facing provider guidance without granting Claude
  implementation authority.
- `/home/neil/.claude/settings.json`, `/home/neil/.claude/CLAUDE.md`, and
  `/home/neil/.claude/conductor/`: let `conductor install --provider claude --repair`
  create or repair its managed hooks, policy block, and manifest.
- No source files, database files, schemas, or Codex installation assets are manually
  edited.

## Behavior

### Codex

1. Run the requested `conductor` command normally.
2. If it fails with `cannot initialize conductor store: unable to open database file`
   and the store is below `~/.codex/conductor/state`, rerun that same command with
   narrowly scoped sandbox escalation.
3. Never substitute an immutable or copied database view.
4. Use `--provider codex` when provider selection matters.

### Claude Code

1. Use `--provider claude` for Conductor diagnostics and installation checks.
2. Access `~/.claude/conductor/state` normally; do not include Codex tool-specific
   escalation instructions.
3. Repair managed installation files only through Conductor's repair command.

## Error Handling

- If Codex escalation is denied, report the denied access and exact command without
  claiming a database fault.
- If Claude repair fails, preserve the prior installation transaction and report the
  installer's failure; do not hand-edit partially managed files.
- A missing Claude store before its first provider session is a controlled warning, not
  database corruption.
- Pricing warnings are unrelated to database access and remain visible.

## Verification

- Run `conductor doctor --provider codex` with the access required for the installed
  Codex store; require `store schema=3 journal=wal integrity=ok` and `overall: OK`.
- Run `conductor status --last --pretty --provider codex` and
  `conductor report --last --provider codex` successfully.
- Run `conductor doctor --provider claude`; require all installation, hook, manifest,
  and policy checks to pass. A pre-session missing-store warning is acceptable.
- Run the repository's relevant documentation/configuration checks.
- Run the required final `conductor report --last` and include its table in the handoff.

## Non-Goals

- No database migration, fallback reader, WAL policy change, sandbox-wide permission
  relaxation, pricing configuration, or provider session launch.
