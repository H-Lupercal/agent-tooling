# Provider contract probe report

The packaged contracts target Codex CLI 0.144.0–0.x and Claude Code 1.x–2.x. Local
offline verification used Codex CLI 0.144.0 and Claude Code 2.1.204. No model or
API calls were made.

Both installations register `SessionStart`, `PreToolUse`, `PostToolUse`,
`SubagentStart`, and `SubagentStop`. PostToolUse is required: it links the
pre-tool call ID to the child ID returned by the provider before lifecycle
events arrive. Conductor never falls back to FIFO matching when that link is
missing.

The Codex golden path uses the current hook fields: `session_id` for the run,
`tool_use_id` for a tool invocation, and `agent_id` for the returned child and
subagent lifecycle. Legacy aliases remain accepted for compatible 0.x payloads.

The Codex spawn schema exposes no child-model selector, so its strongest honest
mode is `admission`. The Claude `Task` schema exposes a model selector and can
negotiate `routing` when all correlation fields match the installed contract.

Golden payload/schema fixtures and `conductor doctor --strict` detect drift.
The packaged probe checks local installation and contract state without
launching provider work:

```bash
make probe
```

Treat a failed canary, unknown CLI version, missing PostToolUse mapping, or
contract digest mismatch as unsupported until a reviewed contract update is
released. Any paid live-agent probe remains a deliberate operator action.
