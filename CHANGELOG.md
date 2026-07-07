# Changelog

All notable changes to codex-conductor are documented here. The format follows
Keep a Changelog, and the project uses Semantic Versioning.

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
