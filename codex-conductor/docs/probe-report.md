# Provider contract probe report

The packaged contracts target Codex CLI 0.144.0–0.x and Claude Code 1.x–2.x.
Local offline verification of the new selector surface used Codex CLI 0.145.0;
the existing Claude probe remains based on Claude Code 2.1.204. No model or API
calls were made.

Both installations register `SessionStart`, `PreToolUse`, `PostToolUse`,
`SubagentStart`, and `SubagentStop`. PostToolUse is required: it links the
pre-tool call ID to the child ID returned by the provider before lifecycle
events arrive. Conductor never falls back to FIFO matching when that link is
missing.

The Codex golden path uses the current hook fields: `session_id` for the run,
`tool_use_id` for a tool invocation, and `agent_id` for the returned child and
subagent lifecycle. Legacy aliases remain accepted for compatible 0.x payloads.

The Codex spawn schema exposes `model` and `reasoning_effort` overrides, so its
strongest honest mode is `routing` when all correlation fields match. The
verified model override choices are GPT-5.6 Sol and Terra, and the effort range
is low through ultra. Full-history spawns omit both overrides and inherit them.
The Claude `Task` schema still exposes a model selector and retains its current
routing behavior; no per-invocation Claude effort selector is asserted here.

Golden payload/schema fixtures and `conductor doctor --strict` detect drift.
The packaged probe checks local installation and contract state without
launching provider work:

```bash
make probe
```

Treat a failed canary, unknown CLI version, missing PostToolUse mapping, or
contract digest mismatch as unsupported until a reviewed contract update is
released. Any paid live-agent probe remains a deliberate operator action.
