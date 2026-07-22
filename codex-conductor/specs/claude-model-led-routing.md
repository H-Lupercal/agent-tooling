# Claude Model-Led Routing (Effort Honestly Deferred)

## Summary

Give the Claude Code orchestrator the same **model-led** delegation control that
Codex received in commit `1350135`: the orchestrator names the worker model on
each `Task` call and Conductor validates that the chosen model does not exceed
the caller's transitive **generation** or **capability** ceiling — instead of the
current behavior, where the task class dictates the model and any other choice is
denied with `MODEL_MISMATCH`.

Reasoning **effort is intentionally NOT enforced for Claude**, and this is the
honest core of the design. First-hand verification (below) confirms the live
Claude Code `Task`/`Agent` spawn tool exposes a per-call `model` selector but
**no** per-call effort selector — effort is fixed by the chosen subagent
definition (`.claude/agents/*.md` frontmatter), which the PreToolUse hook payload
does not carry. Codex's own design already prescribes the response: enforce the
dimensions you can observe, and "keep the honest lower capability mode" for the
ones you cannot. Claude therefore gets model ceilings now; every Claude
reservation records `reasoning_effort = NULL`, and no effort claim is made.

This mirrors Codex's architecture without fabricating enforcement: the model
half is real and tested; the effort half is explicitly absent, contract-honest,
and guarded by a test so it cannot silently drift into a false claim.

## Verification of the blocker (evidence, not assumption)

- **Live tool surface (this environment, Claude Code 2.1.x, Opus 4.8):** the
  `Agent`/`Task` spawn tool exposes exactly these per-call inputs: `description`,
  `isolation`, `model`, `prompt`, `subagent_type`. There is **no**
  `effort`/`reasoning_effort` per-call parameter. The tool documentation states
  reasoning effort "comes from the agent definition's frontmatter
  (`.claude/agents/*.md`) or SDK `agents`."
- **Packaged contract already reflects this:** `claude-current.json` declares
  `model_selector_path: "model"` and **omits** `reasoning_effort_selector_path`.
- **Capability layer already encodes the asymmetry, and tests lock it:**
  `capabilities.contract_mode`/`negotiate` special-case `provider is
  Provider.CODEX` to require an effort selector for `ROUTING`; Claude reaches
  `ROUTING` on the model selector alone. This is asserted by
  `tests/test_capabilities.py::test_codex_contract_without_effort_control_cannot_claim_routing`
  and `::test_claude_keeps_existing_model_only_routing_contract`.

Conclusion: Claude is **already** in `OperatingMode.ROUTING`. The only thing
missing is that `policy.py` sends Claude routing through the legacy task-class
branch (`MODEL_MISMATCH`) instead of the model-led ceiling branch. This spec
redirects Claude routing into the model-led branch with effort enforcement gated
off.

## Constraints & Assumptions

**Hard constraints**

- **Do not fabricate effort enforcement.** Do **not** add
  `reasoning_effort_selector_path` to `claude-current.json` or its golden
  fixtures. Do not read subagent-definition files to synthesize an effort value.
- **Codex behavior must remain bit-identical.** The full existing suite
  (Codex policy, capabilities, doctor, golden-contract, property tests) must stay
  green. `capabilities.py` and `claude-current.json` are **not** modified.
- **Fail closed on missing authority.** A Claude cross-model spawn where either
  the caller or target tier lacks `generation_rank` must be denied
  `UNKNOWN_MODEL_AUTHORITY` (existing behavior); this is why the Claude ladder
  gains explicit ranks.
- **Conductor never rewrites a request or picks a replacement worker.** Denials
  return the caller's ceiling; the orchestrator retries or keeps the work.

**Decisions made (faithful emulation of Codex; flagged for review)**

1. **Effort-authority signal = `run.provider is Provider.CODEX`.** Policy uses
   the provider as the proxy for "contract exposes a verified per-call effort
   selector," because the capability layer already makes exactly this
   provider distinction and two capability tests guard it. A code comment plus a
   new contract-invariant test (Test Plan §T7) pin the coupling so that if a
   future Claude contract ever adds a verified effort selector, this line and its
   test must be updated together. *(Alternative rejected: threading an
   `effort_enforceable` flag through `RunContext`/`capabilities`, because it would
   change persisted `RunContext` shape and force edits across every Codex policy
   test's `_run` helper for no behavioral gain today.)*

2. **Omitted `model` on a Claude `Task` inherits the caller's model.** The
   Agent-tool default (omitting `model`) documents "runs on the parent's model."
   Conductor treats an omitted model as `requested_model = caller_model`
   (trivially within ceiling), rather than denying `MISSING_MODEL_SELECTION`.
   This matches Claude's real tool semantics and Codex's own inherit path
   (`fork_turns == "all"`). *(Alternative: require an explicit model and deny
   otherwise. Flip decision #2 if you prefer strictness.)*

3. **Claude ladder generation ranks: one shared generation for the current
   family.** `claude-opus-4-8`, `claude-sonnet-5`, `claude-haiku-4-5` all receive
   `generation_rank = 48`, with capability ordered by `capability_rank`
   (opus 100 > sonnet 25 > haiku 6). Rationale: Codex's family had monotonic
   version→capability, so version-numbered generations worked. Claude's naming is
   **non-monotonic** — Opus 4.8 is more capable than Sonnet 5 but has a lower
   version number — so a naive "version × 10" scheme (opus 48, sonnet 50) would
   wrongly forbid an Opus orchestrator from spawning a Sonnet worker
   (`MODEL_GENERATION_CEILING`). Treating the current shipped family as one
   generation lets `capability_rank` do the ordering and reserves higher
   `generation_rank` values for a genuinely newer future family. **Open question
   for review:** confirm this single-generation treatment and the capability
   values.

**Assumptions**

- `claude-fable-5` (present in `MODEL_ALIASES`) is **not** added to the ladder;
  a request naming it resolves to a model with no tier and is honestly denied
  `UNKNOWN_TARGET_MODEL`. This is acceptable and documented, not a bug.
- Claude `may_spawn` remains `true` only on the `frontier` (opus) tier, so
  `MODEL_CAPABILITY_CEILING` is structurally unreachable in the shipped ladder
  (the sole spawner is already the most capable). The ceiling is still
  implemented and tested against a constructed config so the guarantee holds if
  `may_spawn` is ever widened.

## Affected Files

**Modify**

- `src/conductor/policy.py` — generalize the model+effort ceiling branch from
  Codex-only to any `ROUTING` provider; gate the four effort checks behind
  `effort_enforced`. (Details in Implementation Plan.)
- `src/conductor/assets/config/conductor.claude.toml` — add
  `generation_rank` and `capability_rank` to all three tiers.
- `src/conductor/assets/policy/orchestration-policy.claude.md` — document that a
  Claude orchestrator now chooses the worker model (any model at or below its
  ceiling), that omitting `model` inherits the caller's model, and that effort is
  not enforced.
- `CHANGELOG.md` — add an entry under the current unreleased section.
- `README.md` — update the provider-status wording so Claude is described as
  model-led routing (model ceiling enforced; effort not enforced), matching the
  Codex entry's structure.
- `docs/probe-report.md` — note that Claude model-led routing is now active while
  no per-invocation Claude effort selector is asserted.
- `docs/superpowers/specs/2026-07-22-claude-effort-routing-handoff.md` — append a
  "Resolved by" line pointing at this spec and stating the effort half remains
  deferred by design.
- `docs/superpowers/specs/2026-07-22-model-effort-ceilings-design.md` — update the
  "Claude Code" provider subsection to reflect that model-led routing shipped and
  effort is deferred (was: "No Claude production code … change in this branch").

**Add (tests)**

- `tests/test_policy_claude.py` — new file: Claude model-led ceiling tests
  (T1–T6 below), mirroring `tests/test_policy_v2.py`'s Codex structure.

**Modify (tests)**

- `tests/test_config.py` — assert the Claude ladder now carries the expected
  `generation_rank`/`capability_rank` values.
- `tests/test_capabilities.py` — add T7 (contract-invariant guard).
- `tests/test_public_docs.py` — if it asserts README/CHANGELOG/policy content,
  update expectations for the new Claude wording.

**Do NOT modify**

- `src/conductor/providers/claude.py` (no effort plumbing needed; `resolve_caller`
  keeps `effort=""`, `normalize_request` keeps `requested_effort=None`).
- `src/conductor/capabilities.py`, `src/conductor/schemas.py`,
  `src/conductor/assets/contracts/claude-current.json`,
  `tests/fixtures/contracts/claude-current.json`,
  `tests/fixtures/contracts/claude-task.json`, `src/conductor/doctor.py`,
  `src/conductor/store.py`, `src/conductor/migrations.py`.

## Public Interfaces

No new public functions, env vars, or routes. Changes are internal to
`evaluate_policy` and the packaged Claude configuration.

**`conductor.claude.toml` tier additions** (exact keys/values):

```toml
[[tiers]]                     # frontier
model = "claude-opus-4-8"
generation_rank = 48
capability_rank = 100
# ...existing keys unchanged...

[[tiers]]                     # standard
model = "claude-sonnet-5"
generation_rank = 48
capability_rank = 25
# ...existing keys unchanged...

[[tiers]]                     # mini
model = "claude-haiku-4-5"
generation_rank = 48
capability_rank = 6
# ...existing keys unchanged...
```

`generation_rank`/`capability_rank` are `PositiveInt | None` on `TierConfig`
(`schemas.py:166-167`); no schema change is required. Existing invariants hold:
`relative_cost_weight` remains non-increasing (100, 25, 6).

**`evaluate_policy` behavior** (signature unchanged, `policy.py:42-52`). New
decision outcomes reachable for Claude (`run.provider is Provider.CLAUDE`,
`run.mode is OperatingMode.ROUTING`):

| Rule | When |
|------|------|
| `ALLOW` / `BUDGET_WARNING` | chosen model ≤ caller ceiling; reservation `reasoning_effort = NULL` |
| `UNKNOWN_TARGET_MODEL` | requested model has no tier (e.g. `claude-fable-5`) |
| `TARGET_MODEL_DISABLED` | requested model's tier is not enabled |
| `UNKNOWN_MODEL_AUTHORITY` | cross-model spawn and either tier lacks `generation_rank` |
| `MODEL_GENERATION_CEILING` | target `generation_rank` > caller's |
| `MODEL_CAPABILITY_CEILING` | target `effective_capability_rank` > caller's |
| `HIGH_RISK_REQUIRES_FRONTIER` / `HIGH_RISK_CALLER_NOT_FRONTIER` | high-risk work off frontier |
| `STRICTLY_CHEAPER_REQUIRED` / `SAME_TIER_LIMIT` | same-model spawn outside the bounded root exception |
| `CALLER_MAY_NOT_SPAWN`, `DEPTH_LIMIT`, `CONCURRENCY_CAP`, `BUDGET_CAP` | unchanged shared rules |

Claude must **never** emit `MISSING_EFFORT_SELECTION`, `EFFORT_CEILING`,
`UNKNOWN_CALLER_EFFORT`, `UNKNOWN_TARGET_EFFORT`, or `UNSUPPORTED_MODEL_EFFORT`.

## Implementation Plan

Ordered; step 1 and step 2 can proceed in parallel, but tests (step 3) depend on
both.

### Step 1 — Add authority ranks to the Claude ladder

Edit `src/conductor/assets/config/conductor.claude.toml` to add the two ranks per
tier as shown in Public Interfaces. Change nothing else (keep `reasoning_effort`,
`pricing`, `task_classes`, `may_spawn`, weights as-is).

### Step 2 — Generalize the policy ceiling branch

In `src/conductor/policy.py`, replace the Codex-only gate and its block opener
(currently `policy.py:119-123`):

```python
forced_frontier = envelope.task_class == "high_risk" or bool(envelope.risk_triggers)
codex_routing = run.provider is Provider.CODEX and run.mode is OperatingMode.ROUTING
requested_effort: str | None = None

if codex_routing:
    requested_model = _requested_model(operation)
    requested_effort = _requested_effort(operation)
    inherits_authority = (
        operation.payload.get("fork_turns") == "all"
        and requested_model is None
        and requested_effort is None
    )
    if inherits_authority:
        requested_model = caller_model
        requested_effort = caller_effort
    if requested_model is None:
        return _result(False, "MISSING_MODEL_SELECTION", ...)
    if requested_effort is None:
        return _result(False, "MISSING_EFFORT_SELECTION", ...)
```

with a model-led gate that admits any `ROUTING` provider and resolves the
requested model/effort per authority:

```python
forced_frontier = envelope.task_class == "high_risk" or bool(envelope.risk_triggers)
model_led_routing = run.mode is OperatingMode.ROUTING
# Effort is enforced only for a provider whose contract exposes a VERIFIED
# per-call reasoning-effort selector. Today that is Codex alone: the Claude
# Task tool exposes `model` but no per-call effort field. This proxy is
# guarded by capabilities.py and tests/test_capabilities.py
# (test_codex_contract_without_effort_control_cannot_claim_routing,
#  test_claude_keeps_existing_model_only_routing_contract) and by T7 below.
# If a future Claude contract adds a verified effort selector, update this
# line and T7 together.
effort_enforced = run.provider is Provider.CODEX
requested_effort: str | None = None

if model_led_routing:
    requested_model = _requested_model(operation)
    if effort_enforced:
        requested_effort = _requested_effort(operation)
        inherits_authority = (
            operation.payload.get("fork_turns") == "all"
            and requested_model is None
            and requested_effort is None
        )
        if inherits_authority:
            requested_model = caller_model
            requested_effort = caller_effort
        if requested_model is None:
            return _result(
                False,
                "MISSING_MODEL_SELECTION",
                "routing requires the orchestrator to choose a worker model",
            )
        if requested_effort is None:
            return _result(
                False,
                "MISSING_EFFORT_SELECTION",
                "routing requires the orchestrator to choose worker reasoning effort",
            )
    else:
        # Claude: an omitted model inherits the caller's model (the documented
        # Agent-tool default). Per-call effort is unobservable, so it is left
        # unenforced and recorded as NULL.
        if requested_model is None:
            requested_model = caller_model
        requested_effort = None
    # ...unchanged model-authority checks continue here...
```

Then, **within the existing block body**, wrap the four effort-specific checks
(currently `policy.py:220-261`: `UNKNOWN_CALLER_EFFORT`, `UNKNOWN_TARGET_EFFORT`,
`EFFORT_CEILING`, `UNSUPPORTED_MODEL_EFFORT`) in `if effort_enforced:` so they are
skipped for Claude. Leave the model checks (`TARGET_MODEL_DISABLED`,
`forced_frontier`, `UNKNOWN_MODEL_AUTHORITY`, `MODEL_GENERATION_CEILING`,
`MODEL_CAPABILITY_CEILING`) and the trailing `strictly_cheaper` block unchanged —
they already reference only model/tier data and `requested_effort` (which is
`None` for Claude and flows into `_result(..., effort=requested_effort)` to
persist `NULL`).

The `else:` branch (currently `policy.py:289-360`, task-class admission) is now
reached only in `ADMISSION`/`OBSERVE`-style flows. Its `run.mode is
OperatingMode.ROUTING` sub-conditionals (including the `MODEL_MISMATCH` path)
become unreachable for real providers; **leave them as-is** to keep the diff
minimal and behavior-preserving. Do not delete them in this change.

No import changes are required (`Provider`, `OperatingMode`, `REASONING_EFFORTS`
are already imported).

### Step 3 — Tests, docs, and full verification

Write the tests in the Test Plan, update the docs listed in Affected Files, then
run the full verification gate (Acceptance Criteria).

## Error Handling

- **Missing generation authority (fail closed):** any Claude cross-model spawn
  where a tier lacks `generation_rank` → `UNKNOWN_MODEL_AUTHORITY`, denied. After
  Step 1 all shipped Claude tiers have ranks, so this fires only under a
  hand-edited ladder — which is the intended safe failure.
- **Unknown / disabled target model:** `UNKNOWN_TARGET_MODEL` /
  `TARGET_MODEL_DISABLED`, denied, caller ceiling reported.
- **Non-spawner caller** (sonnet/haiku): `CALLER_MAY_NOT_SPAWN`, unchanged.
- **High-risk work:** must stay on the frontier (opus); off-frontier callers or
  targets are denied via the existing `HIGH_RISK_*` rules.
- **Degraded/errored hook:** unchanged — governed Claude work is denied safely by
  `pre_tool_use.main`'s existing `CONDUCTOR_DEGRADED` path.
- **Effort:** never evaluated for Claude; `reasoning_effort` persists `NULL`. No
  effort-related denial rule may appear for a Claude run.

## Test Plan

New file `tests/test_policy_claude.py`, mirroring the helpers in
`tests/test_policy_v2.py` (`_run`, `_operation`, `_evaluate`) but with
`provider="claude"`, `provider_contract="claude-current"`, the Claude config
(`conductor.claude.toml`), and `caller_model="claude-opus-4-8"`. All tests are
pure policy evaluations (no live services, no network); they build a
`NormalizedOperation` with an in-line `CONDUCTOR_TASK` envelope and call
`evaluate_policy` directly, exactly as the Codex policy tests do.

- **T1 `test_claude_orchestrator_may_choose_a_cheaper_model_for_any_class`** —
  opus caller, `model="claude-haiku-4-5"`, envelope `task_class="implementation"`
  (owned by sonnet). Expect `spec.allowed is True`, `selected_model ==
  "claude-haiku-4-5"`. *This is the behavior flip from the old `MODEL_MISMATCH`.*
- **T2 `test_claude_omitted_model_inherits_the_caller_model`** — opus caller, no
  `model` in payload. Expect allowed, `selected_model == "claude-opus-4-8"`.
- **T3 `test_claude_reservation_records_null_effort`** — run any allowed Claude
  spawn through `Store.decide_and_reserve` (or `store.reserve`, per
  `tests/test_store.py::request`) and assert
  `store.reservation(...).reasoning_effort is None`.
- **T4 `test_claude_never_enforces_effort`** — parametrize over an operation that
  includes a stray `reasoning_effort` in `operation.payload`; assert the decision
  is `allowed` and `spec.rule` is never one of `MISSING_EFFORT_SELECTION`,
  `EFFORT_CEILING`, `UNKNOWN_CALLER_EFFORT`, `UNKNOWN_TARGET_EFFORT`,
  `UNSUPPORTED_MODEL_EFFORT`.
- **T5 `test_claude_capability_ceiling_blocks_a_stronger_worker`** — construct a
  Claude-shaped config where the `standard` (sonnet) tier has `may_spawn = true`;
  sonnet caller requests `model="claude-opus-4-8"`. Expect denied,
  `spec.rule == "MODEL_CAPABILITY_CEILING"`.
- **T6 `test_claude_high_risk_stays_on_frontier`** — opus caller, envelope
  `task_class="high_risk"`, `model="claude-haiku-4-5"`. Expect denied,
  `spec.rule == "HIGH_RISK_REQUIRES_FRONTIER"`. Add the transitive property
  assertion here or as a Hypothesis test alongside
  `tests/test_policy_properties.py`: for every allowed Claude decision, the target
  tier's `generation_rank ≤` caller's and `effective_capability_rank ≤` caller's,
  and `preview.reasoning_effort is None`.
- **T7 (in `tests/test_capabilities.py`)
  `test_claude_contract_declares_no_effort_selector_so_policy_skips_effort`** —
  load `claude-current` and assert `reasoning_effort_selector_path is None`; load
  `codex-current` and assert it is `"reasoning_effort"`. This guards the
  `effort_enforced = run.provider is Provider.CODEX` proxy against silent drift.

Existing tests to check (should stay green, no logic change):

- `tests/test_provider_claude.py::test_claude_hook_routes_alias_and_reserves_by_tool_use_id`
  — uses `model="sonnet"` for an `implementation` task; opus caller. Still allowed
  with `selected_model == "claude-sonnet-5"` under model-led routing. If it fails,
  the ranks in Step 1 are wrong.
- `tests/test_config.py` — extend to assert Claude tier ranks (Step 3).

Boundary policy: all tests mock nothing external — they exercise real
`evaluate_policy`, real config loading, and a real temp-file `Store`. No live
provider calls (consistent with the repo's offline test posture).

## Acceptance Criteria

- [ ] `conductor.claude.toml` has `generation_rank = 48` on all three tiers and
      `capability_rank` = 100 / 25 / 6 for opus / sonnet / haiku.
- [ ] `policy.py` routes any `OperatingMode.ROUTING` provider through the
      model-led ceiling branch; the four effort checks are gated by
      `effort_enforced = run.provider is Provider.CODEX`.
- [ ] A Claude `Task` naming a model at or below the caller's ceiling is allowed;
      naming a stronger model is denied `MODEL_CAPABILITY_CEILING`; naming a
      newer-generation model is denied `MODEL_GENERATION_CEILING`.
- [ ] A Claude `Task` with no `model` inherits the caller's model and is allowed.
- [ ] Every Claude reservation persists `reasoning_effort = NULL`; no Claude
      decision ever emits an effort-related rule.
- [ ] `claude-current.json` and its golden fixtures are unchanged (no
      `reasoning_effort_selector_path`); `capabilities.py` is unchanged.
- [ ] New tests T1–T7 pass; `test_provider_claude.py` and Codex policy/capability
      tests remain green.
- [ ] `make check` passes (lint, types, unit). `make dist-test` and `make e2e`
      pass. `conductor doctor --strict` reports `policy_canary` `ok` for the
      Claude provider. Run the monorepo release-contract test if present.
- [ ] `CHANGELOG.md`, `README.md`, `docs/probe-report.md`, the handoff doc, and
      the design doc are updated to state that Claude model-led routing shipped and
      effort remains deferred by design.
