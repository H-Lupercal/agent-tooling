# Changelog

All notable changes to codex-conductor are documented here. The format follows
Keep a Changelog, and the project uses Semantic Versioning.

## [Unreleased]

### Added

- Add GPT-5.6 Sol, Terra, and Luna to the Codex ladder with explicit model
  generation, capability, and six-level reasoning-effort ceilings.
- Persist accepted worker effort through an additive SQLite migration and
  reject Codex descendants that exceed any caller authority dimension.

### Changed

- Let the Codex orchestrator choose worker model and effort; Conductor now
  validates that exact choice instead of selecting a task-class target.
- Recognize GPT-5.5 and older models without allowing them to upgrade into the
  GPT-5.6 generation. Equal-cost cross-model work is not counted as savings.
- Give the Claude orchestrator model-led routing: it chooses the worker model
  and Conductor validates only the model generation and capability ceiling,
  replacing the prior rule that the task class dictates the model. An omitted
  `model` inherits the caller's model. Reasoning effort is not observable per
  Claude `Task` call, so it is left unenforced and every Claude reservation
  records a null effort.

### Fixed

- Generate Codex hook configuration with supported top-level metadata and
  migrate legacy Conductor-owned hook files safely.
- Accept current Codex `session_id`, `tool_use_id`, and `agent_id` lifecycle
  fields, and exercise those fields in the installed-package end-to-end test.
- Emit supported Codex `PreToolUse` permission decisions instead of the legacy
  `decision: approve` shape that current Codex treats as a failed hook.
- Refuse installation and fail doctor checks when Codex configuration disables
  user hooks, instead of reporting an enforcement-ready installation.
- Declare Codex CLI 0.144.0 as the minimum verified hook-compatible release and
  align the packaged capability contract, fixtures, probe report, and README.

## [2.0.0] - 2026-07-09

### Added

- Strict Pydantic contracts for configuration, task envelopes, provider
  capabilities, run identity, decisions, reservations, lifecycle events, raw
  usage, and reports.
- SQLite WAL state with atomic concurrency/budget reservations, leases,
  generations, idempotency keys, lifecycle correlation aliases, recovery, and
  lease-safe garbage collection.
- Explicit `routing`, `admission`, `observe`, and `unsupported` modes.
- PostToolUse correlation bridging and exactly-once measured/estimated costing.
- Transactional, no-follow installation with ownership manifests, rollback,
  `--repair`, conservative uninstall, and dry-run support for Codex and Claude.
- `recover` and offline `migrate-v1` commands, strict doctor canaries, isolated
  wheel/sdist tests, cross-platform locked CI, CodeQL, installed-hook end-to-end
  coverage, SBOM generation, artifact checksums, attestations, GitHub Releases,
  and PyPI trusted publishing.

### Changed

- Governed operations fail closed when identity, capability, configuration, or
  state cannot be established. Unrelated tools and ordinary feedback still
  bypass policy.
- Reports separate measured and estimated spend and expose projected savings
  only for routing-eligible decisions.
- The config schema now uses `[[tiers]]` with nested `[tiers.pricing]` tables and
  exact task-class ownership.
- Garbage collection is plan-only unless `--execute` is explicit.
- Admission mode permits only the bounded root same-tier exception when strict
  cheaper-child policy is enabled; it never reports that a model was selected.
- Started work that exceeds its TTL remains capacity/budget committed and is
  surfaced for explicit recovery instead of silently expiring.
- Claude uninstall removes only Conductor-owned hook entries and preserves every
  unrelated hook event, including intentionally empty lists.

### Removed

- JSONL runtime ledgers, FIFO child matching, legacy R1–R10 policy evaluation,
  fabricated unknown-model callers, fail-open governed launches, and the
  advisory file-lock implementation.

### Security

- Bounded UTF-8/JSON parsing, normalized owned paths, safe transcript reads,
  immutable raw usage, contract/config digests, symlink/reparse rejection, and
  managed-file drift detection are enforced by default.
- Enforced work requires an exact provider correlation ID; lifecycle identifier
  reuse with different content, oversized hook input, caller/child confusion,
  and incomplete enabled-tier pricing all fail closed.

## [1.0.0] - 2026-07-07

Initial stable release.

### Added
- Cost-aware subagent orchestration for Codex and Claude Code via native hooks
  (PreToolUse, SubagentStart, SubagentStop, SessionStart).
- Tiered model ladder with per-tier concurrency caps, task-class routing, a depth
  limit, strictly-cheaper enforcement, and a delegated-spawn budget (rules
  R1-R10).
- Per-run JSONL ledger with cost recording and a savings report.
- Provider-aware `status`, `report`, and `doctor` commands
  (`--provider {codex,claude}`).
- `gc` command to prune old run-state ledgers.
- `conductor` console entry point (editable install: `pip install -e .`).
- Config-integrity validation: tiers must be strictly decreasing in
  relative_cost_weight.
- MIT license.

### Fixed
- The Claude delegation policy now inspects the Claude ledger via
  `--provider claude` instead of defaulting to the Codex home.

### Removed
- The unused `policy.retry_same_tier_max` config knob.
