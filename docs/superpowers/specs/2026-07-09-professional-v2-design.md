# codex-conductor Professional v2 Design

**Status:** Approved for implementation on 2026-07-09.

## Purpose

codex-conductor v2 is a public Python CLI and hook runtime that applies explicit,
observable admission and routing policy to native Codex and Claude Code agent
operations. It must never claim model routing, cost control, or concurrency
enforcement that the active provider contract cannot express.

This is a clean break from v1. Version 1 configuration, JSONL state, hook
wrappers, and policy envelopes are not used at runtime. `conductor migrate-v1`
can translate compatible configuration into a disabled v2 candidate for review;
it never enables hooks automatically.

## Release Boundary

codex-conductor remains an independent Git repository and PyPI distribution at
`/home/neil/VSproj/agent-tooling/codex-conductor`. The installed wheel contains
all provider assets, policies, schemas, and default configuration. Runtime hooks
import the installed package and never add a source checkout to `sys.path`.

The release supports Python 3.11, 3.12, and 3.13 on Linux, macOS, and Windows.

## Truthful Operating Modes

Provider capability negotiation selects one explicit mode:

1. `routing`: the provider exposes an enforceable child-model selector plus
   correlated lifecycle events. Conductor may enforce task-class routing and
   calculate routing savings.
2. `admission`: the provider exposes correlated agent operations but not child
   model selection. Conductor enforces allowed operations, depth, concurrency,
   reservations, and configured budgets without claiming model routing or
   counterfactual savings.
3. `observe`: the provider exposes lifecycle information but cannot reliably
   block operations. Conductor records labeled observations only.
4. `unsupported`: required identity or lifecycle capabilities are absent.
   Installation or enablement fails with a precise explanation.

The default policy may require a minimum mode. A mismatch is a hard readiness
failure, not a silent fallback.

## Architecture

```text
Raw provider hook payload
          |
          v
 Provider adapter + capability contract
          |
          v
 Strict normalized operation + RunContext
          |
          v
  BEGIN IMMEDIATE (SQLite transaction)
          |
          +--> expire leases and stale reservations
          +--> load caller, tier, budget, and active counts
          +--> evaluate operation and envelope policy
          +--> insert decision + unique reservation
          |
          v
 Provider-specific decision response

Reservation lifecycle:

approved -> started -> stopped -> costed
    |          |          |
    +------> expired/cancelled/failed
```

### Package Layout

The implementation moves to `src/conductor/` with these boundaries:

- `cli.py`: stable public commands, exit codes, and output selection.
- `schemas.py`: strict config, envelope, capability, event, and report models.
- `capabilities.py`: versioned provider/tool capability contracts.
- `operations.py`: canonical operation names and new-work classification.
- `identity.py`: validated RunContext and caller/child identity resolution.
- `policy.py`: pure policy evaluation against a transaction snapshot.
- `store.py`: SQLite schema, transactions, leases, reservations, and migration.
- `accounting.py`: normalized raw usage, pricing, estimates, and aggregation.
- `installation.py`: transactional install, repair, upgrade, and uninstall.
- `doctor.py`: static integrity checks and executable canaries.
- `providers/codex.py` and `providers/claude.py`: raw payload and response adapters.
- `hooks/`: thin, bounded entry points with provider-specific timeout behavior.
- `assets/`: packaged default configs, hook definitions, and policy templates.

Pydantic v2 validates external schemas and PlatformDirs selects operating-system
appropriate state/config paths. SQLite remains the concurrency primitive.

## Provider Capability Contract

Each supported provider version has a checked-in contract fixture containing:

- provider and CLI version range
- hook event names and trust/enablement visibility
- canonical and namespaced tool names
- raw tool-input schema for spawn, assign, follow-up, and message operations
- whether a child model can be selected and where that selector appears
- run, caller, child, task, and lifecycle correlation fields
- usage/token fields and their semantics
- decision-response schema

`conductor probe` captures a candidate contract without enabling enforcement.
`conductor capabilities validate` compares it with the installed contract.
Unknown or drifted contracts cannot enter routing/admission mode until reviewed.

The current callable Codex surface has no child `model` field. Its contract must
therefore use admission mode unless an independently verified provider mechanism
selects the child model. Conductor must not instruct an agent to emit fields that
the tool rejects.

## Strict Inputs

The v2 envelope is a single versioned object with exact fields, strict booleans,
bounded strings/lists, normalized relative owned paths, a declared operation
intent, and no unknown keys. Envelope extraction rejects duplicate tags, JSON
scalars, oversized payloads, invalid Unicode, unsupported schema versions, and
ambiguous multiple envelopes.

Tool names are canonicalized before classification. Namespaced forms map to the
same canonical operation. A follow-up or message is treated as new work only when
the normalized payload and envelope declare a new task; ordinary feedback remains
communication and does not consume a new reservation.

Malformed governed input returns a controlled validation denial. Internal
fail-open behavior, if enabled, applies only to explicitly classified runtime
outages and creates a visible degraded-mode record. Policy/configuration errors
never fail open.

## Identity And Run Context

SessionStart persists a strict RunContext containing provider, run ID, thread ID,
root model, model source, provider contract, mode, generation, start time,
heartbeat, and configuration digest. Identifiers are bounded URL-safe tokens and
never become unchecked filesystem paths.

Every decision resolves the caller from the RunContext and correlated lifecycle
records. Unknown callers or models follow the configured `deny`, `observe`, or
`degraded` policy. They never receive unrestricted approval and are never
silently assigned frontier authority.

Simultaneous root sessions use distinct databases or a shared database with
strict run keys; status/report default to the current run and never choose another
session merely because its directory is newer.

## Transactional Store

SQLite uses WAL mode, foreign keys, busy timeouts shorter than the provider hook
timeout, and explicit schema migrations. A single `BEGIN IMMEDIATE` transaction:

1. validates the current run lease and capability generation
2. expires abandoned reservations using configured TTLs
3. loads spend, reserved cost, tier counts, depth, and same-tier counts
4. evaluates policy
5. writes the decision and, when approved, a unique reservation
6. commits before returning approval

Pending and started reservations both count against concurrency and budget caps.
Provider correlation IDs and idempotency keys make duplicate start/stop/cost
events no-ops. Reordered events enter explicit recoverable states rather than
being matched to the oldest global pending task.

Active run leases protect state from garbage collection. Lock contention produces
a controlled degraded/deny decision before the provider timeout rather than an
unrecorded spawn.

## Policy

Policy is a pure function over validated input and a transaction snapshot. It
supports operation allowlists, task classes, risk triggers, depth, per-tier or
per-operation concurrency, reservations, budgets, same-tier limits, and provider
mode requirements.

Task classes must form a complete, non-overlapping ownership partition. All
numeric values are finite and range checked. Model ladders are permitted only in
routing mode. Admission mode can classify work and cap it, but cannot require an
unexpressible child model.

High-risk triggers use conservative configured policy and are clearly documented
as workflow controls, not a security sandbox.

## Accounting

The database stores immutable raw provider-usage records with provider, parser
version, source record identity, token dimensions, timestamps, and whether the
record is measured or estimated. Parser upgrades never rewrite raw data.

Pricing is valid only when every enabled model has complete finite rates for all
token dimensions the provider may emit, including cache reads and cache writes.
Partial pricing is rejected. Reports keep measured and estimated values separate.
Routing savings appear only in routing mode and state the assumptions used.

Duplicate or concurrent lifecycle events cannot double charge. Estimated fallback
cost has an explicit estimated baseline rather than a zero-token comparison.

## Transactional Installation

Install performs all capability, ownership, parsing, permissions, path, and
conflict checks before changing a file. It renders the entire desired install to
a same-filesystem staging area, records original hashes and backups, then commits
with atomic replacement and a rollback journal.

Managed files carry an installation manifest with exact hashes. User-modified or
foreign content is preserved and causes a conflict requiring `repair --adopt` or
explicit replacement. Marker substring checks are insufficient. Symlinks and
reparse points are rejected for managed destinations.

Install, upgrade, repair, and uninstall are idempotent. Failure after any staged
operation leaves either the complete previous install or the complete new install.
The packaged CLI never depends on its source checkout.

## Doctor And Operations

`conductor doctor` checks:

- config and database schema integrity
- complete pricing and policy partitions
- exact installed manifest and hashes
- hook definitions, matchers, commands, permissions, and packaged assets
- provider contract compatibility and current operating mode
- run identity and heartbeat visibility
- hook trust/enablement when the provider exposes it
- a safe allow canary and known-deny canary through the installed hook
- database reservation and idempotency behavior

Warnings affect the readiness verdict according to category. `doctor --strict`
has no warning-only escape hatch. `status` and `report` return nonzero on invalid
state and identify the requested run explicitly.

Garbage collection validates nonnegative retention, skips leased/active runs,
reports deletion failures, and supports dry run. Recovery commands resolve stale
reservations and interrupted installations without hand-editing state.

## Test Strategy

Pytest, pytest-cov, and Hypothesis are development dependencies. Required tests
include:

- pure policy truth tables for every rule and operating mode
- property/fuzz tests for envelopes, identifiers, paths, config, prices, and raw
  provider payloads
- golden contract tests captured from every supported provider version
- canonicalization tests for namespaced spawn, assign, follow-up, and messages
- 100-process contention tests proving concurrency and budget caps
- lifecycle permutations: reordered, duplicated, missing, expired, crash, and
  stop-before-start events
- exactly-once accounting under concurrent duplicate delivery
- multi-session isolation, leases, status/report selection, and safe GC
- filesystem containment, symlink/reparse, permissions, disk-full, and atomic
  replacement fault tests
- failure injection after every installation commit boundary
- clean wheel/sdist installation and full install/doctor/uninstall without a
  checkout
- real OS matrix tests on Linux, macOS, and Windows with Python 3.11-3.13
- opt-in live provider canaries that verify a known illegal operation is denied
  and recorded under the same run ID

The branch-coverage floor is 95% overall and 100% for schemas, identity, policy,
store transactions, path handling, accounting idempotency, and installation.

## Public Release

CI runs formatting, linting, typing, tests, coverage, package build and inspection,
dependency audit, provider contract validation, and clean-install smoke tests.
Release tags build one wheel/sdist set and publish those tested artifacts through
PyPI Trusted Publishing. GitHub Releases receive the same artifacts, checksums,
SBOM, and build provenance attestation.

The repository includes README, architecture and provider-contract guides,
configuration and CLI references, operational runbook, migration guide,
SECURITY.md, CONTRIBUTING.md, changelog, code of conduct, support policy, and
release checklist.

## Release Acceptance

codex-conductor v2 is release-ready only when:

- no P0/P1 or actionable P2 findings remain
- all OS/Python CI jobs and branch-coverage gates pass
- 100 concurrent decisions cannot exceed configured caps
- malformed governed input never becomes an unrestricted approval
- duplicate lifecycle events never duplicate cost
- current Codex and Claude contracts produce truthful operating modes
- wheel and sdist install and operate without repository access
- every installation fault point proves old-or-new atomicity
- `doctor --strict` proves an installed allow/deny canary
- public documentation contains no local paths, placeholder models/prices, or
  unsupported capability claims
- a release dry run produces inspectable artifacts without publishing

Actual pushing, tagging, GitHub settings, and PyPI publication require separate
user authorization.

## Explicit Non-Goals

- Conductor is not a billing authority or sandbox.
- Conductor does not invent child-model selection absent from a provider contract.
- Conductor does not silently govern unknown provider versions.
- Conductor does not merge its release cycle with Toolbelt.
- Conductor does not publish or enable hooks without explicit operator action.
