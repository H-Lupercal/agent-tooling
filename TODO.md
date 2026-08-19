# TODO: Improve downward delegation for trivial tasks in Conductor policy

## Issue
- Agent tooling (including codex-conductor) should delegate small, repetitive, or simple tasks to smaller models.
- Current behavior suggests Codex often stays at the main model/effort level instead of using lower-cost workers.
- This appears to be an orchestration policy gap more than a routing capability gap.

## What I found
- Conductor supports spawning lower-capability models with lower reasoning effort.
- The Codex contract exposes both `model` and `reasoning_effort`.
- Policy already permits downward delegation while preventing upward escalation.
- The installed orchestration policy appears to define tiers, but the current defaults can inherit the current model/effort (via `fork_turns="all"`) when no override is set.
- This explains why trivial work can still use the same worker level.

## Likely root cause
- The behavior issue is mainly an **orchestration policy** expectation mismatch, not a Conductor routing limitation.
- `codex-conductor/src/conductor/assets/policy/orchestration-policy.md` is the right target file (managed policy asset), not an installed AGENTS.md.

## Policy behavior to emphasize
- Existing ladder should be kept:
  - **Sol / ultra**: decomposition, architecture, integration, review, high-risk work.
  - **Terra / appropriate effort**: normal implementation/debugging.
  - **Luna / low-medium**: narrow, straightforward tasks (tests, docs, mechanical edits, renames, config changes).
  - **Codex Spark / low**: extremely simple, repetitive work (search, summaries, boilerplate, formatting, extraction).

## Required rule to add
- Prefer downward delegation.
- Do not use the same model/effort for work that a cheaper worker can complete.
- Small, repetitive, mechanical, bounded, or low-reasoning tasks should default to the cheapest capable model at the lowest sufficient effort.
- Reserve same-level workers for tasks that truly require that capability.
- Do not default to `fork_turns="all"` by convenience.
- Delegate by task **difficulty**, not project importance.
  - Example: a 500-file rename may be important but cognitively trivial; it should go to Luna/Spark while Sol remains coordinator.

## Suggested change (2-part)
1. **Behavior change in policy**
   - Strengthen `codex-conductor/src/conductor/assets/policy/orchestration-policy.md` so delegation to cheaper models is explicit and prioritized.
2. **Regression check**
   - Add/verify a check that spawned tasks include explicit lower `model`/`reasoning_effort` overrides.
   - Confirm actual spawns are downward from current context where applicable.
   - Ensure this is a policy-level behavior adjustment, not a core Conductor routing redesign.

## Additional note
- Reference: repository is `H-Lupercal/agent-tooling`.
