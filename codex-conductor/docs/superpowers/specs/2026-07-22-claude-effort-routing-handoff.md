# Claude Code Effort Routing Handoff

## Requested outcome

Give the Claude Code orchestrator the same model-led control now implemented
for Codex: it chooses a worker model and effort, while Conductor only validates
that the child does not exceed the caller's transitive generation, capability,
or effort ceiling.

## Blocking issue

Claude Code 2.1.217 documents `effort` for CLI/session configuration and for
subagent definitions. The installed live `Agent`/Task tool surface was verified
to expose a per-call model selector, but a per-call effort selector was not
verified. Adding an `effort` property to Conductor's Claude golden contract
without proving that the live tool accepts it would fabricate enforcement and
could incorrectly claim routing savings.

## Constraints for the Claude implementation

- Verify the exact live Agent tool input and hook payload fields for requested
  and active effort. Capture golden fixtures from that surface.
- If effort is selectable only through subagent definitions, design and verify
  that path explicitly; do not pretend it is a Task-call override.
- Preserve model aliases and the existing PostToolUse child-ID correlation.
- Require both model and effort authority before claiming full routing control.
  If effort cannot be observed and blocked, keep the honest lower capability
  mode for effort-sensitive launches.
- Never rewrite a request or automatically select a fallback. Return the
  caller ceiling so Claude can retry using its task context.
- Persist accepted effort in the now-nullable reservation field. Historical
  and unchanged Claude reservations legitimately contain `NULL`.
- Add transitive tests proving no descendant can recover a higher model
  generation, capability rank, or effort than its parent.

## Files intentionally untouched by the Codex change

- `src/conductor/providers/claude.py`
- `src/conductor/assets/contracts/claude-current.json`
- `src/conductor/assets/config/conductor.claude.toml`
- Claude golden fixtures, policy template, and installer tests
