# Model and Effort Ceilings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Codex orchestrators choose worker models and reasoning effort while Conductor rejects every model-generation, capability, or effort escalation above the caller. Leave Claude production behavior unchanged and provide a separate handoff.

**Architecture:** The Codex adapter normalizes requested and active effort; tier configuration supplies explicit generation/capability ranks and a model effort ceiling. Policy validates the orchestrator's unchanged choice rather than choosing a target. Additive persistence records accepted effort without changing Claude's current decision path.

**Tech Stack:** Python 3.11+, Pydantic v2, SQLite migrations, pytest/Hypothesis, Ruff, Pyright.

---

### Task 1: Model authority and effort schema

**Files:**
- Modify: `src/conductor/schemas.py`
- Modify: `tests/test_schemas.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing schema tests**

Add tests that construct tiers with `generation_rank`, `capability_rank`, and the
six canonical effort values; assert ranks are positive, model authority is
unique, task-class recommendations still form a partition while empty
recommendation lists are permitted, and relative-cost ties are permitted but
increases are rejected.

```python
@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max", "ultra"])
def test_tier_accepts_canonical_effort_levels(effort: str) -> None:
    payload = valid_config()["tiers"][0]
    payload.update(reasoning_effort=effort, generation_rank=56, capability_rank=100)
    assert TierConfig.model_validate(payload).reasoning_effort == effort


def test_model_authority_ranks_are_positive() -> None:
    payload = valid_config()["tiers"][0]
    payload["generation_rank"] = 0
    with pytest.raises(ValidationError):
        TierConfig.model_validate(payload)


def test_equal_cost_models_are_valid_but_cost_may_not_increase() -> None:
    payload = valid_config()
    payload["tiers"][1]["relative_cost_weight"] = payload["tiers"][0]["relative_cost_weight"]
    assert ConductorConfig.model_validate(payload)
    payload["tiers"][1]["relative_cost_weight"] += 1
    with pytest.raises(ValidationError, match="non-increasing"):
        ConductorConfig.model_validate(payload)
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_config.py -q`

Expected: FAIL because `TierConfig` lacks authority ranks, rejects higher effort,
and requires non-empty task-class lists.

- [ ] **Step 3: Implement the schema**

Add canonical effort ordering and fields without parsing model slugs:

```python
REASONING_EFFORTS = ("low", "medium", "high", "xhigh", "max", "ultra")
ReasoningEffort = Literal["low", "medium", "high", "xhigh", "max", "ultra"]


class TierConfig(StrictModel):
    name: Identifier
    model: BoundedString
    generation_rank: PositiveInt
    capability_rank: PositiveInt
    reasoning_effort: ReasoningEffort
    enabled: Literal["always", "auto", "never"]
    pricing: Pricing
    relative_cost_weight: PositiveInt
    est_task_usd: FiniteNonNegativeFloat
    max_concurrent: Annotated[StrictInt, Field(ge=1, le=10000)]
    may_spawn: StrictBool
    task_classes: Annotated[tuple[BoundedString, ...], Field(max_length=64)]

    def supports_effort(self, effort: str) -> bool:
        try:
            return REASONING_EFFORTS.index(effort) <= REASONING_EFFORTS.index(self.reasoning_effort)
        except ValueError:
            return False
```

Change the cost-order validator from strictly decreasing to non-increasing and
keep exact task-class partition validation over non-empty owners.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_schemas.py tests/test_config.py -q`

Expected: PASS.

### Task 2: Capability contracts and provider normalization

**Files:**
- Modify: `src/conductor/schemas.py`
- Modify: `src/conductor/tool_adapter.py`
- Modify: `src/conductor/assets/contracts/codex-current.json`
- Modify: `tests/fixtures/contracts/codex-current.json`
- Modify: `tests/fixtures/contracts/codex-spawn.json`
- Modify: `tests/test_capabilities.py`
- Modify: `tests/test_tool_adapter.py`

- [ ] **Step 1: Write failing contract and normalization tests**

Verify the current Codex contract exposes both selectors and Codex spellings
normalize:

```python
def test_current_codex_contract_routes_model_and_effort() -> None:
    contract = load_contract("codex-current")
    result = negotiate(contract, fixture("codex-spawn"))
    assert result.mode is OperatingMode.ROUTING
    assert result.child_model_selectable
    assert contract.model_selector_path == "model"


def test_tool_request_extracts_reasoning_effort() -> None:
    request = normalize_tool_request({
        "tool_name": "spawn_agent",
        "tool_input": {"task_name": "x", "message": "bounded", "model": "gpt-5.6-terra", "reasoning_effort": "medium"},
    })
    assert request.requested_model == "gpt-5.6-terra"
    assert request.requested_effort == "medium"
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_capabilities.py tests/test_tool_adapter.py -q`

Expected: FAIL because effort selectors and normalized effort do not exist.

- [ ] **Step 3: Add effort-selector capability negotiation**

Extend `ToolRequest`:

```python
@dataclass(frozen=True)
class ToolRequest:
    kind: str
    tool_name: str
    requested_model: str | None
    requested_effort: str | None
    task_name: str | None
    envelope: TaskEnvelopeV2 | None
```

Normalize Codex `reasoning_effort` and copy the normalized value into
`NormalizedOperation.payload` in `hooks/pre_tool_use.py`. Do not change Claude
normalization.

- [ ] **Step 4: Update golden contracts and fixtures**

Codex spawn properties must include:

```json
"model": {"type":"string","enum":["gpt-5.6-sol","gpt-5.6-terra","gpt-5.6-luna","gpt-5.5","gpt-5.4","gpt-5.4-mini","gpt-5.3-codex-spark"]},
"reasoning_effort": {"type":"string","enum":["low","medium","high","xhigh","max","ultra"]}
```

Set `model_selector_path` to `model`. Do not modify the Claude contract or
fixtures without a verified live effort selector.

- [ ] **Step 5: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_capabilities.py tests/test_tool_adapter.py -q`

Expected: PASS.

### Task 3: Persist accepted effort for transitive ceilings

**Files:**
- Modify: `src/conductor/migrations.py`
- Modify: `src/conductor/store.py`
- Modify: `src/conductor/schemas.py`
- Modify: `tests/test_store.py`
- Modify: `tests/test_schemas.py`

- [ ] **Step 1: Write failing migration and round-trip tests**

```python
def test_schema_v4_records_reservation_effort(tmp_path: Path) -> None:
    store = Store(tmp_path / "state.db")
    assert store.schema_version() == SCHEMA_VERSION == 4
    decision = store.reserve(request("run", "task", reasoning_effort="medium"), concurrency_cap=2, budget_cap=10.0)
    assert decision.allowed
    assert store.reservation("task", run_id="run").reasoning_effort == "medium"
```

Add a v3 database migration test showing historical rows load with `None`.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_schemas.py -q`

Expected: FAIL because schema version 4 and reservation effort do not exist.

- [ ] **Step 3: Add the additive migration and storage field**

```python
SCHEMA_VERSION = 4
MIGRATIONS[4] = ("ALTER TABLE reservations ADD COLUMN reasoning_effort TEXT",)
```

Add `reasoning_effort: ReasoningEffort | None` to `Reservation`, an optional
canonical effort to `ReservationRequest`, include it in reservation inserts,
and load nullable historical values in `_reservation_from_row`. Codex supplies
it; unchanged Claude reservations remain nullable.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_store.py tests/test_schemas.py -q`

Expected: PASS.

### Task 4: Model-led policy enforcement

**Files:**
- Modify: `src/conductor/policy.py`
- Modify: `src/conductor/hooks/pre_tool_use.py`
- Modify: `tests/test_policy_v2.py`
- Modify: `tests/test_policy_properties.py`
- Modify: `tests/test_pre_tool_use.py`

- [ ] **Step 1: Write failing policy examples**

Cover missing selections, GPT-5.5 to any GPT-5.6 denial, capability escalation,
effort escalation, unsupported model effort, unchanged valid requests, equal
cost strict-cheaper behavior, and high-risk no-downgrade behavior.

```python
def test_newer_generation_is_denied_even_when_child_is_cheaper(tmp_path: Path) -> None:
    result = _evaluate(
        tmp_path,
        _operation(model="gpt-5.6-terra", effort="medium"),
        caller_model="gpt-5.5",
        caller_effort="high",
    )
    assert not result.spec.allowed
    assert result.spec.rule == "MODEL_GENERATION_CEILING"


def test_worker_effort_may_not_exceed_caller(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, _operation(effort="high"), caller_effort="medium")
    assert not result.spec.allowed
    assert result.spec.rule == "EFFORT_CEILING"
    assert "medium" in result.spec.message
```

Add a Hypothesis property: every allowed decision has target generation and
capability no greater than the caller and requested effort no greater than both
caller effort and target model effort.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_policy_v2.py tests/test_policy_properties.py tests/test_pre_tool_use.py -q`

Expected: FAIL because policy still chooses a task-class target and ignores effort.

- [ ] **Step 3: Implement minimal validation-only policy**

Change `evaluate_policy` to accept `caller_effort: str`. For Codex, resolve the
target only from the orchestrator's requested model. Require exact model/effort
selections, verify the target is enabled, then compare explicit generation,
capability, and effort ranks. Preserve forced-frontier behavior for high-risk
work. Compare `relative_cost_weight` for strict-cheaper enforcement; only the
bounded root same-model exception may bypass it. Keep Claude's current
task-class policy path unchanged.

Use messages of the form:

```python
return _result(
    False,
    "EFFORT_CEILING",
    f"requested effort {requested_effort} exceeds caller ceiling {caller_effort}; choose an effort at or below {caller_effort}",
    tier=target,
    selected_model=target.model,
    estimate=estimate,
)
```

Pass the accepted effort into `ReservationRequest`; never modify operation
payload or select a fallback.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_policy_v2.py tests/test_policy_properties.py tests/test_pre_tool_use.py -q`

Expected: PASS.

### Task 5: Resolve caller effort for Codex

**Files:**
- Modify: `src/conductor/identity.py`
- Modify: `src/conductor/providers/codex.py`
- Modify: `tests/test_identity.py`
- Modify: `tests/test_hook_commands.py`

- [ ] **Step 1: Write failing caller-effort tests**

```python
def test_codex_caller_reads_active_effort_from_hook() -> None:
    caller = PROVIDER.resolve_caller({"model": "gpt-5.6-sol", "reasoning_effort": "high", "session_id": "run"}, config)
    assert caller.effort == "high"


```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_identity.py tests/test_hook_commands.py -q`

Expected: FAIL because `Caller` has no effort.

- [ ] **Step 3: Implement authoritative effort resolution**

Add `effort: str` to `Caller`. Codex reads provider-owned
`reasoning_effort`/`model_reasoning_effort`. Unknown effort is an empty string
and fails closed in Codex enforced policy. Leave Claude caller resolution
unchanged.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_identity.py tests/test_hook_commands.py -q`

Expected: PASS.

### Task 6: GPT-5.6 packaged ladder, docs, and installer assets

**Files:**
- Modify: `src/conductor/assets/config/conductor.toml`
- Modify: `tests/helpers.py`
- Modify: `tests/fixtures/v1-conductor.toml`
- Modify: `README.md`
- Modify: `docs/probe-report.md`
- Modify: `CHANGELOG.md`
- Modify: `tests/test_public_docs.py`
- Modify: `tests/test_install.py`
- Create: `docs/superpowers/specs/2026-07-22-claude-effort-routing-handoff.md`

- [ ] **Step 1: Write failing packaged-default and documentation tests**

Assert the Codex config contains Sol, Terra, Luna, and GPT-5.5 with explicit
authority; Sol and GPT-5.5 use equal relative-cost weights; default class
recommendations remain an exact partition; policy docs say the orchestrator
chooses and Conductor denies rather than rewrites.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_public_docs.py tests/test_install.py -q`

Expected: FAIL on old defaults and admission-only documentation.

- [ ] **Step 3: Update packaged defaults and public documentation**

Use this Codex authority ordering:

```text
gpt-5.6-sol: generation 56, capability 100, max effort ultra, weight 100
gpt-5.5: generation 55, capability 90, max effort high, weight 100
gpt-5.6-terra: generation 56, capability 80, max effort high, weight 50
gpt-5.4: generation 54, capability 70, max effort high, weight 50
gpt-5.6-luna: generation 56, capability 50, max effort medium, weight 20
gpt-5.4-mini: generation 54, capability 40, max effort medium, weight 15
gpt-5.3-codex-spark: generation 53, capability 20, max effort low, weight 2
```

Keep dollar prices zero. Explain that ChatGPT credits and API dollars are
different units, and document Sol's equal credit rate to GPT-5.5 without using
that rate in dollar accounting. Add a Claude handoff summarizing the unverified
per-invocation effort selector and the constraints its implementation must
preserve.

- [ ] **Step 4: Verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_config.py tests/test_public_docs.py tests/test_install.py -q`

Expected: PASS.

### Task 7: Full verification

**Files:**
- Modify only files required by failures caused by this feature.

- [ ] **Step 1: Run format, lint, typecheck, and unit tests**

Run: `make check PYTHON=.venv/bin/python`

Expected: 0 failures and coverage at least 90%.

- [ ] **Step 2: Run distribution tests**

Run: `make dist-test PYTHON=.venv/bin/python`

Expected: wheel/sdist and installed-package tests pass.

- [ ] **Step 3: Run end-to-end smoke tests**

Run: `make e2e PYTHON=.venv/bin/python`

Expected: Codex and Claude hook flows pass without live model work.

- [ ] **Step 4: Run the monorepo release contract**

Run: `.venv/bin/python -m pytest ../tests/test_release_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Review the final diff**

Run: `git diff --check && git status --short && git diff --stat origin/main...HEAD`

Expected: no whitespace errors, only planned files changed, and the ignored
worktree environment is not staged.
