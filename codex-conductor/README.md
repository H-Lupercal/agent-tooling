# codex-conductor

Codex Conductor is a local admission, routing, and accounting guardrail for
developer agents launched by Codex CLI or Claude Code. It validates a bounded
task envelope, applies model-tier and risk policy, reserves concurrency and
budget atomically, and correlates lifecycle usage without a daemon or remote
service.

The public interface is the `conductor` command. State is stored in a local
SQLite WAL database. Conductor does not proxy model traffic, hold provider
credentials, or claim to be a sandbox or billing authority.

## Why use it?

Agent delegation becomes difficult to audit as soon as multiple tasks launch at
once. A plain prompt cannot atomically enforce a budget, prove which child a
usage record belongs to, or distinguish an unsupported provider feature from a
real routing decision. Conductor makes those states explicit:

- one strict task-envelope schema with bounded identifiers, paths, and checks;
- exact task-class ownership and high-risk escalation;
- atomic SQLite reservations for concurrency and run-budget limits;
- provider capability modes that never imply control the provider does not
  expose;
- PostToolUse child-ID linking followed by idempotent lifecycle and cost events;
- measured and estimated dollars reported separately;
- transactional installation with ownership hashes, rollback, repair, and
  conservative uninstall behavior.

## Requirements

- Python 3.11–3.13;
- Codex CLI 0.144.0–0.x and/or Claude Code 1.x–2.x with the hook events declared by the
  packaged capability contract;
- Linux, macOS, or Windows.

Provider payloads do change. `conductor doctor --strict` checks the installed CLI
version and local contract before you rely on enforcement.

## Install

Install the published package in an isolated environment, then preview its
filesystem changes:

```bash
python -m pip install codex-conductor
conductor install --dry-run
conductor install
conductor doctor
```

Claude Code uses its own home and policy file:

```bash
conductor install --provider claude --dry-run
conductor install --provider claude
conductor doctor --provider claude
```

The checkout launchers are thin aliases for the same installed command:

```bash
bash install.sh
bash uninstall.sh
```

PowerShell users can run `./install.ps1` and `./uninstall.ps1`.

Codex requires persisted trust for installed hook hashes. Open `/hooks`, review,
and approve the Conductor hooks in a trusted interactive session; do not use
`--dangerously-bypass-hook-trust` as an installation shortcut. Configure real
model prices, start a provider session, and then use `conductor doctor --strict`
as the enforcement-readiness gate. A fresh install intentionally reports
warnings for unverified prices and a not-yet-created run store.

Installation refuses a Codex configuration that disables user hooks through
`features.hooks = false`, the deprecated `features.codex_hooks = false`, or
`allow_managed_hooks_only = true`. Conductor cannot enforce policy while those
settings exclude `~/.codex/hooks.json`.

### Installer behavior

The installer stages every new file before committing and rolls the whole file
set back if any replacement fails. It rejects symbolic-link/reparse-point
targets, refuses foreign Codex hook files or conflicting unmanaged config
tables, and records SHA-256 ownership in
`~/.codex/conductor/managed-manifest.json` (or the Claude equivalent).

User-editable `conductor.toml` is seeded once and preserved on upgrades.
Provider settings and policy files are composite: foreign content is retained
while only marked Conductor blocks or hook entries are replaced. Fully managed
wrappers must match their recorded hash; restore them explicitly with:

```bash
conductor install --repair
```

Uninstall removes an owned file only while its hash still matches. A locally
modified managed file is preserved for manual inspection.

## Capability modes

Every run records one provider mode:

| Mode | What Conductor can truthfully do |
|---|---|
| `routing` | Validate and enforce the selected child model and effort, reserve capacity, and correlate lifecycle cost. |
| `admission` | Allow or deny a launch, but not assert that a cheaper child model was selected. |
| `observe` | Record observations; never claim a block or reservation was enforced. |
| `unsupported` | Deny new governed work because required identity or lifecycle capability is absent. |

The packaged Codex contract exposes child `model` and `reasoning_effort`
selectors and can operate in routing mode when its exact lifecycle link is
present. The orchestrator chooses both values from task context; Conductor
validates that request unchanged and never picks or rewrites a worker. A
`fork_turns="all"` spawn with neither override safely inherits both values.
Claude's existing `Task` model-routing behavior is unchanged in this release.

Non-governed tools and ordinary feedback messages bypass policy and state.
Unexpected failures deny new governed work safely; they do not block unrelated
developer operations.

## Task envelope

Every new governed task carries exactly one envelope in its prompt:

```text
<CONDUCTOR_TASK>{"schema_version":1,"task_name":"tests_ledger","task_class":"tests","risk_triggers":[],"owned_paths":["tests/test_ledger.py"],"acceptance_checks":["python -m pytest tests/test_ledger.py -q"],"new_task":true}</CONDUCTOR_TASK>
```

`task_class` must be one of the closed classes in the installed policy. Risk
triggers are also closed; unknown values are rejected rather than silently
ignored. Paths must be normalized relative POSIX paths with no `..` segments.
Follow-up and message tools count as new work only when their envelope sets
`new_task=true` and an `operation_intent` matching that tool.

Policy evaluation is ordered and stable. Important decision rules include:

- `MISSING_ENVELOPE`, `INVALID_ENVELOPE`, `ENVELOPE_OVERSIZED`;
- `DEPTH_LIMIT`, `CALLER_MAY_NOT_SPAWN`, `UNKNOWN_CALLER_MODEL`;
- `MISSING_MODEL_SELECTION`, `MISSING_EFFORT_SELECTION`;
- `MODEL_GENERATION_CEILING`, `MODEL_CAPABILITY_CEILING`, `EFFORT_CEILING`;
- `UNSUPPORTED_MODEL_EFFORT`, `FRONTIER_UNAVAILABLE`,
  `STRICTLY_CHEAPER_REQUIRED`, `SAME_TIER_LIMIT`;
- `MODEL_MISMATCH`, `ROUTING_REQUIRED`;
- `CONCURRENCY_CAP`, `BUDGET_CAP`, `BUDGET_CAP_WARNING`;
- `CONFIG_DRIFT`, `STALE_GENERATION`, `RUN_LEASE_EXPIRED`.

Decisions and reservations share one SQLite transaction. Concurrent hooks
cannot all observe stale capacity and oversubscribe a tier or budget.

## Configuration

Installed configuration lives at:

- Codex: `~/.codex/conductor/conductor.toml`
- Claude: `~/.claude/conductor/conductor.toml`

Tiers are ordered by policy preference. Their task classes must form an exact
partition, although compatibility models may have no recommended classes;
model IDs and tier names must be unique; relative cost weights must be
non-increasing. Explicit generation and capability ranks define authority
without guessing from model names. Legacy configuration remains loadable, but
cross-model Codex routing fails closed until missing generation authority is
made explicit. `enabled` is `always`, `auto`, or `never`.
Codex auto tiers are enabled only when the exact model slug is present in the
configured model cache.

The bundled Codex ladder starts with GPT-5.6 Sol, uses GPT-5.6 Terra for
everyday implementation, and recognizes GPT-5.6 Luna plus older models. The
caller is always the ceiling: a GPT-5.5 caller cannot spawn any GPT-5.6 worker,
and worker effort cannot exceed caller effort. This ceiling is transitive.

OpenAI's Codex pricing page says GPT-5.6 Sol has the
same ChatGPT credit rates as GPT-5.5 (125 input, 12.5 cached input, and 750
output credits per million tokens). That makes Sol the logical default when
both are permitted. Terra was listed at half those rates and described as the
starting point for work previously assigned to GPT-5.5. ChatGPT credits are
not API dollars, so bundled dollar prices remain zero and must be configured
from rates that actually apply to the account. See
[Codex pricing](https://developers.openai.com/codex/pricing) and
[Codex models](https://developers.openai.com/codex/models).

The bundled model IDs are examples for the supported contract, and bundled
prices deliberately start at zero. Configure rates that apply to your account
before enforcing dollar caps. If any enabled tier lacks a complete set of
nonzero input, cache-read, cache-write, and output rates, Conductor retains raw
usage but charges the explicit reservation estimate and labels it estimated.

The budget can be overridden for one process with
`CONDUCTOR_RUN_USD_CAP=<positive finite number>`.

## Lifecycle and accounting

The lifecycle path is deliberately strict:

1. PreToolUse reserves by the provider tool-call ID.
2. PostToolUse links that call ID to the returned child agent/thread ID.
3. SubagentStart and SubagentStop resolve the alias to the original reservation.
4. One canonical cost event and one immutable raw-usage event are recorded.

Retries reuse stable identifiers and cannot double-charge. If a provider omits
the correlation bridge, Conductor creates an explicit recoverable orphan instead
of guessing from launch order. Inspect or resolve those records with:

```bash
conductor recover --run <run-id> --json
conductor recover --run <run-id> --reservation <id> --outcome failed
```

An approved reservation that never starts expires after its configured TTL. A
started child never silently expires or releases capacity; after the TTL it is
flagged for explicit recovery and continues to hold concurrency and budget
until a terminal event or operator resolution arrives.

Transcript readers are bounded, reject symlink files, and prefer a child's own
transcript. Parent sidechain usage is not assigned to a child when exact
correlation is unavailable.

## Commands

```bash
conductor status --last --pretty
conductor status --run <run-id> --pretty
conductor report --last
conductor report --run <run-id> --json
conductor doctor --strict
conductor install --dry-run
conductor install --repair
conductor uninstall
conductor recover --run <run-id> --json
conductor gc --keep 20
conductor gc --older-than-days 30
conductor gc --keep 20 --execute
conductor migrate-v1 old.toml v2-candidate.toml
```

Invalid or missing run IDs return nonzero; there is no synthetic `none` run.
`gc` prints a lease-safe plan by default. It mutates state only with
`--execute`, and an active run lease is never eligible.

The report separates measured and estimated spend. Projected savings are shown
only for routing-eligible decisions and are labeled as a configured task-estimate
counterfactual. Admission and observe runs report savings as unavailable.

## Migrating from v1

Version 2 intentionally removes the JSONL event ledger, FIFO lifecycle matching,
legacy rule codes, and fail-open governed launches. It also changes the config
schema from `[[tier]]` plus flat prices to `[[tiers]]` and a nested
`[tiers.pricing]` table.

Migration is offline and never activates its output:

```bash
conductor migrate-v1 ~/.codex/conductor/old.toml ./v2-candidate.toml
```

Review the candidate, verify model IDs and rates, then place it deliberately.
The source is not modified and an existing destination is refused unless
`--overwrite` is explicit.

## Security model

Conductor is a cost and orchestration guardrail, not a process sandbox. Provider
hooks, the provider CLI, and the local user account remain trusted. An agent with
permission to alter its own hook configuration or database can bypass it.

Conductor does provide bounded parsers, strict schemas, fail-closed governed
operations, atomic state, no-follow installer checks, immutable raw usage,
manifest drift detection, and secret-free local error logging. Report security
issues privately as described in `SECURITY.md`.

## Development

From a source checkout:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
make check PYTHON=.venv/bin/python
make release-check PYTHON=.venv/bin/python
python -m compileall src/conductor
```

The release gate runs Ruff formatting and linting, Pyright, branch coverage,
100-process reservation stress tests, offline wheel and sdist installs, a full
installed-hook lifecycle smoke test, dependency auditing, SBOM generation,
artifact metadata checks, and cross-platform CI. See `CONTRIBUTING.md` and
`docs/RELEASING.md`.

## License

MIT
