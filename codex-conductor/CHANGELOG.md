# Changelog

All notable changes to codex-conductor are documented here. The format follows
Keep a Changelog, and the project uses Semantic Versioning.

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
