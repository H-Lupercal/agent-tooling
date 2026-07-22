# Model and Effort Ceilings Design

## Goal

Allow current Codex and Claude Code orchestrators to request a worker model and
reasoning effort while guaranteeing that no descendant exceeds the initiating
orchestrator's model generation, configured capability rank, or effort.

Conductor remains a guardrail. The orchestrator decides whether to delegate,
how to divide work, and which permitted worker model and effort to request.
Conductor never rewrites a request or chooses a replacement worker.

## Evidence and defaults

The implementation targets the provider surfaces verified on 2026-07-22:

- Codex CLI 0.145.0 exposes `model` and `reasoning_effort` on spawned agents.
- Claude Code 2.1.217 supports model and effort configuration for subagents.
- Codex documents GPT-5.6 Sol, Terra, and Luna as its current family.
- Codex prices GPT-5.6 Sol at the same credit rates as GPT-5.5: 125 input,
  12.5 cached-input, and 750 output credits per million tokens.
- Codex describes Terra as competitive with GPT-5.5 at a lower cost and as the
  natural starting point for work previously assigned to GPT-5.5.

The packaged Codex ladder therefore uses GPT-5.6 Sol as the frontier default,
Terra for everyday work, and Luna for narrow repeatable work. GPT-5.5 remains
recognized so a run that starts on GPT-5.5 is governed without being upgraded.
An older parent may not spawn any GPT-5.6 worker, even when that worker is less
expensive.

Bundled dollar pricing remains zero until verified API-dollar rates are
available. The documented ChatGPT credit rates are not mislabeled as dollars.

## Architecture

Provider contracts declare model and effort selector paths independently.
Routing mode is available only when the installed provider contract proves
that Conductor can observe and block both requested dimensions. A contract
that cannot prove effort control stays admission-only and cannot claim effort
routing or savings.

The configuration defines explicit model authority rather than parsing model
names. Each model has:

- a provider-local generation rank, used to prevent GPT-5.5 to GPT-5.6 upgrades;
- a capability rank, used to prevent a worker from exceeding its caller even
  within one generation;
- supported effort levels, used to reject settings the model cannot run.

Effort has one canonical order: `low`, `medium`, `high`, `xhigh`, `max`, and
`ultra`. Provider adapters normalize provider spellings without changing the
requested setting.

## Request and decision flow

1. Session start records the root model and root effort from provider-owned
   hook data. Missing or unknown authority fails closed under the configured
   unknown-model posture.
2. The orchestrator submits a governed spawn with its chosen model and effort.
3. The provider adapter extracts both fields into the normalized operation.
4. Policy validates the existing envelope, identity, depth, risk, concurrency,
   and budget rules.
5. Policy independently verifies that the requested model generation,
   capability, and effort are no greater than the caller's effective values.
6. A valid request is reserved unchanged. The reservation records the exact
   requested model and effort.
7. A nested caller resolves its authority from its correlated reservation and
   provider lifecycle identity, so the ceiling propagates transitively.

The task-class ladder remains advisory policy about which models may own work,
but it does not silently choose a model or effort. A request must name the
configuration the orchestrator chose. When a provider has a documented
inheritance-only form that exposes no overrides, Conductor may accept it only
when the contract proves that both values inherit from the caller unchanged.

## Denials

Conductor never mutates tool input. It denies and gives the orchestrator an
actionable ceiling:

- `MISSING_MODEL_SELECTION` or `MISSING_EFFORT_SELECTION` when an enforced
  request cannot be proven safe;
- `MODEL_GENERATION_CEILING` when a worker belongs to a newer generation;
- `MODEL_CAPABILITY_CEILING` when a worker exceeds the caller's configured
  capability;
- `EFFORT_CEILING` when worker effort exceeds caller effort;
- `UNSUPPORTED_MODEL_EFFORT` when a model does not support the requested level;
- existing stronger-child, high-risk, depth, concurrency, and budget rules
  continue to apply.

The denial reports the caller's model and effort ceiling. The orchestrator may
retry with any permitted combination, keep the work itself, or restructure the
task. High-risk work is never downgraded merely to make delegation possible.

## Provider behavior

### Codex

Update the golden spawn contract to the current `spawn_agent` input, including
`model` and `reasoning_effort`. The contract remains version-bounded and golden
fixture tests detect schema drift. Codex negotiates routing only when both
selectors and correlated lifecycle hooks are present.

### Claude Code

Update the golden contract to the current `Agent`/compatible task input only
for fields verified in the installed release and official documentation.
Claude aliases are resolved before policy evaluation. If the live Agent hook
does not expose a per-invocation effort field, Conductor must use a verified
subagent definition or remain admission-only; it must not fabricate control.

## Persistence and compatibility

Add nullable effort fields through an additive SQLite migration. Existing runs
and reservations remain readable, but new enforced spawns require exact effort
authority. Status and reports display effort where known and label historical
unknowns honestly.

Installed version-2 TOML remains loadable. New model-authority fields receive
safe compatibility defaults only when they preserve the old ordering; ambiguous
or duplicate authority fails configuration validation. The installer updates
managed assets transactionally and never edits unrelated user configuration.

## Testing

Use test-driven changes for each behavior:

- schema validation for model authority and the full effort order;
- capability negotiation requiring verified model and effort selectors;
- Codex and Claude normalization of requested effort;
- policy tests for generation, capability, effort, supported-effort, missing
  selections, and unchanged valid requests;
- nested-reservation tests proving a descendant cannot recover higher authority;
- property tests asserting child generation, capability, and effort never
  exceed the caller for any allowed decision;
- migration and legacy-state tests for nullable historical effort;
- golden contract, installer, status, report, distribution, and end-to-end
  regression tests;
- the package `make check`, `make dist-test`, `make e2e`, and the monorepo
  release-contract test before completion.

## Non-goals

- No automatic worker selection or task decomposition.
- No automatic request rewriting or fallback.
- No model-quality inference from names or release dates.
- No conversion of ChatGPT credits into dollar pricing.
- No live provider installation, publication, deployment, or user-config
  mutation without separate authorization.
