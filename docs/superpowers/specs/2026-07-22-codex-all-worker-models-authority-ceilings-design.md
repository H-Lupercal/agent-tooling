# Codex All-Worker Models and Authority Ceilings

## Summary

Make every configured Codex model available as a native worker override while preserving a
non-increasing authority lattice across model generation, model capability, and reasoning
effort. A worker may equal its orchestrator on model and effort, but it may never exceed the
orchestrator in any authority dimension. Descendants use their own effective model and effort
as the ceiling for subsequent workers.

This change spans the local Codex 0.145.0 source fork and Codex Conductor. Codex owns native
worker selection and effective child configuration. Conductor owns the configured authority
ladder, admission decision, capacity reservation, lifecycle accounting, and strict diagnostics.

## Goals

- Expose these cached models as explicit Codex worker choices:
  - `gpt-5.6-sol`
  - `gpt-5.6-terra`
  - `gpt-5.6-luna`
  - `gpt-5.5`
  - `gpt-5.4`
  - `gpt-5.4-mini`
  - `gpt-5.3-codex-spark`
- Preserve per-call reasoning-effort selection.
- Allow equal model and equal or lower effort.
- Reject workers that exceed the caller's generation, capability, or effort.
- Carry the worker's effective model and effort into descendant ceilings.
- Keep ordinary global agent capacity, tier concurrency, depth, and budget enforcement.
- Make strict doctor and status distinguish selectable tiers from merely cached models.
- Preserve the existing spawn model/effort visibility in CLI and VS Code surfaces.

## Non-Goals

- Do not raise or lower Codex's global agent-count limit.
- Do not raise or lower per-tier `max_concurrent`, maximum depth, or run budget.
- Do not change service-tier selection.
- Do not rewrite a caller's explicit model or effort request.
- Do not claim a model is live-selectable based only on historical ledger compatibility.
- Do not modify Claude Code behavior.

## Authority Model

Each configured model has:

- a generation rank;
- a capability rank;
- a maximum governed reasoning effort;
- its provider-advertised supported reasoning efforts.

A requested worker is admissible only when:

1. `worker.generation_rank <= caller.generation_rank`;
2. `worker.capability_rank <= caller.capability_rank`;
3. `worker.effort_rank <= caller.effective_effort_rank`;
4. the worker model supports the requested effort;
5. all independent budget, depth, capacity, concurrency, and risk rules pass.

Equality is valid. For example, `gpt-5.5/medium` may spawn another
`gpt-5.5/medium`, subject to ordinary capacity and budget rules. It may not spawn
`gpt-5.5/high` or any GPT-5.6 model. It may spawn `gpt-5.4/medium`, but not
`gpt-5.4/high`.

The generation and capability checks are independent. This prevents a lower-capability model
from reaching a nominally older but more capable model. For example, Luna cannot spawn GPT-5.5
merely because GPT-5.5 has a lower generation rank.

The current special `same_tier_spawns_from_root_max` exception is removed from admission.
Same-model workers instead use the same ordinary global capacity, tier concurrency, depth,
and budget checks as cross-model workers. This does not change those limits.

## Effort Resolution

An explicit effort is accepted unchanged only when it is canonical, supported by the target
model, no higher than the target tier's governed maximum, and no higher than the caller's
effective effort.

When model and effort are both omitted on a full-history fork, the child inherits both exactly.

When an explicit worker model is selected and effort is omitted, Codex chooses the highest
provider-supported canonical effort that does not exceed either:

- the caller's effective effort; or
- the target tier's governed maximum effort.

This permits a medium-effort caller to select a low-only worker such as Spark without creating
an accidental effort upgrade. The resolved effort—not merely the request—is emitted through
the spawn lifecycle and becomes the descendant ceiling.

If no supported effort exists at or below both ceilings, the spawn is denied with the supported
efforts and both effective ceilings in the error. Codex and Conductor never silently raise effort.

## Codex Changes

The native spawn tool will derive its model choices from the active, picker-visible model cache
instead of requiring the worker's `multi_agent_version` to equal the orchestrator's version.
The existing model-summary bound remains finite but is increased sufficiently to include the
seven configured worker models.

The child continues to inherit the active multi-agent feature configuration. Models marked v1
or without a remote multi-agent marker may therefore run as v2 workers under the explicitly
enabled local v2 runtime. Their ability to spawn descendants remains governed by the same
effective authority and Conductor hooks.

Codex validates provider-supported effort and computes the safe omitted-effort value before
creating the child. The effective model and effort are included in lifecycle-visible metadata
so CLI, VS Code, hooks, and Conductor accounting observe the same values.

Codex does not duplicate Conductor's generation or capability ladder. Those ranks are deployment
policy, not provider model metadata. Conductor remains the fail-closed authority for cross-model
admission.

## Conductor Changes

The verified Codex contract lists all seven explicit model choices and retains the canonical
effort selector.

Configured `auto` tiers are selectable only when the model is both:

- present in the active Codex model cache; and
- exposed by the verified native spawn selector.

Strict doctor fails when a configured task class points at a cached but unselectable tier.
Status reports cached and selectable state honestly.

Routing policy continues to enforce independent generation, capability, target-model effort,
and caller-effort ceilings. It permits equality and removes the special same-tier root count
gate. Capacity, per-tier concurrency, maximum depth, run budget, risk ownership, and lifecycle
correlation remain unchanged.

For explicit model plus omitted effort, the hook and Codex must agree on the deterministic safe
effort. The committed reservation records that resolved value. Any disagreement fails closed
before work is credited or savings are reported.

## Data Flow

1. Codex builds `spawn_agent` from the active model cache and exposes all seven configured
   picker-visible models plus the effort selector.
2. The orchestrator submits model and optional effort.
3. The Conductor `PreToolUse` hook resolves the caller's effective model and effort.
4. Conductor validates generation, capability, effort, risk, depth, capacity, concurrency, and
   budget, then reserves the exact effective worker selection.
5. Codex validates provider support, resolves omitted effort deterministically, and creates the
   child with that effective model and effort.
6. `PostToolUse`, `SubagentStart`, and `SubagentStop` correlate the child with the reservation.
7. The child model and effort become its descendant authority ceiling.
8. CLI and VS Code display the effective model, effort, and task name from the same lifecycle
   data used for accounting.

## Failure Handling

- Unknown or non-canonical model: deny and list verified selectable models.
- Model absent from the live cache: deny; do not fall back.
- Model above generation or capability ceiling: deny with the relevant caller ceiling.
- Effort above caller or target ceiling: deny with allowed efforts.
- Cached but selector-unreachable model: strict doctor failure.
- Codex/Conductor effective-selection disagreement: deny and cancel the reservation.
- Provider rejection after admission: mark the reservation failed; never report completed work.
- Missing lifecycle correlation: retain recoverable state and fail strict accounting.

## Testing

### Codex

- Tool-schema/description tests list all seven worker models.
- A v2 orchestrator can select v1-marked and unmarked cached models.
- Explicit effort is preserved when supported and within the caller ceiling.
- Omitted effort resolves to the highest supported effort at or below both ceilings.
- Effective model and effort appear in child configuration and lifecycle metadata.
- Existing full-history inheritance behavior remains exact.
- Existing hook correlation and encrypted-message behavior remain intact.

### Conductor

- Contract tests require all seven model enum values.
- Selectability is the intersection of cache presence and verified selector values.
- Strict doctor fails for cached but selector-unreachable routed tiers.
- Equal model/equal effort is allowed without a special same-tier count gate.
- Higher effort, newer generation, and higher capability are independently denied.
- Descendants use their effective reduced model and effort ceilings.
- Omitted effort resolves identically to Codex and is recorded in the reservation.
- Existing budget, depth, concurrency, high-risk, accounting, and recovery tests remain green.

### Live Verification

- Build and install the local Codex fork without overwriting unrelated work.
- Repair/reinstall Conductor through its transactional installer.
- Run strict doctor and contract canaries.
- Probe each model with an allowed effort from a sufficiently authoritative root.
- Probe representative denials:
  - `5.5/medium -> 5.5/high`;
  - `5.5/medium -> 5.6-luna/low`;
  - `5.6-luna/medium -> 5.5/low`.
- Verify the ledger records exact model and effort for every successful probe.
- Verify the CLI and VS Code lifecycle surfaces show effective model, effort, and task.

## Acceptance Criteria

- All seven configured models are explicit native worker choices when present in the active cache.
- A worker never exceeds its caller in generation, capability, or effective effort.
- Equal model/equal effort is permitted subject only to ordinary independent limits.
- Omitted effort never creates an upgrade and is resolved consistently across Codex and
  Conductor.
- Descendant ceilings use effective child authority.
- Strict doctor reports unreachable configured tiers rather than presenting them as enabled.
- Live probes confirm both successful cross-model routing and fail-closed authority denials.
- No unrelated Codex-fork or Agent Tooling changes are overwritten.
