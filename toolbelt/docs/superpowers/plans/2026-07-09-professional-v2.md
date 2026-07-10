# Toolbelt Professional v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a deterministic, transactional, publicly distributable Toolbelt v2 CLI that professional developers can trust to inspect and manage AI-development tools.

**Architecture:** Preserve the useful prototype algorithms only where their behavior survives the v2 contracts. Move the package to `src/`, enforce strict Pydantic schemas, make scans pure, bind plans to content digests, separate a committed TOML declaration from SQLite runtime state, and execute approved actions through a journaled rollback transaction.

**Tech Stack:** Python 3.11-3.13, Pydantic 2, PathSpec, SQLite, argparse, pytest, Hypothesis, Ruff, Pyright, pytest-cov, build, twine.

---

## File Map

- `src/toolbelt/schemas.py`: all public v2 schemas and stable enums.
- `src/toolbelt/paths.py`: repository containment and atomic file operations.
- `src/toolbelt/ignore.py`: default and Git-compatible ignore rules.
- `src/toolbelt/scanner.py`: pure, bounded evidence collection.
- `src/toolbelt/capabilities.py`: normalized provider capability inventory.
- `src/toolbelt/catalog.py`: packaged catalog loading and strict validation.
- `src/toolbelt/policy.py`: recommendation eligibility and explanations.
- `src/toolbelt/planner.py`: deterministic, digest-bound action plans.
- `src/toolbelt/state.py`: TOML declaration and SQLite journal/state.
- `src/toolbelt/executor.py`: preflight, execution, verification, rollback, recovery.
- `src/toolbelt/adapters/`: Claude, Codex, and command adapters.
- `src/toolbelt/rendering.py`: human and versioned JSON output.
- `src/toolbelt/cli.py`: command dispatch and exit-code contract.
- `src/toolbelt/data/catalog.toml`: bundled, pinned seed catalog.

### Task 1: Public package and quality baseline

**Files:**
- Create: `pyproject.toml`
- Create: `src/toolbelt/__init__.py`
- Create: `src/toolbelt/__main__.py`
- Modify/move: `toolbelt/*.py` to `src/toolbelt/`
- Create: `tests/test_distribution.py`
- Modify: `.gitignore`
- Modify: `Makefile`

- [ ] **Step 1: Write a failing installed-package test**

```python
class DistributionTests(unittest.TestCase):
    def test_public_metadata_and_console_entrypoint(self):
        import importlib.metadata
        import toolbelt

        self.assertEqual(toolbelt.__version__, importlib.metadata.version("toolbelt-ai"))
        self.assertTrue(callable(toolbelt.main))
```

- [ ] **Step 2: Verify RED**

Run: `python3 -m unittest tests.test_distribution -v`

Expected: FAIL because the project has no installable distribution or public `main`.

- [ ] **Step 3: Add the package contract and move sources**

Use Hatchling with project name `toolbelt-ai`, console script
`toolbelt = toolbelt.cli:main`, dynamic version from `toolbelt.__version__`,
package data `toolbelt/data/*.toml`, required Python `>=3.11`, and runtime
dependencies `pydantic>=2.8,<3` and `pathspec>=0.12,<1`. Add optional `dev`
dependencies for pytest, pytest-cov, hypothesis, ruff, pyright, build, twine,
pip-audit, and cyclonedx-bom. Export only `__version__` and `main`:

```python
from toolbelt.cli import main

__version__ = "2.0.0"
__all__ = ["__version__", "main"]
```

Move the existing package mechanically to `src/toolbelt/`, update the Makefile
to use `python -m pytest`, `ruff check`, `ruff format --check`, `pyright`, and
`python -m build`, and ignore `.venv/`, `.coverage`, `coverage.xml`, `dist/`,
`build/`, and `*.egg-info/`.

- [ ] **Step 4: Verify GREEN and preserve the prototype suite**

Run: `python3 -m pip install -e '.[dev]'`

Run: `python3 -m unittest discover -s tests -v`

Run: `python3 -m unittest tests.test_distribution -v`

Expected: all existing tests and the distribution test pass.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src tests/test_distribution.py .gitignore Makefile
git commit -m "build: package toolbelt v2"
```

### Task 2: Strict v2 schemas and stable errors

**Files:**
- Create: `src/toolbelt/schemas.py`
- Create: `src/toolbelt/errors.py`
- Create: `tests/test_schemas.py`
- Modify: `src/toolbelt/models.py`

- [ ] **Step 1: Write failing strict-schema tests**

```python
def test_plan_rejects_unknown_fields_and_absolute_paths():
    payload = valid_plan_payload()
    payload["surprise"] = True
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)

    payload = valid_plan_payload()
    payload["repository"]["root"] = "/tmp/elsewhere"
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)


@given(st.text(max_size=300))
def test_relative_path_schema_never_accepts_escape(value):
    accepted = relative_path_or_none(value)
    if accepted is not None:
        assert not accepted.is_absolute()
        assert ".." not in accepted.parts
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_schemas.py -q`

Expected: FAIL because `PlanV2` and strict path types do not exist.

- [ ] **Step 3: Implement the public schema surface**

Define frozen, `extra="forbid"` Pydantic models for `EvidenceV2`,
`CapabilitySnapshot`, `CatalogToolV2`, `ActionStepV2`, `ActionV2`,
`RepositoryBinding`, `PlanV2`, `DeclarationV2`, and `CommandResultV2`. Use
closed enums for permission, install scope, action operation, verification
state, and transaction state. Validate schema version `2`, nonempty bounded IDs,
finite confidence, non-shell argv arrays, relative artifact paths, unique action
IDs, and exact catalog/tool references.

Define `ToolbeltError` subclasses with stable exit codes: usage 2, validation 3,
stale plan 4, declined 5, apply 6, rollback 7, verification 8, drift 9, internal
10. No command handler maps validation errors to success.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_schemas.py -q`

Run: `pytest tests/test_core.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/schemas.py src/toolbelt/errors.py src/toolbelt/models.py tests/test_schemas.py
git commit -m "feat: define strict v2 contracts"
```

### Task 3: Pure bounded scanner and ignore engine

**Files:**
- Create: `src/toolbelt/ignore.py`
- Create: `src/toolbelt/scanner.py`
- Create: `tests/test_scanner_v2.py`
- Create: `tests/fixtures/repos/ignored_noise/.gitignore`
- Modify: `src/toolbelt/evidence.py`

- [ ] **Step 1: Write failing purity and exclusion tests**

```python
def test_scan_is_pure_and_ignores_fixtures_vendor_and_generated(tmp_path):
    repo = build_noisy_repo(tmp_path)
    before = snapshot_tree(repo)
    evidence = scan_repository(repo)
    after = snapshot_tree(repo)

    assert before == after
    assert {item.key for item in evidence if item.type == "infra"} == {"github_actions"}
    assert all("fixtures" not in item.source for item in evidence)
    assert all("node_modules" not in item.source for item in evidence)


def test_scan_does_not_follow_symlink_outside_root(tmp_path):
    repo, outside = repo_with_external_symlink(tmp_path)
    assert str(outside) not in {item.source for item in scan_repository(repo)}
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_scanner_v2.py -q`

Expected: FAIL because v1 scanning includes fixtures and writes last-scan state.

- [ ] **Step 3: Implement bounded traversal**

Build `IgnoreRules` from fixed exclusions, root/nested `.gitignore`, and
`.toolbeltignore`. Walk with `os.scandir`, never follow directory symlinks,
enforce configurable file/depth/byte limits, and return sorted immutable
evidence plus bounded scan warnings. Parse manifests as data only; decoding or
parse failures become evidence warnings containing relative paths.

`scan_repository()` must not call declaration/state functions or create
`.toolbelt/`.

- [ ] **Step 4: Verify GREEN and performance bound**

Run: `pytest tests/test_scanner_v2.py tests/test_core.py -q`

Run: `pytest tests/test_scanner_v2.py::test_100k_entry_scan_respects_limits -q`

Expected: all tests pass and the synthetic limit test completes under five
seconds on CI hardware.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/ignore.py src/toolbelt/scanner.py src/toolbelt/evidence.py tests/test_scanner_v2.py tests/fixtures/repos/ignored_noise
git commit -m "feat: make repository scanning pure and bounded"
```

### Task 4: Capabilities, catalog, and conservative policy

**Files:**
- Create: `src/toolbelt/capabilities.py`
- Create: `src/toolbelt/adapters/base.py`
- Create: `src/toolbelt/adapters/codex.py`
- Create: `src/toolbelt/adapters/claude.py`
- Rewrite: `src/toolbelt/catalog.py`
- Create: `src/toolbelt/policy.py`
- Create: `src/toolbelt/data/catalog.toml`
- Create: `tests/test_capabilities.py`
- Create: `tests/test_policy.py`
- Create: `tests/test_catalog_v2.py`

- [ ] **Step 1: Write failing adoption and weak-evidence tests**

```python
def test_existing_unmanaged_tool_is_never_reinstalled():
    recs = recommend(catalog(), python_evidence(), capabilities(existing={"ruff"}))
    ruff = next(item for item in recs if item.tool_id == "ruff")
    assert ruff.allowed_operations == ("adopt", "leave_unmanaged", "replace")
    assert "install" not in ruff.allowed_operations


def test_language_extension_cannot_authorize_user_global_install():
    recs = recommend(catalog(), [evidence("lang", "python")], capabilities())
    assert all(not item.actionable for item in recs)


def test_native_filesystem_and_git_capabilities_suppress_redundant_mcp():
    ids = {item.tool_id for item in recommend(catalog(), repo_evidence(), native_codex())}
    assert "mcp-filesystem" not in ids
    assert "mcp-git" not in ids
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_capabilities.py tests/test_policy.py tests/test_catalog_v2.py -q`

Expected: FAIL because v1 proposes reinstalls and treats broad matches as actionable.

- [ ] **Step 3: Implement adapters and policy**

Provider adapters execute bounded read-only inventory commands and parse
versioned fixtures into `CapabilitySnapshot`. Parsing failure produces an
unknown capability, never an assumption of absence.

Catalog loading uses `importlib.resources`, validates all entries through
`CatalogToolV2`, rejects duplicate IDs/live names, secret-shaped argv, shell
metacharacter wrappers, unsupported provenance, missing rollback, unpinned
network packages, and inconsistent platform claims.

Policy emits `Recommendation` objects with `actionable`, `why`, `evidence`,
`missing_requirements`, and `allowed_operations`. Weak evidence is advisory.
User-scope and network actions require independent plan flags.

- [ ] **Step 4: Verify GREEN and catalog contract coverage**

Run: `pytest tests/test_capabilities.py tests/test_policy.py tests/test_catalog_v2.py -q`

Expected: all tests pass and every enabled catalog entry has install/verify/
rollback contract cases.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/capabilities.py src/toolbelt/adapters src/toolbelt/catalog.py src/toolbelt/policy.py src/toolbelt/data tests/test_capabilities.py tests/test_policy.py tests/test_catalog_v2.py
git commit -m "feat: add capability-aware conservative recommendations"
```

### Task 5: Digest-bound deterministic planner

**Files:**
- Create: `src/toolbelt/planner.py`
- Create: `tests/test_planner_v2.py`
- Modify: `src/toolbelt/plan.py`

- [ ] **Step 1: Write failing determinism and stale-plan tests**

```python
@given(st.permutations(sample_evidence()))
def test_plan_is_order_independent(evidence):
    first = build_plan(repo(), list(evidence), catalog(), capabilities())
    second = build_plan(repo(), list(reversed(evidence)), catalog(), capabilities())
    assert first.model_dump_json() == second.model_dump_json()


def test_changed_catalog_or_repo_rejects_plan(tmp_path):
    plan = write_valid_plan(tmp_path)
    mutate_relevant_repo_input(tmp_path)
    with pytest.raises(StalePlanError):
        validate_plan_binding(plan, tmp_path, catalog(), capabilities())
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_planner_v2.py -q`

Expected: FAIL because v1 plans lack repository/catalog/capability bindings.

- [ ] **Step 3: Implement canonical planning**

Canonicalize evidence/actions, calculate SHA-256 digests for relevant repository
inputs, catalog bytes, and capabilities, bind Git HEAD and dirty-file hashes when
available, add creation/expiry timestamps, and derive the plan ID from canonical
JSON excluding the plan ID itself. Exact argv and rollback argv must appear in
the plan. Validation recomputes every binding before approval.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_planner_v2.py -q`

Run: `pytest tests/test_core.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/planner.py src/toolbelt/plan.py tests/test_planner_v2.py
git commit -m "feat: bind plans to deterministic repository state"
```

### Task 6: Contained paths, declaration, and SQLite state

**Files:**
- Create: `src/toolbelt/paths.py`
- Create: `src/toolbelt/state.py`
- Create: `tests/test_paths.py`
- Create: `tests/test_state_v2.py`
- Modify: `src/toolbelt/manifest.py`

- [ ] **Step 1: Write failing containment and concurrency tests**

```python
@given(st.text(max_size=260))
def test_resolve_owned_path_never_escapes(value, repo):
    try:
        result = resolve_owned_path(repo, value)
    except PathViolation:
        return
    assert result.is_relative_to(repo.resolve())


def test_32_concurrent_state_writers_preserve_all_transactions(tmp_path):
    run_parallel_writers(tmp_path, count=32)
    assert StateStore(tmp_path).transaction_count() == 32
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_paths.py tests/test_state_v2.py -q`

Expected: FAIL because v1 paths and JSON state have no strict transaction model.

- [ ] **Step 3: Implement state boundaries**

`resolve_owned_path()` rejects absolute paths, `..`, NULs, device names,
symlink/reparse components, and roots that change identity. Atomic writes use a
same-directory temporary file, flush, fsync where supported, and `os.replace`.

`StateStore` initializes a versioned SQLite schema with WAL, foreign keys, a
five-second-or-shorter configurable busy timeout, transactions, actions,
backups, command results, and recovery records. The committed lock TOML is
rendered deterministically and changed only after successful verification.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_paths.py tests/test_state_v2.py -q`

Expected: all property and multiprocessing tests pass.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/paths.py src/toolbelt/state.py src/toolbelt/manifest.py tests/test_paths.py tests/test_state_v2.py
git commit -m "feat: add contained atomic state management"
```

### Task 7: Transactional executor and recovery

**Files:**
- Create: `src/toolbelt/executor.py`
- Create: `tests/test_executor_v2.py`
- Create: `tests/test_executor_faults.py`
- Modify: `src/toolbelt/harness.py`
- Modify: `src/toolbelt/apply.py`

- [ ] **Step 1: Write failing all-or-rollback tests**

```python
@pytest.mark.parametrize("fail_after", range(1, 9))
def test_failure_at_every_boundary_restores_original_state(repo, plan, fail_after):
    before = snapshot_machine_and_repo(repo)
    result = Executor(fault_after=fail_after).apply(plan, repo)
    assert result.state in {"rolled_back", "rollback_failed"}
    if result.state == "rolled_back":
        assert snapshot_machine_and_repo(repo) == before


def test_timeout_kills_child_group_and_records_recovery(repo, timeout_plan):
    result = Executor(command_timeout=0.1).apply(timeout_plan, repo)
    assert result.state == "rolled_back"
    assert not child_process_is_alive(result.command_pid)
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_executor_v2.py tests/test_executor_faults.py -q`

Expected: FAIL because v1 records partial actions and does not restore the
transaction as a unit.

- [ ] **Step 3: Implement preflight and journaled apply**

Preflight validates every binary, capability, path, ownership marker, scope,
permission, secret-name presence, verify command, rollback command, and plan
binding before mutation. Commands use argv without a shell, bounded stdout/stderr,
declared-secret redaction, process-group timeouts, and per-step result records.

Journal each completed step. Verify the full action set before committing the
declaration. Reverse completed steps on failure and distinguish complete from
incomplete rollback. `recover(transaction_id)` resumes rollback or finalizes a
verified commit based on journal state.

- [ ] **Step 4: Verify GREEN and stress**

Run: `pytest tests/test_executor_v2.py tests/test_executor_faults.py -q`

Run: `pytest tests/test_executor_v2.py::test_concurrent_apply_serializes -q`

Expected: all tests pass without leaked processes or partial silent state.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/executor.py src/toolbelt/harness.py src/toolbelt/apply.py tests/test_executor_v2.py tests/test_executor_faults.py
git commit -m "feat: execute plans transactionally"
```

### Task 8: CLI, JSON contract, adoption, migration, and doctor

**Files:**
- Rewrite: `src/toolbelt/cli.py`
- Create: `src/toolbelt/rendering.py`
- Create: `src/toolbelt/doctor.py`
- Create: `src/toolbelt/migration.py`
- Create: `tests/test_cli_v2.py`
- Create: `tests/test_migration.py`
- Modify: `src/toolbelt/reconcile.py`

- [ ] **Step 1: Write failing end-to-end CLI tests**

```python
@pytest.mark.parametrize("command", ["scan", "discover", "status", "doctor"])
def test_read_only_commands_leave_tree_byte_identical(cli, repo, command):
    before = snapshot_tree(repo)
    result = cli(command, "--path", str(repo), "--json")
    assert result.returncode == 0
    assert json.loads(result.stdout)["schema_version"] == 2
    assert snapshot_tree(repo) == before


def test_migrate_v1_writes_disabled_candidate_only(cli, v1_repo):
    result = cli("migrate-v1", "--path", str(v1_repo), "--out", "candidate.toml")
    assert result.returncode == 0
    assert not (v1_repo / ".toolbelt" / "state.sqlite3").exists()
    assert load_toml(v1_repo / "candidate.toml")["enabled"] is False
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_cli_v2.py tests/test_migration.py -q`

Expected: FAIL because v1 scan/status mutate or lack v2 JSON and migration.

- [ ] **Step 3: Implement the stable CLI**

Dispatch `scan`, `discover`, `plan`, `apply`, `status`, `doctor`, `verify`,
`adopt`, `remove`, `reconcile`, `recover`, `catalog validate`, and `migrate-v1`.
All commands support `--json` where meaningful. JSON stdout is one strict v2
object; diagnostics use stderr. Map only declared `ToolbeltError` exit codes and
render unexpected exceptions as internal failures without tracebacks unless
`--debug` is supplied.

Doctor validates distribution data, catalog contracts, root permissions,
provider capability parsing, state schema, lock declaration, and safe dry-run
execution. Strict mode treats every readiness warning as nonzero.

- [ ] **Step 4: Verify GREEN**

Run: `pytest tests/test_cli_v2.py tests/test_migration.py -q`

Run: `toolbelt doctor --strict --json`

Expected: tests pass and doctor emits valid JSON with a truthful readiness
verdict.

- [ ] **Step 5: Commit**

```bash
git add src/toolbelt/cli.py src/toolbelt/rendering.py src/toolbelt/doctor.py src/toolbelt/migration.py src/toolbelt/reconcile.py tests/test_cli_v2.py tests/test_migration.py
git commit -m "feat: expose the professional v2 CLI"
```

### Task 9: Adversarial, distribution, and cross-platform test gates

**Files:**
- Create: `tests/test_adversarial.py`
- Create: `tests/test_distribution_clean_env.py`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/release.yml`
- Modify: `pyproject.toml`
- Modify: `Makefile`

- [ ] **Step 1: Add tests that initially fail release gates**

Cover traversal, symlink/reparse swaps, malformed TOML/JSON, duplicate managed
blocks, secret-shaped argv, 10 MiB command output, process timeouts, disk-full
faults, stale plans, 32 concurrent applies, Unicode paths, absent Git, read-only
repositories, wheel data files, and isolated wheel/sdist installs. The wheel test
must run:

```python
def test_wheel_runs_without_checkout(built_wheel, clean_venv):
    clean_venv.pip_install(built_wheel)
    result = clean_venv.run("toolbelt", "doctor", "--strict", "--json", cwd="/")
    assert result.returncode == 0
    assert json.loads(result.stdout)["distribution"]["catalog_loaded"] is True
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_adversarial.py tests/test_distribution_clean_env.py -q`

Expected: at least the package-data or strict-doctor gate fails before release
configuration is complete.

- [ ] **Step 3: Configure CI and release artifacts**

CI matrices Ubuntu, macOS, and Windows against Python 3.11-3.13. Separate jobs
run Ruff, Pyright, pytest with branch coverage, build/twine check, clean install,
pip-audit, CodeQL, and SBOM creation. Enforce 95% branch coverage overall and
100% for schemas, paths, state, and executor modules.

Release workflow triggers on `v*` tags, downloads the already-tested artifacts,
uses PyPI Trusted Publishing, creates GitHub attestations, and attaches wheel,
sdist, SHA-256 checksums, and CycloneDX SBOM to the GitHub release. It contains
no token secret fallback.

- [ ] **Step 4: Verify GREEN locally**

Run: `make check`

Run: `python -m build`

Run: `python -m twine check dist/*`

Run: `pytest tests/test_distribution_clean_env.py -q`

Expected: all checks pass and artifacts install without source-tree access.

- [ ] **Step 5: Commit**

```bash
git add tests/test_adversarial.py tests/test_distribution_clean_env.py .github/workflows pyproject.toml Makefile
git commit -m "ci: enforce public release gates"
```

### Task 10: Professional documentation and final migration cleanup

**Files:**
- Rewrite: `README.md`
- Create: `docs/architecture.md`
- Create: `docs/cli.md`
- Create: `docs/catalog-authoring.md`
- Create: `docs/migrating-from-v1.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `CODE_OF_CONDUCT.md`
- Create: `SUPPORT.md`
- Create: `RELEASING.md`
- Modify: `CHANGELOG.md`
- Modify: `LICENSE`
- Delete after parity proof: obsolete v1-only modules and specs
- Test: `tests/test_public_docs.py`

- [ ] **Step 1: Write failing documentation contract tests**

```python
def test_public_docs_have_no_local_paths_or_unsupported_claims():
    text = public_docs_text()
    assert "/home/neil" not in text
    assert "guarantees cost savings" not in text.lower()
    assert "latest" not in bundled_network_package_specs()


def test_every_cli_command_is_documented():
    assert documented_commands() == parser_commands()
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_public_docs.py -q`

Expected: FAIL because prototype documentation and paths do not describe v2.

- [ ] **Step 3: Write public documentation and remove dead v1 surfaces**

Document installation with `pipx` and `uv tool`, quick-start dry runs, exact
mutation/approval semantics, declaration/state separation, recovery, exit codes,
JSON schema versioning, catalog review, provider limitations, migration, support,
vulnerability reporting, contribution setup, and release dry runs. Changelog
marks v2 as breaking and v1 plans/manifests unsupported without migration.

Delete v1 modules only after all preserved behaviors map to v2 tests and no
imports reference them. Do not retain compatibility aliases.

- [ ] **Step 4: Run the final release gate**

Run: `make check`

Run: `python -m build`

Run: `python -m twine check dist/*`

Run: `python -m pip_audit`

Expected: all checks pass with no warnings, no stale references, and no dirty
generated artifacts.

- [ ] **Step 5: Commit**

```bash
git add README.md docs SECURITY.md CONTRIBUTING.md CODE_OF_CONDUCT.md SUPPORT.md RELEASING.md CHANGELOG.md LICENSE src tests/test_public_docs.py
git commit -m "docs: prepare toolbelt v2 for public release"
```

## Final Verification

- [ ] Run `ruff format --check .`
- [ ] Run `ruff check .`
- [ ] Run `pyright`
- [ ] Run `pytest --cov=toolbelt --cov-branch --cov-report=term-missing --cov-fail-under=95`
- [ ] Run module-specific 100% coverage gates for schemas, paths, state, and executor.
- [ ] Run `python -m build` and `python -m twine check dist/*`.
- [ ] Install wheel and sdist separately into clean temporary virtual environments.
- [ ] Run `toolbelt doctor --strict --json` from outside the checkout.
- [ ] Run `git diff --check` and confirm `git status --short` contains only intentional changes.
- [ ] Confirm no P0/P1 or actionable P2 review findings remain.
