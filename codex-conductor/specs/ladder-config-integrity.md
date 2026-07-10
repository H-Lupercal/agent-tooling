# Ladder Config Integrity

## Summary

Two small correctness/honesty fixes to the conductor config layer, bundled
because both harden `conductor/config.py` and its shipped/test configs:

1. **Enforce the tier cost-ordering invariant.** The decision engine treats a
   higher list index as "cheaper" (see `require_strictly_cheaper` handling in
   `conductor/hooks/pre_tool_use.py`, which compares tier *indices*, not prices).
   Nothing validates that tiers are actually listed strongest→cheapest. If a
   config author reorders `[[tier]]` blocks, enforcement silently inverts with no
   error. Add a validation rule that rejects any config whose
   `relative_cost_weight` is not strictly decreasing down the tier list.

2. **Remove the dead `policy.retry_same_tier_max` knob.** It is loaded into the
   `Policy` dataclass and read from TOML but is referenced by no decision logic
   anywhere in the codebase. A config key that does nothing is a lie; remove it.
   (Implementing a real "retry the same tier on failure" feature is out of scope
   and would reintroduce a differently-shaped field deliberately — see Open
   Questions.)

## Constraints & Assumptions

- **Scope is config integrity only.** No behavior change to spawning, budgeting,
  pricing, reporting, or the providers beyond the two items above.
- **Ordering rule applies to ALL tiers in list order**, not just enabled ones,
  because the engine indexes across the full `ladder.tiers` tuple regardless of
  `enabled`.
- **The rule is strictly decreasing** (`current < previous`), not
  non-increasing: two tiers with equal weight would break the "child must be
  strictly cheaper than parent" guarantee, so equal adjacent weights are invalid.
- **Only `relative_cost_weight` is validated for ordering**, NOT `est_task_usd`.
  A cheaper-per-token tier can legitimately carry a higher per-task estimate
  because it is expected to burn more tokens, so `est_task_usd` must not be
  constrained.
- **Backward compatibility for `retry_same_tier_max`:** any already-installed
  user config (e.g. `~/.codex/conductor/conductor.toml`) may still contain
  `retry_same_tier_max = 1`. After this change, `load_ladder` never reads that
  key, and `tomllib` simply leaves the unknown key in the parsed dict, so stale
  configs continue to load without error. No migration step is required.
- The shipped default configs and all test fixtures already list tiers in
  strictly-decreasing `relative_cost_weight` order (100, 25, 6, 2 for Codex; 100,
  25, 6 for Claude), so the new rule does not reject any current config.

**Open Questions (non-blocking):**
- None required to implement. Design note for a future spec: a real same-tier
  retry-on-failure feature would need failure detection from the ledger and a
  retry counter keyed on `task_name`; that is a separate feature, not this one.

## Affected Files

Modify:
- `conductor/config.py` — remove `retry_same_tier_max` from the `Policy`
  dataclass and from the `Policy(...)` construction in `load_ladder`; add the
  ordering-validation rule to `_validate`.
- `config/conductor.toml` — remove the `retry_same_tier_max = 1` line from the
  `[policy]` table.
- `config/conductor.claude.toml` — remove the `retry_same_tier_max = 1` line from
  the `[policy]` table.
- `tests/helpers.py` — remove the `retry_same_tier_max = 1` line from the
  `[policy]` table inside `DEFAULT_CONFIG`.
- `tests/test_provider_claude.py` — remove the `retry_same_tier_max = 1` line from
  the inline `[policy]` table (currently near line 21).
- `tests/test_config.py` — add one case to the `cases` list in
  `test_validation_errors_have_exact_messages` covering the new ordering rule.

Create / delete: none.

Authoritative locator for every `retry_same_tier_max` occurrence (all must be
gone afterward except this spec):

```bash
grep -rn "retry_same_tier_max" . --include=*.py --include=*.toml | grep -v pycache
```

## Public Interfaces

No public signatures change. For clarity:

- `Policy` dataclass loses one field. New definition (in `conductor/config.py`):

  ```python
  @dataclass(frozen=True)
  class Policy:
      max_depth: int
      require_strictly_cheaper: bool
      same_tier_spawns_from_root_max: int
  ```

- `load_ladder(path: Path | None = None) -> Ladder` — unchanged signature; the
  `Policy(...)` call inside it drops the `retry_same_tier_max=...` argument.

- `_validate(ladder: Ladder) -> None` — unchanged signature; gains one rule.

- New `ConfigError` message string (exact, regex-safe — no parentheses or other
  regex metacharacters):

  ```text
  tier <name>: relative_cost_weight must be lower than tier <previous_name>
  ```

## Implementation Plan

Steps 1–2 touch `conductor/config.py`; the rest are independent and may be done
in any order / in parallel.

1. **Remove the field from `Policy`.** Delete the line
   `retry_same_tier_max: int` from the `Policy` dataclass.

2. **Remove the loader argument.** In `load_ladder`, delete the line
   `retry_same_tier_max=int(policy_data.get("retry_same_tier_max", 1)),` from the
   `Policy(...)` construction.

3. **Add the ordering rule to `_validate`.** Insert the following block
   immediately after the existing `for tier in ladder.tiers:` loop completes (the
   loop that populates `seen_names`/`seen_models`/`assigned`) and before the
   final `if not any(tier.enabled != "never" ...)` check:

   ```python
   for previous, current in zip(ladder.tiers, ladder.tiers[1:]):
       if current.relative_cost_weight >= previous.relative_cost_weight:
           raise ConfigError(
               f"tier {current.name}: relative_cost_weight must be lower than tier {previous.name}"
           )
   ```

4. **Strip `retry_same_tier_max` from the shipped configs.** Remove the
   `retry_same_tier_max = 1` line from the `[policy]` table in both
   `config/conductor.toml` and `config/conductor.claude.toml`.

5. **Strip it from the test fixtures.** Remove the `retry_same_tier_max = 1` line
   from the `[policy]` table in `DEFAULT_CONFIG` (`tests/helpers.py`) and from the
   inline `[policy]` table in `tests/test_provider_claude.py`.

6. **Add the new validation test case.** In `tests/test_config.py`, inside
   `test_validation_errors_have_exact_messages`, append this tuple to the `cases`
   list:

   ```python
   ("relative_cost_weight = 6", "relative_cost_weight = 30", "tier mini: relative_cost_weight must be lower than tier standard"),
   ```

   This swaps `mini`'s weight from 6 to 30, producing the sequence 100, 25, 30, 2,
   which violates strict-decrease at the `standard`→`mini` boundary and must raise
   the exact message.

## Error Handling

- Non-strictly-decreasing `relative_cost_weight` between any adjacent pair of
  tiers (list order) raises `ConfigError` with the message specified in Public
  Interfaces. The first offending pair encountered (top-down) determines the
  message; validation stops at the first failure, consistent with every other
  rule in `_validate`.
- A config with 0 or 1 tier trivially passes the ordering rule (`zip` yields no
  pairs); the pre-existing "at least one tier must be enabled" rule still governs
  the empty case.
- Unknown `retry_same_tier_max` keys in pre-existing installed TOML are ignored
  by `load_ladder` (no read, no error) — no failure mode introduced.

## Test Plan

- **New negative test** (item 6): asserts `load_ladder` raises `ConfigError`
  matching `tier mini: relative_cost_weight must be lower than tier standard` when
  `mini`'s weight exceeds `standard`'s. Uses the existing
  `assertRaisesRegex(ConfigError, message)` pattern; the message is regex-safe.
- **Regression:** the existing `test_valid_default_loads_and_auto_tiers_follow_models_cache`
  must still pass, proving the default (strictly decreasing) config is accepted
  after adding the rule.
- **Fixture hygiene:** removing `retry_same_tier_max` from `DEFAULT_CONFIG` and
  the Claude inline config must not affect any assertion (no test reads that
  field). Verified by running the full suite.
- No new fixtures, mocks, or live services required. All tests remain offline and
  use `tempfile.TemporaryDirectory` + `write_config`, as the suite already does.

Run:

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall conductor
```

## Acceptance Criteria

- [ ] `grep -rn "retry_same_tier_max" . --include=*.py --include=*.toml | grep -v pycache`
      returns **only** matches inside `specs/ladder-config-integrity.md` (zero in
      `conductor/`, `config/`, or `tests/`).
- [ ] `Policy` has exactly three fields: `max_depth`,
      `require_strictly_cheaper`, `same_tier_spawns_from_root_max`.
- [ ] Loading a config whose `[[tier]]` blocks are strictly decreasing in
      `relative_cost_weight` succeeds unchanged.
- [ ] Loading a config where any tier's `relative_cost_weight` is `>=` the
      previous tier's raises `ConfigError` with message
      `tier <name>: relative_cost_weight must be lower than tier <previous_name>`.
- [ ] `python3 -m unittest discover -s tests -v` passes with the same or a
      greater test count than before (currently 37), including the new case.
- [ ] `python3 -m compileall conductor` succeeds.
- [ ] No changes to spawning, budget, pricing, reporting, provider, installer, or
      README behavior.
