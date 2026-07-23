# Codex All-Worker Models and Authority Ceilings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make all seven configured Codex models explicitly worker-selectable while preventing every worker and descendant from exceeding its caller's model generation, model capability, or effective reasoning effort.

**Architecture:** The Codex fork owns the native worker picker, provider-supported effort validation, safe effort inheritance, and lifecycle-visible child configuration. Conductor owns the generation/capability/effort policy lattice, selector-aware tier enablement, hook-time filling of omitted effort, reservations, and diagnostics. Existing capacity, concurrency, depth, budget, hook-correlation, and UI-display behavior remain independent.

**Tech Stack:** Rust/Cargo/Nextest (`codex-core`), Python 3.13/Pydantic/pytest (`codex-conductor`), Codex native hooks, SQLite WAL accounting, TOML/JSON capability contracts.

---

## File Map

### Codex fork: `/home/neil/VSproj/codex-native-hook-fix`

- Modify `codex-rs/core/src/tools/handlers/multi_agents_common.rs`: broaden v2 worker compatibility; rank canonical efforts; prevent effort upgrades; resolve omitted effort safely.
- Create `codex-rs/core/src/tools/handlers/multi_agents_common_tests.rs`: focused worker compatibility and effort-ceiling tests.
- Modify `codex-rs/core/src/tools/handlers/multi_agents_spec.rs`: keep the worker-model description bounded while including all seven configured models.
- Modify `codex-rs/core/src/tools/handlers/multi_agents_spec_tests.rs`: prove v1-marked and unmarked cached models are exposed under v2.
- Modify `codex-rs/core/tests/suite/subagent_notifications.rs`: prove effective child model/effort and descendant configuration through the public spawn path.
- Preserve all existing uncommitted native-hook changes in `registry.rs`, `multi_agents_v2/spawn.rs`, `multi_agents_tests.rs`, and `core/tests/suite/hooks.rs`.

### Agent Tooling: `/home/neil/VSproj/agent-tooling`

- Modify `codex-conductor/src/conductor/assets/contracts/codex-current.json`: declare all seven native model choices.
- Modify `codex-conductor/tests/fixtures/contracts/codex-current.json`: keep the golden contract identical.
- Modify `codex-conductor/tests/test_capabilities.py`: assert the complete exact model enum.
- Modify `codex-conductor/src/conductor/capabilities.py`: extract bounded selectable-model values from the verified spawn contract.
- Modify `codex-conductor/src/conductor/config.py`: intersect auto-tier cache presence with verified selector reachability.
- Modify `codex-conductor/src/conductor/status.py`, `doctor.py`, and `hooks/pre_tool_use.py`: pass verified selector models into tier enablement.
- Modify `codex-conductor/tests/test_config.py`, `test_status_report.py`, and `test_doctor.py`: cover cached-but-unselectable tiers.
- Modify `codex-conductor/src/conductor/policy.py`: resolve omitted effort safely, permit equal-authority workers, and remove the special same-tier count gate without changing ordinary limits.
- Modify `codex-conductor/src/conductor/providers/codex.py`: emit an `updatedInput` only when filling omitted effort.
- Modify `codex-conductor/tests/test_policy_v2.py`, `test_pre_tool_use.py`, and `test_provider_codex.py`: cover model/effort ceilings and exact hook rewrites.
- Modify `codex-conductor/README.md`, `CHANGELOG.md`, and installed policy text: document the non-increasing authority lattice and all selectable workers.

## Task 1: Expose Every Cached Model to the Native v2 Worker Picker

**Files:**
- Modify: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/src/tools/handlers/multi_agents_spec_tests.rs`
- Modify: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/src/tools/handlers/multi_agents_spec.rs`
- Modify: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/src/tools/handlers/multi_agents_common.rs`

- [ ] **Step 1: Write the failing picker compatibility test**

Change the current v2 test so its v1-marked model and a model with no multi-agent marker must both appear:

```rust
let mut v1_worker = model_preset("v1-worker", /*show_in_picker*/ true);
v1_worker.multi_agent_version = Some(MultiAgentVersion::V1);
let mut unmarked_worker = model_preset("unmarked-worker", /*show_in_picker*/ true);
unmarked_worker.multi_agent_version = None;

assert!(description.contains("`v1-worker-model`"));
assert!(description.contains("`unmarked-worker-model`"));
```

Extend the cap test to seven configured entries plus an eighth sentinel and assert the first seven are shown.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd /home/neil/VSproj/codex-native-hook-fix/codex-rs
just test -p codex-core tools::handlers::multi_agents_spec::tests::spawn_agent_tool_v2_requires_task_name_and_lists_visible_models -- --exact
```

Expected: FAIL because v2 currently filters out v1 and unmarked models.

- [ ] **Step 3: Implement bounded all-worker exposure**

In `multi_agents_common.rs`, make a locally forced v2 runtime accept any cached worker model:

```rust
pub(crate) const MAX_SPAWN_AGENT_MODEL_OVERRIDES: usize = 16;

pub(crate) fn model_supports_multi_agent_backend(
    model: &ModelPreset,
    multi_agent_version: MultiAgentVersion,
) -> bool {
    multi_agent_version == MultiAgentVersion::V2
        || model.multi_agent_version == Some(multi_agent_version)
}
```

Keep `show_in_picker` filtering and the hard bound in `spawn_agent_models_description`. Do not expose hidden models and do not remove the bound.

- [ ] **Step 4: Run the focused spec tests and verify GREEN**

Run:

```bash
just test -p codex-core tools::handlers::multi_agents_spec::tests
```

Expected: all multi-agent spec tests PASS.

- [ ] **Step 5: Commit only the picker files**

```bash
git add codex-rs/core/src/tools/handlers/multi_agents_common.rs \
  codex-rs/core/src/tools/handlers/multi_agents_spec.rs \
  codex-rs/core/src/tools/handlers/multi_agents_spec_tests.rs
git commit -m "feat: expose all cached Codex worker models"
```

Do not stage the pre-existing native-hook files.

## Task 2: Enforce Native Effort Non-Escalation and Safe Omitted Effort

**Files:**
- Create: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/src/tools/handlers/multi_agents_common_tests.rs`
- Modify: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/src/tools/handlers/multi_agents_common.rs`
- Modify: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/core/tests/suite/subagent_notifications.rs`

- [ ] **Step 1: Add failing unit tests for canonical effort ordering**

Add a sibling test module and register it from `multi_agents_common.rs`:

```rust
#[cfg(test)]
#[path = "multi_agents_common_tests.rs"]
mod tests;
```

Test these exact cases through a private helper API:

```rust
assert_eq!(
    highest_supported_effort_at_or_below(
        &supported(&[ReasoningEffort::Low, ReasoningEffort::Medium]),
        &ReasoningEffort::High,
    ),
    Some(ReasoningEffort::Medium),
);
assert!(effort_at_or_below(&ReasoningEffort::Medium, &ReasoningEffort::Medium));
assert!(!effort_at_or_below(&ReasoningEffort::High, &ReasoningEffort::Medium));
assert!(!effort_at_or_below(
    &ReasoningEffort::Custom("future".into()),
    &ReasoningEffort::Ultra,
));
```

- [ ] **Step 2: Run the unit tests and verify RED**

Run:

```bash
just test -p codex-core tools::handlers::multi_agents_common::tests
```

Expected: compilation FAIL because the effort helpers do not exist.

- [ ] **Step 3: Implement canonical effort ranking**

Add a private rank function covering every known enum variant:

```rust
fn canonical_effort_rank(effort: &ReasoningEffort) -> Option<u8> {
    match effort {
        ReasoningEffort::None => Some(0),
        ReasoningEffort::Minimal => Some(1),
        ReasoningEffort::Low => Some(2),
        ReasoningEffort::Medium => Some(3),
        ReasoningEffort::High => Some(4),
        ReasoningEffort::XHigh => Some(5),
        ReasoningEffort::Max => Some(6),
        ReasoningEffort::Ultra => Some(7),
        ReasoningEffort::Custom(_) => None,
    }
}
```

Implement `effort_at_or_below` and select the highest provider-supported canonical effort no higher than the caller.

- [ ] **Step 4: Write the failing public-path effort tests**

In `subagent_notifications.rs`, add cases proving:

```rust
// Equal effort remains equal.
parent = gpt_5_5_at(ReasoningEffort::Medium);
spawn(model = "gpt-5.5", reasoning_effort = "medium");
assert_eq!(child.reasoning_effort, Some(ReasoningEffort::Medium));

// Explicit upgrade is rejected.
spawn(model = "gpt-5.5", reasoning_effort = "high");
assert_no_child_created();

// Omitted effort selects the highest target-supported value <= parent.
spawn(model = "low-only-worker", reasoning_effort = omitted);
assert_eq!(child.reasoning_effort, Some(ReasoningEffort::Low));
```

Use the existing mock model manager and child config snapshot helpers rather than introducing test-only production APIs.

- [ ] **Step 5: Run the public-path tests and verify RED**

Run:

```bash
just test -p codex-core spawn_agent_requested_model -- --nocapture
```

Expected: the explicit-upgrade or omitted-effort assertion FAILS because current code uses the target default without a caller ceiling.

- [ ] **Step 6: Apply the caller ceiling in native spawn configuration**

In `apply_requested_spawn_agent_model_overrides`:

1. Resolve the caller's effective effort from `turn.reasoning_effort`, then the parent model default.
2. Reject an explicit effort whose canonical rank exceeds the caller.
3. For explicit model plus omitted effort, select the highest target-supported canonical effort at or below the caller.
4. Preserve exact full-history inheritance when both overrides are absent.
5. Fail closed for unknown custom effort ordering.

Use errors that name the requested effort, caller effort, target model, and supported target efforts.

- [ ] **Step 7: Run focused native tests and verify GREEN**

Run:

```bash
just test -p codex-core tools::handlers::multi_agents_common::tests
just test -p codex-core spawn_agent_requested_model -- --nocapture
```

Expected: all focused tests PASS.

- [ ] **Step 8: Commit the native effort files**

```bash
git add codex-rs/core/src/tools/handlers/multi_agents_common.rs \
  codex-rs/core/src/tools/handlers/multi_agents_common_tests.rs \
  codex-rs/core/tests/suite/subagent_notifications.rs
git commit -m "feat: prevent subagent effort escalation"
```

## Task 3: Make Conductor Selector-Aware and Declare All Seven Models

**Files:**
- Modify: `codex-conductor/src/conductor/assets/contracts/codex-current.json`
- Modify: `codex-conductor/tests/fixtures/contracts/codex-current.json`
- Modify: `codex-conductor/tests/test_capabilities.py`
- Modify: `codex-conductor/src/conductor/capabilities.py`
- Modify: `codex-conductor/src/conductor/config.py`
- Modify: `codex-conductor/tests/test_config.py`
- Modify: `codex-conductor/src/conductor/status.py`
- Modify: `codex-conductor/src/conductor/doctor.py`
- Modify: `codex-conductor/src/conductor/hooks/pre_tool_use.py`

- [ ] **Step 1: Write failing contract and selectability tests**

Assert this exact selector order:

```python
CODEX_WORKER_MODELS = [
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gpt-5.3-codex-spark",
]
assert properties["model"]["enum"] == CODEX_WORKER_MODELS
```

Add an `enabled_tiers` test with a cache containing three models but a selector set containing
only two:

```python
assert enabled_tiers(config, models, {"gpt-5.6-sol", "gpt-5.6-terra"}) == [0, 2]
```

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_capabilities.py \
  codex-conductor/tests/test_config.py -q
```

Expected: FAIL on the two-model enum and unsupported `enabled_tiers` selector argument.

- [ ] **Step 3: Update both contract copies**

Replace the model enum in both JSON files with `CODEX_WORKER_MODELS` in the exact order above.
Do not change the effort enum or correlation fields.

- [ ] **Step 4: Add a bounded contract selector helper**

In `capabilities.py`, add:

```python
def selectable_models(contract: CapabilityContract) -> frozenset[str]:
    spawn = next(
        (tool for tool in contract.tools if tool.canonical_name is OperationName.SPAWN),
        None,
    )
    if spawn is None or contract.model_selector_path is None:
        return frozenset()
    values = spawn.input_schema.get("properties", {}).get(
        contract.model_selector_path, {}
    ).get("enum", [])
    return frozenset(value for value in values if isinstance(value, str))
```

Use the actual canonical-name enum type already used by `ToolContract`; do not compare unrelated enum classes.

- [ ] **Step 5: Intersect cache presence with selector reachability**

Change the signature to:

```python
def enabled_tiers(
    ladder: Ladder,
    models_cache_path: Path,
    selector_models: Collection[str] | None = None,
) -> list[int]:
```

`always` tiers remain configured, but in routing-mode callers pass the verified selector set so
an unreachable `always` tier cannot be used for a native override. Update status, doctor, and
pre-tool-use call sites to load the active run/provider contract and pass `selectable_models`.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_capabilities.py \
  codex-conductor/tests/test_config.py \
  codex-conductor/tests/test_status_report.py \
  codex-conductor/tests/test_doctor.py -q
```

Expected: all focused tests PASS.

- [ ] **Step 7: Commit selector-aware Conductor**

```bash
git add codex-conductor/src/conductor/assets/contracts/codex-current.json \
  codex-conductor/tests/fixtures/contracts/codex-current.json \
  codex-conductor/tests/test_capabilities.py \
  codex-conductor/src/conductor/capabilities.py \
  codex-conductor/src/conductor/config.py \
  codex-conductor/tests/test_config.py \
  codex-conductor/src/conductor/status.py \
  codex-conductor/src/conductor/doctor.py \
  codex-conductor/src/conductor/hooks/pre_tool_use.py
git commit -m "feat: recognize every selectable Codex worker"
```

## Task 4: Enforce the Non-Increasing Authority Lattice and Fill Omitted Effort

**Files:**
- Modify: `codex-conductor/tests/test_policy_v2.py`
- Modify: `codex-conductor/tests/test_pre_tool_use.py`
- Modify: `codex-conductor/src/conductor/policy.py`
- Modify: `codex-conductor/src/conductor/providers/codex.py`
- Test: `codex-conductor/tests/test_provider_codex.py`

- [ ] **Step 1: Write the failing policy matrix**

Add parametrized cases:

```python
@pytest.mark.parametrize(
    ("caller_model", "caller_effort", "worker_model", "worker_effort", "allowed", "rule"),
    [
        ("gpt-5.5", "medium", "gpt-5.5", "medium", True, "ALLOW"),
        ("gpt-5.5", "medium", "gpt-5.5", "high", False, "EFFORT_CEILING"),
        ("gpt-5.5", "medium", "gpt-5.6-luna", "low", False, "MODEL_GENERATION_CEILING"),
        ("gpt-5.5", "medium", "gpt-5.4", "medium", True, "ALLOW"),
        ("gpt-5.5", "medium", "gpt-5.4", "high", False, "EFFORT_CEILING"),
        ("gpt-5.6-luna", "medium", "gpt-5.5", "low", False, "MODEL_CAPABILITY_CEILING"),
        ("gpt-5.6-luna", "medium", "gpt-5.4-mini", "medium", True, "ALLOW"),
    ],
)
```

Add a snapshot with five active same-model workers below the normal tier concurrency cap and
assert no `SAME_TIER_LIMIT` decision occurs.

- [ ] **Step 2: Run the policy tests and verify RED**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_policy_v2.py -q
```

Expected: equal-model cases beyond the special root count fail with `SAME_TIER_LIMIT`, and omitted effort fails with `MISSING_EFFORT_SELECTION`.

- [ ] **Step 3: Resolve omitted effort deterministically**

After resolving the target tier, use:

```python
def _bounded_worker_effort(caller_effort: str, target: TierConfig) -> str | None:
    if caller_effort not in REASONING_EFFORTS:
        return None
    ceiling = min(
        REASONING_EFFORTS.index(caller_effort),
        REASONING_EFFORTS.index(target.reasoning_effort),
    )
    return REASONING_EFFORTS[ceiling]
```

Only fill an omitted effort; never modify an explicit value. Store the resolved effort in the
reservation.

- [ ] **Step 4: Permit equality without a special count gate**

For model-led routing:

```python
if config.policy.require_strictly_cheaper and not strictly_cheaper and not exact_same_model:
    return _result(False, "STRICTLY_CHEAPER_REQUIRED", ...)
```

For class-led fallback, allow `same_tier` and retain the stronger-child, capacity, concurrency,
depth, budget, and high-risk checks. Leave the legacy config field parseable for installation
compatibility, but stop consulting it during admission.

- [ ] **Step 5: Write the failing hook rewrite test**

Given a Codex spawn with model `gpt-5.4-mini` and no `reasoning_effort`, assert:

```python
response["hookSpecificOutput"]["permissionDecision"] == "allow"
response["hookSpecificOutput"]["updatedInput"] == {
    **original_tool_input,
    "reasoning_effort": "medium",
}
```

Also assert explicit `"reasoning_effort": "low"` produces no `updatedInput`.

- [ ] **Step 6: Run hook tests and verify RED**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_pre_tool_use.py \
  codex-conductor/tests/test_provider_codex.py -q
```

Expected: omitted effort currently blocks or the allow response lacks `updatedInput`.

- [ ] **Step 7: Emit an exact Codex updated input**

Add a Codex-provider method that copies the original bounded tool input and adds only the
resolved effort:

```python
def decorate_updated_input(
    self,
    response: dict,
    tool_input: dict,
    reasoning_effort: str,
) -> dict:
    output = deepcopy(response)
    output["hookSpecificOutput"]["updatedInput"] = {
        **tool_input,
        "reasoning_effort": reasoning_effort,
    }
    return output
```

Call it only for an allowed Codex spawn where the original effort was omitted and the committed
reservation has a resolved effort. Preserve the encrypted message value byte-for-byte.

- [ ] **Step 8: Run the policy and hook tests and verify GREEN**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_policy_v2.py \
  codex-conductor/tests/test_pre_tool_use.py \
  codex-conductor/tests/test_provider_codex.py -q
```

Expected: all tests PASS.

- [ ] **Step 9: Commit the authority policy**

```bash
git add codex-conductor/src/conductor/policy.py \
  codex-conductor/src/conductor/providers/codex.py \
  codex-conductor/tests/test_policy_v2.py \
  codex-conductor/tests/test_pre_tool_use.py \
  codex-conductor/tests/test_provider_codex.py
git commit -m "feat: enforce worker model and effort ceilings"
```

## Task 5: Diagnostics, Documentation, and Full Verification

**Files:**
- Modify: `codex-conductor/README.md`
- Modify: `codex-conductor/CHANGELOG.md`
- Modify: `codex-conductor/tests/test_public_docs.py`
- Verify: both repositories

- [ ] **Step 1: Add failing public-document assertions**

Require the README to name all seven workers and state:

```text
A worker may equal, but never exceed, its caller's model generation,
capability, or effective reasoning effort.
```

Require documentation to say ordinary concurrency/depth/budget limits still apply.

- [ ] **Step 2: Run the docs tests and verify RED**

Run:

```bash
codex-conductor/.venv/bin/python -m pytest \
  codex-conductor/tests/test_public_docs.py -q
```

Expected: FAIL because the new authority wording is absent.

- [ ] **Step 3: Update README and changelog**

Document:

- the seven explicit worker models;
- equal authority is allowed;
- each authority dimension is independently non-increasing;
- omitted effort is safely bounded;
- descendant ceilings use effective child authority;
- capacity, tier concurrency, depth, and budget remain unchanged.

- [ ] **Step 4: Run all Conductor verification**

Run:

```bash
cd /home/neil/VSproj/agent-tooling/codex-conductor
make check PYTHON=.venv/bin/python
make dist-test PYTHON=.venv/bin/python
make e2e PYTHON=.venv/bin/python
cd ..
codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q
```

Expected: every command exits 0; coverage remains at or above the configured threshold.

- [ ] **Step 5: Format and verify the Codex fork**

Run from `/home/neil/VSproj/codex-native-hook-fix/codex-rs`:

```bash
just test -p codex-core tools::handlers::multi_agents_common::tests
just test -p codex-core tools::handlers::multi_agents_spec::tests
just test -p codex-core spawn_agent_requested_model -- --nocapture
just test -p codex-core
just fix -p codex-core
just fmt
```

Expected: all tests pass; fix and fmt exit 0. Per repository instructions, do not rerun tests
after `just fix` and `just fmt`.

- [ ] **Step 6: Commit documentation**

```bash
git add codex-conductor/README.md \
  codex-conductor/CHANGELOG.md \
  codex-conductor/tests/test_public_docs.py
git commit -m "docs: describe Codex worker authority ceilings"
```

## Task 6: Install and Prove the Live CLI and VS Code Runtime

**Files/State:**
- Build: `/home/neil/VSproj/codex-native-hook-fix/codex-rs/target/release/codex`
- Update: installed Codex CLI native binary
- Update: installed VS Code Codex extension native binary
- Repair: `/home/neil/.codex/conductor`

- [ ] **Step 1: Record exact installation targets and hashes**

Run read-only checks:

```bash
command -v codex
readlink -f "$(command -v codex)"
find /home/neil/.vscode/extensions -path '*/bin/linux-x86_64/codex' -type f -print
sha256sum <each resolved native binary>
```

Record targets explicitly. Do not use globs for overwrite commands.

- [ ] **Step 2: Build the release Codex binary**

Run:

```bash
cd /home/neil/VSproj/codex-native-hook-fix/codex-rs
cargo build --release -p codex-cli
```

Expected: `target/release/codex` exists and `target/release/codex --version` reports 0.145.0.

- [ ] **Step 3: Install to the two resolved native-binary targets**

Use `install -m 755` with each explicit path recorded in Step 1. Do not overwrite package
directories, extension assets, user settings, or unrelated binaries.

- [ ] **Step 4: Repair Conductor transactionally**

Run:

```bash
cd /home/neil/VSproj/agent-tooling/codex-conductor
.venv/bin/conductor install --provider codex --repair
.venv/bin/conductor doctor --provider codex --strict
```

Expected: contract, routing mode, run context, policy canary, and selector reachability pass.
Pricing may remain the already-known warning.

- [ ] **Step 5: Start a fresh authoritative live run**

Restart the CLI or VS Code host so the newly installed binary owns the session. Verify the
native `spawn_agent` selector presents all seven model values and canonical efforts.

- [ ] **Step 6: Run allowed probes**

From a sufficiently authoritative root, launch one bounded probe for each model with an effort
at or below both caller and target ceilings. Each probe prints only `CHILD_OK`.

Expected: all seven launches create correlated reservations with exact non-null model and effort.

- [ ] **Step 7: Run denied ceiling probes**

Verify these are blocked before child creation:

```text
gpt-5.5/medium -> gpt-5.5/high       EFFORT_CEILING
gpt-5.5/medium -> gpt-5.6-luna/low   MODEL_GENERATION_CEILING
gpt-5.6-luna/medium -> gpt-5.5/low   MODEL_CAPABILITY_CEILING
```

Expected: no child lifecycle start and no lingering active reservation.

- [ ] **Step 8: Verify UI and ledger**

Confirm both CLI and VS Code spawn surfaces show:

```text
Spawning <effective-model> · <effective-effort> · <task>
```

Run:

```bash
conductor status --last --pretty
conductor report --last
```

Expected: successful probes are costed under exact tiers, denied probes name exact rules, and
there are no `unknown` model/effort reservations from the new run.

- [ ] **Step 9: Verify clean scoped diffs**

Run:

```bash
git -C /home/neil/VSproj/agent-tooling status --short
git -C /home/neil/VSproj/agent-tooling diff --check
git -C /home/neil/VSproj/codex-native-hook-fix status --short
git -C /home/neil/VSproj/codex-native-hook-fix diff --check
```

Expected: Agent Tooling contains only intended committed work; the Codex fork retains the
pre-existing hook changes plus the intended committed worker-selection changes, with no
whitespace errors.
