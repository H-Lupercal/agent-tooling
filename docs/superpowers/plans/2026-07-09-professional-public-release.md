# Professional Public Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task-by-task. This execution is explicitly inline because the
> user prohibited subagents. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finalize `agent-tooling` for independent professional public releases of
`toolbelt-ai` and `codex-conductor`.

**Architecture:** Keep both Python packages self-contained beneath their existing
folders. Move GitHub-recognized automation and governance to the repository root, use
namespaced release tags, and enforce release contracts with root tests.

**Tech Stack:** Python 3.11-3.13, pytest, Ruff, Pyright, uv, Hatchling, GitHub Actions,
CodeQL, Dependabot, pip-audit, CycloneDX, Twine.

---

### Task 1: Record and isolate the work

**Files:**
- Create: `.gitignore`
- Create: `docs/superpowers/specs/2026-07-09-professional-public-release-design.md`
- Create: `docs/superpowers/plans/2026-07-09-professional-public-release.md`

- [ ] Commit the approved design and this plan on `main`.
- [ ] Create `.worktrees/release-finalize-public-v2` on branch
  `release/finalize-public-v2`.
- [ ] Restore both project virtual environments in the worktree without tracking them.
- [ ] Run both current core suites and confirm the baseline passes.

### Task 2: Add release-contract tests first

**Files:**
- Create: `tests/test_release_contract.py`

- [ ] Add tests requiring root workflows, root governance files, immutable action
  pins, project working directories, namespaced tags, 90% gates, valid package URLs,
  tracked lockfiles, and absence of deleted-repository URLs.
- [ ] Run `codex-conductor/.venv/bin/python -m pytest tests/test_release_contract.py -q`.
- [ ] Confirm failures describe the missing monorepo release infrastructure.

### Task 3: Implement root automation

**Files:**
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/codeql.yml`
- Create: `.github/workflows/release-toolbelt.yml`
- Create: `.github/workflows/release-codex-conductor.yml`
- Create: `.github/dependabot.yml`
- Create: `.github/CODEOWNERS`
- Delete: `toolbelt/.github/**`
- Delete: `codex-conductor/.github/**`

- [ ] Pin every action to an immutable upstream commit.
- [ ] Configure path-aware jobs with explicit project directories and unique artifacts.
- [ ] Configure package-specific tags and protected PyPI environments.
- [ ] Run the release-contract test until the automation assertions pass.

### Task 4: Repair public metadata and governance

**Files:**
- Create: `README.md`
- Create: `SECURITY.md`
- Create: `CONTRIBUTING.md`
- Create: `SUPPORT.md`
- Create: `AGENTS.md`
- Modify: `toolbelt/pyproject.toml`
- Modify: `toolbelt/CONTRIBUTING.md`
- Modify: `toolbelt/RELEASING.md`
- Modify: `codex-conductor/pyproject.toml`
- Modify: `codex-conductor/CONTRIBUTING.md`
- Modify: `codex-conductor/docs/RELEASING.md`

- [ ] Point project URLs and clone instructions at `H-Lupercal/agent-tooling`.
- [ ] Document local development and independent release procedures.
- [ ] Run the release-contract and public-documentation tests.

### Task 5: Raise Toolbelt coverage

**Files:**
- Modify: `toolbelt/tests/test_executor_faults.py`
- Modify: `toolbelt/tests/test_planner_v2.py`
- Modify: `toolbelt/tests/test_catalog_v2.py`
- Modify: `toolbelt/tests/test_cli_v2.py`
- Modify additional focused tests only where coverage evidence requires them.
- Modify: `toolbelt/Makefile`
- Modify: `toolbelt/pyproject.toml`

- [ ] Add one focused failing assertion or uncovered-path test at a time.
- [ ] Run the focused test and confirm it exercises the intended path.
- [ ] Repeat until total branch-enabled coverage reaches at least 90%.
- [ ] Set the local and CI release floor to 90%.

### Task 6: Raise Conductor coverage

**Files:**
- Modify: `codex-conductor/tests/test_accounting.py`
- Modify: `codex-conductor/tests/test_identity.py`
- Modify: `codex-conductor/tests/test_install_transactional.py`
- Modify: `codex-conductor/tests/test_store.py`
- Modify additional focused tests only where coverage evidence requires them.
- Modify: `codex-conductor/Makefile`
- Modify: `codex-conductor/pyproject.toml`

- [ ] Add focused tests for accounting dimensions, invalid identity sources, managed
  installation failures, replay conflicts, leases, and transaction rollback.
- [ ] Run each focused test before the complete suite.
- [ ] Repeat until total branch-enabled coverage reaches at least 90%.
- [ ] Set the local and CI release floor to 90%.

### Task 7: Verify installed behavior

**Files:**
- Modify tests only if an acceptance failure exposes a reproducible product defect.

- [ ] Run distribution tests for both packages.
- [ ] Run Toolbelt E2E from a clean temporary home.
- [ ] Install Conductor into disposable Codex and Claude homes.
- [ ] Require strict doctor, lifecycle, report, repair, and uninstall checks to pass.

### Task 8: Security and release audit

**Files:**
- Create local-only reports beneath `.gstack/` when supported.

- [ ] Scan the current tree and Git history for credible secret formats.
- [ ] Audit both locked environments for known vulnerabilities.
- [ ] Check workflow permissions, event interpolation, and action pinning.
- [ ] Build wheel and sdist artifacts, run Twine, generate SBOMs and checksums, and
  inspect wheel contents.
- [ ] Run documentation link/contract checks and compile all Python sources.

### Task 9: Review and integrate

**Files:**
- Review every changed file and final repository status.

- [ ] Run release-contract tests and both complete release gates from a clean state.
- [ ] Review the diff for accidental product/API changes or generated artifacts.
- [ ] Commit the finalized release work.
- [ ] Fast-forward local `main`, rerun smoke gates, and delete the temporary branch and
  owned worktree.
- [ ] Do not push, tag, or publish.

