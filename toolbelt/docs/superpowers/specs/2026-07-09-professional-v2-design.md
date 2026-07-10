# Toolbelt Professional v2 Design

**Status:** Approved for implementation on 2026-07-09.

## Purpose

Toolbelt v2 is a public Python CLI for discovering, planning, applying, verifying,
and removing AI-development tools in a repository. It must be safe enough for a
professional developer to inspect and run without trusting an agent's judgment or
accepting hidden global mutations.

This is a clean break from the prototype. Existing v1 plans and manifests are not
accepted. The `toolbelt migrate-v1` command converts a v1 manifest into a v2
declaration after validation; it never applies changes.

## Release Boundary

Toolbelt remains an independent Git repository and PyPI distribution under
`/home/neil/VSproj/agent-tooling/toolbelt`. It does not share runtime code or a
release cycle with codex-conductor.

The public package provides:

- `toolbelt` console entry point
- Python 3.11, 3.12, and 3.13 support
- Linux, macOS, and Windows support
- wheel and source distribution artifacts
- bundled, versioned seed catalog

## Design Principles

1. Observation is pure. `scan`, `discover`, `status`, and `doctor` never write.
2. Recommendations are evidence-based. A language alone cannot justify a global
   install, and native harness capabilities are preferred over redundant tools.
3. Plans are reviewable artifacts. Exact argv, permissions, scope, provenance,
   verification, rollback, and evidence are visible before approval.
4. Apply is transactional. A failed action restores all earlier actions in the
   same transaction or reports a precise rollback failure.
5. Repository files are untrusted input. All paths are contained beneath the
   selected root, symlink escapes are rejected, and configuration is strictly
   validated.
6. Machine state and project intent are separate. Declarative state is committed;
   execution journals and secrets remain local.
7. Public claims require executable proof in CI and clean virtual environments.

## Architecture

```text
Repository + optional intent brief + harness capabilities
                         |
                         v
                 Pure evidence scanner
                         |
                         v
              Normalized evidence inventory
                         |
                         v
             Catalog matcher + policy engine
                         |
                         v
          Immutable, content-addressed action plan
                         |
                         v
              Preflight + explicit approval
                         |
                         v
          Transaction executor + rollback journal
                         |
              +----------+----------+
              |                     |
              v                     v
      project declaration      local state database
```

### Package Layout

The implementation moves to a `src/toolbelt/` layout with these boundaries:

- `cli.py`: argument parsing, rendering selection, and stable exit codes only.
- `schemas.py`: strict public schemas and schema-version dispatch.
- `scanner.py`: bounded repository traversal and evidence collection.
- `ignore.py`: default exclusions plus `.gitignore`/`.toolbeltignore` matching.
- `capabilities.py`: live Claude Code and Codex capability inventory.
- `catalog.py`: bundled/override catalog loading, provenance, and validation.
- `policy.py`: recommendation eligibility and confidence rules.
- `planner.py`: deterministic plans bound to repository and catalog digests.
- `executor.py`: preflight, approval, execution, verification, and rollback.
- `paths.py`: root containment, symlink checks, and atomic file replacement.
- `state.py`: declaration, journal, adoption, drift, and reconciliation state.
- `adapters/`: provider-specific argv construction and live-state discovery.
- `rendering.py`: human text and versioned JSON output.

Pydantic v2 validates public schemas. PathSpec implements Git-compatible ignore
matching. The CLI remains `argparse`-based to avoid adding presentation
dependencies to a mutation-sensitive tool.

## State Model

Toolbelt v2 uses two stores:

1. `.toolbelt/toolbelt.lock.toml` is committed. It declares selected tools,
   catalog versions, exact provenance, install scope, permissions, required
   environment-variable names, and repository-owned artifacts.
2. `.toolbelt/state.sqlite3` is ignored. It records transactions, action
   attempts, verification results, backups, rollback outcomes, and live harness
   identities. SQLite transactions serialize concurrent Toolbelt processes.

Secrets are never stored in either file. Toolbelt reports whether a required
environment variable is present but never logs or serializes its value.

Plans are JSON documents containing:

- schema version and plan ID
- canonical repository path and repository identity
- Git HEAD and dirty-state digest when Git is available
- catalog digest and capability digest
- ordered actions with exact non-shell argv
- permissions, install scope, evidence, and confidence explanation
- verification and rollback steps
- creation and expiry timestamps

`apply` rejects a plan when its repository, catalog, capabilities, or relevant
working-tree inputs changed after planning.

## Scanning And Matching

The scanner performs a bounded walk and excludes `.git`, Toolbelt state,
virtual environments, dependency/vendor trees, build output, caches, coverage
artifacts, generated files, and test fixtures by default. Users may opt test
fixtures back in explicitly.

The scanner honors `.gitignore` and `.toolbeltignore`, detects nested manifests,
and records every evidence source as a repository-relative path. It never imports
or executes repository code.

Recommendation rules distinguish:

- required capabilities explicitly declared by project configuration
- strong evidence such as a configured test runner or infrastructure file
- weak evidence such as a language extension
- already available native/provider capabilities
- already installed but unmanaged tools

Weak evidence is shown as advisory and cannot produce an install action by
itself. Existing unmanaged tools produce `adopt`, `leave-unmanaged`, or `replace`
choices, never a blind reinstall. User-global actions require an explicit
`--allow-user-scope` approval in addition to action approval.

## Catalog Contract

Every catalog entry declares:

- immutable tool ID and catalog schema version
- exact distribution provenance and pinned version/range policy
- upstream homepage and license metadata
- supported operating systems and harnesses
- least-privilege permission vocabulary
- installation scope and expected artifacts
- required environment-variable names
- evidence match groups and their explanations
- install, verify, and rollback operations
- whether an operation requires network access or elevated privileges

The bundled catalog contains only entries whose commands are exercised by
contract tests. Unavailable, deprecated, or unverified entries remain disabled.
The public CLI never downloads executable catalog content from an arbitrary URL.
A catalog override is a local file whose digest is printed in every plan.

## Transaction Semantics

Before executing any action, Toolbelt validates every argv, binary, path,
permission, secret-name requirement, provider capability, ownership marker, and
rollback operation. No action begins when preflight fails.

The executor never invokes a shell. It uses argv arrays with timeouts, bounded
output capture, and redaction of values corresponding to declared secret names.
Repository file changes use same-filesystem temporary files, flush, and atomic
replace. Managed blocks require exact markers and refuse malformed or duplicate
ownership regions.

Each successful step is journaled before the next begins. On failure, rollback
runs in reverse order. The final result distinguishes:

- apply failed and rollback completed
- apply failed and rollback was incomplete
- apply succeeded but verification failed and rollback completed
- apply and verification succeeded

An interrupted process can be inspected and recovered with `toolbelt recover`.

## CLI And Error Contract

Primary commands are `scan`, `discover`, `plan`, `apply`, `status`, `doctor`,
`verify`, `adopt`, `remove`, `reconcile`, `recover`, `catalog validate`, and
`migrate-v1`.

Human output goes to stdout, diagnostics to stderr, and `--json` emits a
versioned object with no surrounding prose. Stable exit codes distinguish usage,
validation, stale plans, declined actions, apply failure, rollback failure,
verification failure, drift, and internal failure. Read-only commands return
nonzero when their requested assertion fails, not merely when an exception is
uncaught.

## Failure Handling

- Traversal, absolute-path, symlink, and ownership-marker violations fail closed.
- Missing binaries and provider capabilities are preflight failures.
- Timeouts terminate the process group where supported and produce a recoverable
  transaction state.
- Disk-full and permission failures preserve the previous committed declaration.
- Concurrent `apply` attempts serialize; a second process reports the owning
  transaction rather than waiting indefinitely.
- Unknown catalog or state schema versions are rejected with migration guidance.
- Malformed repository files become bounded evidence errors, never scanner crashes.

## Test Strategy

Pytest, pytest-cov, and Hypothesis are development dependencies. The required
test layers are:

- unit tests for every schema, match rule, renderer, path rule, and exit code
- property tests for schema round trips, path containment, managed blocks,
  redaction, and plan determinism
- fixture-based scans across Python, Node, monorepo, Terraform, Docker, empty,
  ignored, generated, malformed, deeply nested, and large repositories
- provider contract tests using captured, versioned Claude/Codex outputs
- subprocess tests for nonzero exits, signals, timeouts, large output, missing
  binaries, and Unicode paths
- multiprocessing tests for concurrent plans, applies, adoption, and recovery
- fault-injection tests after every mutation boundary
- clean-venv wheel and sdist install, CLI, data-file, and uninstall tests
- Windows, macOS, and Linux CI on Python 3.11 through 3.13

The coverage floor is 95% branch coverage overall and 100% branch coverage for
schemas, paths, executor transaction handling, and state migration.

## Public Release

CI runs formatting, linting, typing, unit/property/integration tests, coverage,
package build, artifact inspection, dependency audit, and clean-install smoke
tests. Release tags build once and publish the tested artifacts through PyPI
Trusted Publishing. GitHub Releases receive the same wheel and sdist, checksums,
an SBOM, and build provenance attestation.

The repository includes README, CLI reference, architecture guide, catalog
authoring guide, migration guide, SECURITY.md, CONTRIBUTING.md, changelog, code
of conduct, support policy, and release checklist.

## Release Acceptance

Toolbelt v2 is release-ready only when:

- all CI matrix jobs pass from a clean checkout
- wheel and sdist install and run without repository access
- no open P0/P1 or actionable P2 review findings remain
- the branch-coverage gates pass
- transaction fault tests demonstrate no silent partial state
- the seed catalog has contract coverage for every enabled entry
- public documentation contains no machine-local paths or unsupported claims
- a release dry run produces inspectable artifacts without publishing them

Actual pushing, tagging, GitHub configuration, and PyPI publication require
separate user authorization.

## Explicit Non-Goals

- Toolbelt does not autonomously browse for or approve tools.
- Toolbelt is not a general package manager.
- Toolbelt does not store secret values.
- Toolbelt does not execute repository code to infer its stack.
- Toolbelt does not merge its release cycle with codex-conductor.
