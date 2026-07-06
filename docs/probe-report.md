# Probe Report

Recorded from the Toolbelt specification dated 2026-07-06. This file contains verified and sanitized facts only; no mutating probes were run while creating these support files.

## Verified CLI Facts

- `claude mcp list` has no `--json` flag and performs health checks, so Toolbelt must not use it for state listing.
- `claude plugin list --json` exists and can be used only as a probe cross-check.
- `codex mcp list --json` exists and can be used only as a probe cross-check.
- `claude plugin marketplace add <source>` accepts a URL, path, or GitHub repository.
- MCP mutation goes through official CLIs; live state listing reads config files.

## Sanitized State Fixtures

- `tests/fixtures/state/claude_state.json`: sanitized `~/.claude.json` shape with top-level and project `mcpServers`.
- `tests/fixtures/state/installed_plugins.json`: sanitized Claude plugin registry containing `superpowers@claude-plugins-official`.
- `tests/fixtures/state/codex_config.toml`: sanitized Codex config containing `[mcp_servers.playwright]`.
- `tests/fixtures/state/mcp.json`: sample project `.mcp.json` containing a Playwright MCP server.

## Deferred Mutating Probes

The following were specified as Step 0 probes but were not run here:

- Duplicate `claude mcp add -s project probe-tb -- echo hi` behavior.
- Duplicate `codex mcp add probe-tb -- echo hi` behavior.
- Duplicate `claude plugin install superpowers@claude-plugins-official` behavior.

Implementation should record the resulting exit codes, stderr patterns, and any already-exists constants before enabling live apply behavior.
