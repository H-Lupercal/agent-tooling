# codex-conductor Professional v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a truthful, atomic, publicly distributable conductor v2 that enforces only capabilities proven by the active Codex or Claude provider contract.

**Architecture:** Normalize provider payloads into strict operations and RunContext records, then make every policy decision and reservation in one SQLite `BEGIN IMMEDIATE` transaction. Separate routing, admission, observe, and unsupported modes; package every asset inside the wheel; and make installation an old-or-new atomic transaction.

**Tech Stack:** Python 3.11-3.13, Pydantic 2, PlatformDirs, SQLite, argparse, pytest, Hypothesis, Ruff, Pyright, pytest-cov, build, twine.

---

## File Map

- `src/conductor/schemas.py`: strict config, envelope, capability, event, and report contracts.
- `src/conductor/capabilities.py`: provider capability negotiation and fixtures.
- `src/conductor/operations.py`: canonical operation and new-work classification.
- `src/conductor/identity.py`: RunContext and caller/child resolution.
- `src/conductor/policy.py`: pure policy evaluation.
- `src/conductor/store.py`: SQLite decisions, reservations, leases, lifecycle, and migrations.
- `src/conductor/accounting.py`: raw usage, complete pricing, estimates, and reports.
- `src/conductor/installation.py`: transactional install, repair, upgrade, uninstall.
- `src/conductor/doctor.py`: integrity and executable canaries.
- `src/conductor/providers/`: raw provider adapters.
- `src/conductor/hooks/`: bounded hook entry points.
- `src/conductor/assets/`: packaged defaults, policies, contracts, and hook templates.

### Task 1: Public package with bundled assets

**Files:**
- Modify: `pyproject.toml`
- Create: `src/conductor/__init__.py`
- Create: `src/conductor/__main__.py`
- Move: `conductor/` to `src/conductor/`
- Move/package: `config/`, `policy/`, and hook templates under `src/conductor/assets/`
- Create: `tests/test_distribution.py`
- Modify: `.gitignore`
- Modify: `Makefile`

- [ ] **Step 1: Write a failing clean-wheel test**

```python
def test_installed_wheel_contains_operational_assets(built_wheel, clean_venv):
    clean_venv.pip_install(built_wheel)
    result = clean_venv.run("conductor", "install", "--dry-run", env=isolated_home())
    assert result.returncode == 0
    assert "FileNotFoundError" not in result.stderr
    assert "conductor.toml" in result.stdout
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_distribution.py -q`

Expected: FAIL because the current wheel omits top-level `config/` and `policy/`.

- [ ] **Step 3: Move to `src/` and package assets**

Use Hatchling with console script `conductor = conductor.cli:main`, dynamic
version from `conductor.__version__`, required Python `>=3.11`, runtime
dependencies `pydantic>=2.8,<3` and `platformdirs>=4.2,<5`, and optional dev
dependencies for pytest, pytest-cov, hypothesis, ruff, pyright, build, twine,
pip-audit, and cyclonedx-bom. Set version `2.0.0`.

Replace checkout-relative asset paths with `importlib.resources.files("conductor.assets")`.
Move sources mechanically, update Makefile check/build targets, and ignore virtual
environment, coverage, build, and distribution artifacts.

- [ ] **Step 4: Verify GREEN and preserve baseline behavior**

Run: `python3 -m pip install -e '.[dev]'`

Run: `pytest tests/test_distribution.py -q`

Run: `python3 -m unittest discover -s tests -v`

Expected: clean wheel test and all existing tests pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests/test_distribution.py .gitignore Makefile
git commit -m "build: package conductor v2 with runtime assets"
```

### Task 2: Strict schemas and configuration integrity

**Files:**
- Create: `src/conductor/schemas.py`
- Create: `src/conductor/errors.py`
- Rewrite: `src/conductor/config.py`
- Create: `tests/test_schemas.py`
- Rewrite: `tests/test_config.py`

- [ ] **Step 1: Write failing strict validation tests**

```python
@pytest.mark.parametrize("change", [
    {"schema_version": 99},
    {"budget": {"run_usd_cap": float("nan")}},
    {"budget": {"warn_at_fraction": 1.5}},
    {"policy": {"max_depth": -1}},
])
def test_invalid_config_is_rejected(change):
    with pytest.raises(ValidationError):
        ConductorConfig.model_validate(deep_merge(valid_config(), change))


def test_task_classes_form_exact_partition():
    payload = valid_config()
    payload["tiers"][1]["task_classes"].append("architecture")
    with pytest.raises(ValidationError, match="task class ownership"):
        ConductorConfig.model_validate(payload)
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_schemas.py tests/test_config.py -q`

Expected: FAIL because v1 ignores schema version and accepts incomplete numeric
and ownership constraints.

- [ ] **Step 3: Implement exact v2 models**

Create frozen `extra="forbid"` models for `ConductorConfig`, `BudgetConfig`,
`PolicyConfig`, `TierConfig`, `Pricing`, `CapabilityContract`, `RunContext`,
`TaskEnvelopeV2`, `NormalizedOperation`, `Decision`, `Reservation`,
`LifecycleEvent`, `RawUsage`, and report rows. Enforce bounded IDs/strings/lists,
strict booleans, finite nonnegative prices, `0 < warn_at_fraction <= 1`, complete
task-class partition, decreasing tier cost, unique models, and valid operating
mode requirements.

Define stable errors/exit codes for usage, validation, unsupported capability,
policy denial, degraded runtime, state, installation conflict, and internal
failure.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_schemas.py tests/test_config.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/schemas.py src/conductor/errors.py src/conductor/config.py tests/test_schemas.py tests/test_config.py
git commit -m "feat: enforce strict conductor v2 contracts"
```

### Task 3: Versioned provider capabilities and canonical operations

**Files:**
- Create: `src/conductor/capabilities.py`
- Create: `src/conductor/operations.py`
- Create: `src/conductor/assets/contracts/codex-current.json`
- Create: `src/conductor/assets/contracts/claude-current.json`
- Create: `tests/fixtures/contracts/`
- Create: `tests/test_capabilities.py`
- Create: `tests/test_operations.py`

- [ ] **Step 1: Write failing real-schema tests**

```python
def test_current_codex_contract_selects_admission_without_model_field():
    contract = load_contract("codex-current")
    payload = current_codex_spawn_payload_without_model()
    result = negotiate(contract, payload)
    assert result.mode == OperatingMode.ADMISSION
    assert result.child_model_selectable is False


@pytest.mark.parametrize("raw, expected", [
    ("spawn_agent", "spawn"),
    ("collaboration.spawn_agent", "spawn"),
    ("assign_agent_task", "assign"),
    ("collaboration.followup_task", "followup"),
    ("send_agent_message", "message"),
    ("collaboration.send_message", "message"),
])
def test_tool_names_are_canonicalized(raw, expected):
    assert canonical_operation(raw) == expected
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_capabilities.py tests/test_operations.py -q`

Expected: FAIL because v1 fixtures invent a `model` field and ignore namespaced
follow-up/message tools.

- [ ] **Step 3: Implement negotiation and contracts**

Capability contracts declare provider/CLI range, hook events, exact tool names,
tool-input schemas, model-selector location, correlation fields, usage fields,
decision schema, and trust visibility. Load packaged contracts by digest and
reject unknown/drifted shapes for admission/routing.

Canonicalize namespaced aliases. Classify spawn/assign as new work. Classify
follow-up/message as new work only when a strict v2 envelope says `new_task=true`;
ordinary feedback remains communication. Select routing only when an enforceable
model selector and lifecycle correlation both exist; otherwise select admission,
observe, or unsupported truthfully.

- [ ] **Step 4: Verify GREEN and fixture parity**

Run: `pytest tests/test_capabilities.py tests/test_operations.py -q`

Expected: all supported raw fixtures normalize and every unknown drift fixture
returns unsupported/degraded rather than an assumed contract.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/capabilities.py src/conductor/operations.py src/conductor/assets/contracts tests/fixtures/contracts tests/test_capabilities.py tests/test_operations.py
git commit -m "feat: negotiate truthful provider capabilities"
```

### Task 4: Strict envelope extraction and RunContext identity

**Files:**
- Rewrite: `src/conductor/tool_adapter.py`
- Rewrite: `src/conductor/identity.py`
- Create: `tests/test_envelopes.py`
- Rewrite: `tests/test_identity.py`

- [ ] **Step 1: Write failing malformed/fuzz and root-identity tests**

```python
@pytest.mark.parametrize("payload", [None, [], 1, "text", {"unknown": True}])
def test_malformed_governed_envelope_is_controlled_denial(payload):
    result = normalize_governed_payload(raw_spawn_with_envelope(payload))
    assert result.decision.rule == "INVALID_ENVELOPE"
    assert result.decision.allowed is False


def test_root_transcript_thread_id_becomes_run_id():
    context = resolve_run_context(root_transcript_fixture())
    assert context.run_id == "root-run"
    assert context.thread_id == "root-run"


@given(st.binary(max_size=65536))
def test_envelope_parser_never_raises_unclassified(data):
    result = parse_envelope_bytes(data)
    assert result.kind in {"valid", "missing", "invalid", "oversized"}
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_envelopes.py tests/test_identity.py -q`

Expected: FAIL because JSON lists can reach fail-open and root run resolution is
missing.

- [ ] **Step 3: Implement strict parsing and identity**

Extract exactly one bounded v2 envelope. Reject duplicate tags, scalars, unknown
keys, wrong types, overlong values, absolute/traversing owned paths, and
unsupported schema versions. Return typed parse results; do not use exceptions as
normal classification.

Persist and resolve `RunContext` with provider, run/thread IDs, root model and
source, contract digest, mode, generation, start/heartbeat, and config digest.
Identifiers must match `^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$`. Unknown identity or
model follows explicit deny/observe/degraded config and never fabricates a tier.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_envelopes.py tests/test_identity.py -q`

Expected: all tests and Hypothesis examples pass without unrestricted approval.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/tool_adapter.py src/conductor/identity.py tests/test_envelopes.py tests/test_identity.py
git commit -m "feat: validate operations and run identity strictly"
```

### Task 5: Atomic SQLite reservations and lifecycle

**Files:**
- Create: `src/conductor/store.py`
- Create: `src/conductor/migrations.py`
- Replace: `src/conductor/ledger.py`
- Create: `tests/test_store.py`
- Create: `tests/test_reservation_stress.py`
- Rewrite: `tests/test_lifecycle.py`

- [ ] **Step 1: Write failing atomic-cap and idempotency tests**

```python
def test_100_processes_never_exceed_concurrency_cap(store_path):
    decisions = run_concurrent_decisions(store_path, processes=100, cap=4)
    assert sum(decision.allowed for decision in decisions) == 4
    assert Store(store_path).reserved_count() == 4


def test_one_task_budget_allows_exactly_one_concurrent_reservation(store_path):
    decisions = run_concurrent_budget_decisions(store_path, processes=100, cap=0.15)
    assert sum(decision.allowed for decision in decisions) == 1


@pytest.mark.parametrize("order", lifecycle_permutations())
def test_lifecycle_is_correlated_and_idempotent(store, order):
    for event in order:
        store.record_lifecycle(event)
    assert store.cost_record_count(event_id="task-1-stop") <= 1
    assert store.reservation("task-1").state in TERMINAL_OR_RECOVERABLE_STATES
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_store.py tests/test_reservation_stress.py tests/test_lifecycle.py -q`

Expected: FAIL because v1 check-then-append approves stale snapshots and double
records duplicate stops.

- [ ] **Step 3: Implement the transactional state machine**

Use SQLite WAL, foreign keys, a hook-bounded busy timeout, schema migrations, and
tables for runs, leases, operations, decisions, reservations, lifecycle events,
raw usage, costs, and installation state. In one `BEGIN IMMEDIATE`, expire stale
reservations, load counts/spend, evaluate through a callback, insert the decision,
and insert a unique reservation before commit.

Reservation states are approved, started, stopped, costed, cancelled, expired,
and failed. Pending and started count against caps. Provider correlation and
idempotency keys are unique. Reordered events attach only by correlation ID and
enter recoverable state when prerequisites are absent. Active leases protect GC.

- [ ] **Step 4: Verify GREEN under stress**

Run: `pytest tests/test_store.py tests/test_reservation_stress.py tests/test_lifecycle.py -q`

Expected: all stress tests pass repeatedly with no over-admission or duplicate
cost.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/store.py src/conductor/migrations.py src/conductor/ledger.py tests/test_store.py tests/test_reservation_stress.py tests/test_lifecycle.py
git commit -m "feat: make reservations and lifecycle atomic"
```

### Task 6: Pure mode-aware policy

**Files:**
- Create: `src/conductor/policy.py`
- Rewrite: `src/conductor/hooks/pre_tool_use.py`
- Rewrite: `tests/test_pre_tool_use.py`
- Create: `tests/test_policy_v2.py`

- [ ] **Step 1: Write failing mode truth tables**

```python
def test_admission_mode_does_not_require_unavailable_child_model():
    decision = evaluate(admission_request(task_class="tests"), snapshot())
    assert decision.allowed is True
    assert decision.selected_model is None
    assert decision.savings_eligible is False


def test_unknown_model_never_bypasses_policy():
    decision = evaluate(request(caller_model="unknown"), snapshot(unknown_policy="deny"))
    assert decision.allowed is False
    assert decision.rule == "UNKNOWN_CALLER_MODEL"


def test_high_risk_trigger_requires_configured_posture_in_every_mode():
    decision = evaluate(request(risk_triggers=["payments"]), snapshot(mode="admission"))
    assert decision.allowed is False
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_policy_v2.py tests/test_pre_tool_use.py -q`

Expected: FAIL because v1 inherits the parent model, bypasses unknown callers,
and conflates routing with admission.

- [ ] **Step 3: Implement pure decisions and transactional hook flow**

Policy consumes only validated `NormalizedOperation`, `RunContext`, config, and a
store snapshot. Apply operation allowlist, new-work classification, depth, task
ownership, risk posture, same-tier rules only in routing mode, concurrency,
budget, and degraded policy in explicit order. Every decision has stable rule,
message, mode, selected model or null, reservation estimate, and savings
eligibility.

The hook parses and negotiates before opening the store, then calls the store's
atomic decide-and-reserve method. Controlled denials are provider-formatted.
Unexpected outages follow the configured degraded posture and record a visible
degraded event when possible.

- [ ] **Step 4: Verify GREEN and rule completeness**

Run: `pytest tests/test_policy_v2.py tests/test_pre_tool_use.py -q`

Expected: all rules have allow/deny/boundary tests in every applicable mode.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/policy.py src/conductor/hooks/pre_tool_use.py tests/test_policy_v2.py tests/test_pre_tool_use.py
git commit -m "feat: enforce mode-aware policy atomically"
```

### Task 7: Provider adapters and exactly-once accounting

**Files:**
- Rewrite: `src/conductor/providers/codex.py`
- Rewrite: `src/conductor/providers/claude.py`
- Create: `src/conductor/accounting.py`
- Rewrite: `src/conductor/pricing.py`
- Rewrite: `src/conductor/hooks/lifecycle.py`
- Create: `tests/test_accounting.py`
- Rewrite: `tests/test_provider_claude.py`
- Create: `tests/test_provider_codex.py`

- [ ] **Step 1: Write failing correlation and complete-pricing tests**

```python
def test_out_of_order_claude_starts_do_not_swap_pending_tasks(store):
    reserve(store, correlation="a", model="sonnet")
    reserve(store, correlation="b", model="haiku")
    deliver_start(store, correlation="b")
    deliver_start(store, correlation="a")
    assert store.reservation("a").model == "sonnet"
    assert store.reservation("b").model == "haiku"


def test_duplicate_stop_charges_once(store, transcript):
    deliver_stop(store, event_id="stop-1", transcript=transcript)
    deliver_stop(store, event_id="stop-1", transcript=transcript)
    assert store.cost_record_count(event_id="stop-1") == 1


def test_partial_enabled_tier_pricing_is_rejected():
    with pytest.raises(ValidationError, match="complete pricing"):
        validate_pricing(partially_priced_config())
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_accounting.py tests/test_provider_claude.py tests/test_provider_codex.py -q`

Expected: FAIL because v1 matches the oldest pending task, duplicates stop cost,
and treats partial pricing as verified.

- [ ] **Step 3: Implement adapters and raw usage accounting**

Adapters normalize only fields declared in the selected capability contract and
emit provider-specific decisions. Lifecycle events require provider correlation
IDs. Store immutable `RawUsage` with provider, parser version, source identity,
input, cache-read, cache-write, output, reasoning dimensions, and measured flag.

Require complete finite rates for every enabled model and emitted dimension.
Keep measured and estimated totals/baselines separate. Routing savings appear
only for routing-mode reservations and include assumptions. A unique raw-event
key and cost key make duplicate delivery exactly once.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_accounting.py tests/test_provider_claude.py tests/test_provider_codex.py -q`

Expected: all golden transcripts, duplicate delivery, and partial pricing cases
pass.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/providers src/conductor/accounting.py src/conductor/pricing.py src/conductor/hooks/lifecycle.py tests/test_accounting.py tests/test_provider_claude.py tests/test_provider_codex.py
git commit -m "feat: correlate lifecycle and cost exactly once"
```

### Task 8: Transactional install, repair, and uninstall

**Files:**
- Create: `src/conductor/installation.py`
- Create: `src/conductor/managed_files.py`
- Rewrite: `src/conductor/install.py`
- Replace: `install.sh`
- Replace: `install.ps1`
- Replace: `uninstall.sh`
- Replace: `uninstall.ps1`
- Create: `tests/test_installation_faults.py`
- Rewrite: `tests/test_install.py`
- Rewrite: `tests/test_install_claude.py`

- [ ] **Step 1: Write failing old-or-new installation tests**

```python
@pytest.mark.parametrize("fail_after", range(1, 13))
def test_failure_after_every_boundary_is_old_or_new(home, desired, fail_after):
    old = snapshot_install(home)
    result = Installer(home, fault_after=fail_after).install(desired)
    current = snapshot_install(home)
    assert current == old or current == desired.snapshot


def test_symlink_destination_is_rejected_without_touching_target(home, victim):
    make_symlink(home / "hooks.json", victim)
    with pytest.raises(UnsafeManagedPath):
        Installer(home).install(desired_install())
    assert victim.read_text() == "owned by user"


def test_uninstall_preserves_user_modified_managed_file(home):
    install(home)
    modify_managed_wrapper(home)
    result = uninstall(home)
    assert result.conflicts
    assert modified_wrapper(home).exists()
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_installation_faults.py tests/test_install.py tests/test_install_claude.py -q`

Expected: FAIL because v1 follows symlinks, partially installs, and uses marker
substrings as ownership.

- [ ] **Step 3: Implement staged atomic installation**

Preflight parses every target file, negotiates capabilities, checks trust
visibility, rejects symlink/reparse paths, validates ownership hashes, and renders
the complete desired install before mutation. Stage on the destination
filesystem, flush, keep backups and a rollback journal, and atomically replace.

Persist a managed manifest with exact hashes. Preserve foreign and modified
content. `repair --adopt` records explicit user ownership decisions. Install,
upgrade, repair, and uninstall are idempotent. Shell/PowerShell files become thin
launchers of `python -m conductor installation ...` and contain no separate logic.

- [ ] **Step 4: Verify GREEN and cross-platform quoting fixtures**

Run: `pytest tests/test_installation_faults.py tests/test_install.py tests/test_install_claude.py -q`

Expected: all fault points prove old-or-new state and quoting fixtures match
POSIX and Windows process rules.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/installation.py src/conductor/managed_files.py src/conductor/install.py install.sh install.ps1 uninstall.sh uninstall.ps1 tests/test_installation_faults.py tests/test_install.py tests/test_install_claude.py
git commit -m "feat: install conductor transactionally"
```

### Task 9: Doctor canaries, status, reporting, recovery, and GC

**Files:**
- Rewrite: `src/conductor/doctor.py`
- Rewrite: `src/conductor/status.py`
- Rewrite: `src/conductor/report.py`
- Rewrite: `src/conductor/gc.py`
- Rewrite: `src/conductor/cli.py`
- Create: `src/conductor/recovery.py`
- Create: `tests/test_doctor_v2.py`
- Rewrite: `tests/test_status_report.py`
- Rewrite: `tests/test_gc.py`

- [ ] **Step 1: Write failing operational truth tests**

```python
def test_doctor_fails_when_no_hook_canary_or_current_run(home):
    report = Doctor(home).run(strict=True)
    assert report.ready is False
    assert {check.code for check in report.failed} >= {"HOOK_DENY_CANARY", "RUN_CONTEXT"}


def test_status_invalid_state_is_nonzero(cli, corrupt_store):
    result = cli("status", "--run", "current", "--json")
    assert result.returncode != 0
    assert json.loads(result.stdout)["ready"] is False


def test_gc_never_removes_leased_run(store):
    active = store.create_run(leased=True)
    removed = gc_runs(store, keep=0)
    assert active.run_id not in removed
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_doctor_v2.py tests/test_status_report.py tests/test_gc.py -q`

Expected: FAIL because v1 doctor checks presence only and status masks errors.

- [ ] **Step 3: Implement truthful operations**

Doctor validates config/store schema, complete pricing, policy partitions,
managed manifest hashes, exact hooks/matchers/commands, provider contract/mode,
run identity/heartbeat, trust when observable, store idempotency, and an installed
allow plus known-deny canary. Strict readiness fails on every release-relevant
warning.

Status/report require explicit current or named run selection and return nonzero
for invalid state. Reports separate modes and measured/estimated accounting.
Recovery expires/resolves reservations and interrupted installs explicitly. GC
validates nonnegative options, skips leased runs, and reports actual deletion
failures.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_doctor_v2.py tests/test_status_report.py tests/test_gc.py -q`

Run: `conductor doctor --strict --json`

Expected: tests pass; local doctor truthfully reports unsupported/degraded until
real hook trust/current-run canaries are available.

- [ ] **Step 5: Commit**

```bash
git add src/conductor/doctor.py src/conductor/status.py src/conductor/report.py src/conductor/gc.py src/conductor/cli.py src/conductor/recovery.py tests/test_doctor_v2.py tests/test_status_report.py tests/test_gc.py
git commit -m "feat: make conductor operations truthful"
```

### Task 10: Adversarial, distribution, and release gates

**Files:**
- Create: `tests/test_adversarial.py`
- Create: `tests/test_distribution_clean_env.py`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Modify: `pyproject.toml`
- Modify: `Makefile`

- [ ] **Step 1: Add tests that initially fail release readiness**

Cover JSON scalar/list/null envelopes, duplicate tags, huge payloads, Unicode,
unknown keys, identifiers with separators/traversal, symlink/reparse swaps,
permissions, lock timeout, disk-full injection, 100-process cap races, reordered
and duplicated lifecycle, two simultaneous roots, active-run GC, incomplete
pricing, provider drift, wheel data, and isolated wheel/sdist install. The clean
environment test must execute:

```python
def test_wheel_install_doctor_uninstall_without_checkout(built_wheel, clean_venv):
    clean_venv.pip_install(built_wheel)
    home = clean_venv.temp_home()
    assert clean_venv.run("conductor", "install", "--dry-run", env=home.env).returncode == 0
    doctor = clean_venv.run("conductor", "doctor", "--json", env=home.env)
    assert json.loads(doctor.stdout)["distribution"]["assets_loaded"] is True
    assert clean_venv.run("conductor", "uninstall", "--dry-run", env=home.env).returncode == 0
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_adversarial.py tests/test_distribution_clean_env.py -q`

Expected: at least strict distribution/readiness assertions fail before CI and
artifact metadata are complete.

- [ ] **Step 3: Configure CI and release**

CI matrices Ubuntu, macOS, and Windows with Python 3.11-3.13. Run Ruff, Pyright,
pytest branch coverage, build/twine check, clean installs, pip-audit, CodeQL,
contract validation, and SBOM generation. Enforce 95% branch coverage overall
and 100% for schemas, identity, policy, store, accounting, and installation.

Tag workflow downloads already-tested artifacts, publishes with PyPI Trusted
Publishing, attests provenance, and attaches wheel, sdist, SHA-256 checksums, and
CycloneDX SBOM to GitHub Releases. It has no long-lived token fallback.

- [ ] **Step 4: Verify GREEN locally**

Run: `make check`

Run: `python -m build`

Run: `python -m twine check dist/*`

Run: `pytest tests/test_distribution_clean_env.py -q`

Expected: all local gates pass and installed assets work without the checkout.

- [ ] **Step 5: Commit**

```bash
git add tests/test_adversarial.py tests/test_distribution_clean_env.py .github/workflows pyproject.toml Makefile
git commit -m "ci: enforce conductor public release gates"
```

### Task 11: Public documentation, migration, and v1 removal

**Files:**
- Rewrite: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/provider-contracts.md`
- Create: `docs/configuration.md`
- Create: `docs/cli.md`
- Create: `docs/operations.md`
- Create: `docs/migrating-from-v1.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `SUPPORT.md`
- Create: `RELEASING.md`
- Modify: `CHANGELOG.md`
- Create: `tests/test_public_docs.py`
- Delete after parity proof: obsolete JSONL/v1-only modules, configs, policies, and specs

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_public_docs_are_portable_and_truthful():
    text = public_docs_text()
    assert "/home/neil" not in text
    assert "always routes" not in text.lower()
    assert "guarantees savings" not in text.lower()


def test_commands_modes_and_config_are_documented_exactly():
    assert documented_commands() == parser_commands()
    assert documented_modes() == {"routing", "admission", "observe", "unsupported"}
    assert documented_config_keys() == public_config_schema_keys()
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_public_docs.py -q`

Expected: FAIL because v1 documentation includes checkout assumptions and
unsupported routing claims.

- [ ] **Step 3: Write public docs and remove v1 runtime**

Document pipx/uv installation, capability modes, provider contract capture,
strict envelopes, atomic reservations, pricing semantics, transactional install,
doctor canaries, operations/recovery, configuration, v1 migration, support,
vulnerability reporting, contribution setup, and release dry runs. Changelog
marks v2 breaking and explains admission mode for Codex surfaces without a child
model selector.

Implement `migrate-v1` as an offline converter that writes a disabled candidate
config and imports no JSONL decisions. Remove v1 runtime modules only after every
preserved behavior has a v2 test and no imports refer to them. Do not retain
compatibility aliases or checkout-pinned launchers.

- [ ] **Step 4: Run the final release gate**

Run: `make check`

Run: `python -m build`

Run: `python -m twine check dist/*`

Run: `python -m pip_audit`

Expected: all checks pass without warnings, local paths, stale claims, or dirty
generated artifacts.

- [ ] **Step 5: Commit**

```bash
git add README.md docs SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md SUPPORT.md RELEASING.md CHANGELOG.md src tests/test_public_docs.py
git commit -m "docs: prepare conductor v2 for public release"
```

## Final Verification

- [ ] Run `ruff format --check .`.
- [ ] Run `ruff check .`.
- [ ] Run `pyright`.
- [ ] Run `pytest --cov=conductor --cov-branch --cov-report=term-missing --cov-fail-under=95`.
- [ ] Run module-specific 100% branch coverage gates for schemas, identity, policy, store, accounting, and installation.
- [ ] Run the 100-process concurrency and one-task-budget stress tests repeatedly.
- [ ] Run `python -m build` and `python -m twine check dist/*`.
- [ ] Install wheel and sdist separately into clean temporary virtual environments.
- [ ] Run install/doctor/uninstall from outside the checkout.
- [ ] Run `git diff --check` and confirm only intentional changes remain.
- [ ] Confirm no P0/P1 or actionable P2 review findings remain.
