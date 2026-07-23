# Claude Spawn Model and Effort Display

## Summary

Make lower-model Claude delegation visible to the user at spawn time. When
Conductor approves a routed Claude `Task` spawn that is eligible for savings
(the worker is genuinely cheaper than the caller), the Claude Code CLI and the
Claude VS Code extension must show one informational line naming the effective
worker model, its reasoning effort, and the task:

```text
Spawning claude-sonnet-5 · medium · tests_ledger
```

The display is **informational only**. It must not change whether work is
allowed, which model is selected, how reservations are accounted for, or how
Claude names the child agent. This is the Claude-provider counterpart of the
already-approved Codex design in
`docs/superpowers/specs/2026-07-22-codex-spawn-model-effort-display-design.md`,
which explicitly defers the Claude side to a separate change and requires it to
"verify Claude's current CLI, extension, hook response, and effective-effort
metadata rather than copying Codex response fields."

### Two verified facts that drive this design

1. **Display mechanism.** Claude Code's hook JSON output supports a top-level
   `systemMessage` field, documented as "Warning message shown to the user"
   (https://code.claude.com/docs/en/hooks, "JSON output" table). It is a
   universal field shown in both the CLI and the VS Code extension. By contrast,
   `hookSpecificOutput.permissionDecisionReason` is only reliably surfaced for
   `deny`/`ask` decisions, not for `allow`. Therefore the spawn notice is
   emitted as a **top-level `systemMessage`** added to the already-approved
   `allow` response; the permission decision and its reason are left unchanged.
   Claude's packaged capability contract
   (`src/conductor/assets/contracts/claude-current.json`) sets
   `decision_response_schema` to require only `hookSpecificOutput` and does not
   forbid extra top-level fields, so adding `systemMessage` is contract-valid.

2. **Effective reasoning effort.** Per-call reasoning effort is not observable
   on a Claude `Task` call, so `policy.py` records **NULL** effort in every
   Claude reservation (see the `effort_enforced = run.provider is Provider.CODEX`
   comment block in `src/conductor/policy.py`, and the CHANGELOG "Unreleased"
   entry). The effective effort for a Claude worker is therefore the configured
   `reasoning_effort` of the **tier that owns the selected model**, read from
   config. (Example: for the packaged Claude ladder in
   `src/conductor/assets/config/conductor.claude.toml`, `claude-sonnet-5` is the
   `standard` tier whose `reasoning_effort = "medium"`, so the notice reads
   `Spawning claude-sonnet-5 · medium · tests_ledger`. The `high` in the task's
   sample line is illustrative, not literal — the sample was given as an
   example.)

## Constraints & Assumptions

Constraints:

- Display is best-effort and must **never** become an admission gate. Any
  failure to build the notice yields the original, unmodified `allow` response.
- No change to routing, policy evaluation, ceilings, task classes, model
  selection, reservation schema, or accounting.
- No change to Codex provider output. The Codex provider keeps the default
  no-op decoration; its own systemMessage behavior is implemented by the
  separate Codex spec, not here.
- No change to denial responses or their `permissionDecisionReason` text.
- No change to how Claude names child agents/tasks.
- The separator between fields is exactly a space, U+00B7 MIDDLE DOT, space
  (`" · "`), matching the Codex design's `Spawning <model> · <effort> · <task>`.

Assumptions (all verified against the codebase, listed so the executor can
re-confirm):

- A committed Claude spawn reservation always has a non-null `model` (set to the
  routed target model in `_persist`) and a `task_id` equal to the validated
  envelope `task_name`. Reservation `reasoning_effort` is NULL for Claude.
- `Decision.savings_eligible` is Conductor's authoritative "worker is strictly
  cheaper than caller in routing mode" signal (`_savings_eligible` in
  `policy.py`), and is the correct gate for "lower-model subagent."
- Both the CLI and VS Code render top-level `systemMessage`; this repository
  produces only the hook JSON, so no separate CLI/extension code exists or is
  changed. Satisfying "both clients" means emitting the field correctly.

Open questions: none. The effort-source and gating decisions above are
determined by existing code and the approved sibling design; the sample line's
`high` was explicitly labeled an example by the requester.

## Affected Files

- **Modify** `src/conductor/providers/base.py`
  Add a default no-op decoration seam `decorate_spawn_notice`.
- **Modify** `src/conductor/providers/claude.py`
  Override `decorate_spawn_notice` to add a top-level `systemMessage`.
- **Modify** `src/conductor/hooks/pre_tool_use.py`
  Build the notice for approved, savings-eligible, routing-mode spawns and ask
  the provider to decorate the `allow` response. Best-effort with bounded
  diagnostics.
- **Modify** `CHANGELOG.md`
  Add an "Unreleased" → "Added" entry.
- **Create** `tests/test_claude_spawn_display.py`
  Unit + integration tests (see Test Plan).
- **Modify** `tests/test_hook_commands.py`
  Add one negative assertion that Codex `allow` output remains byte-for-byte
  unchanged (no `systemMessage`). (May instead live in the new test file; place
  wherever the executor prefers, but the assertion is required.)

No files are deleted.

## Public Interfaces

### `src/conductor/providers/base.py` — new method on `Provider`

```python
def decorate_spawn_notice(self, response: dict, notice: str) -> dict:
    """Return an approved allow response enriched with an informational spawn
    notice. Default is a no-op: providers that can surface a cross-client
    message override this. Must not mutate ``response`` in place and must not
    alter the permission decision."""
    return response
```

### `src/conductor/providers/claude.py` — override on `ClaudeProvider`

```python
def decorate_spawn_notice(self, response: dict, notice: str) -> dict:
    decorated = dict(response)
    decorated["systemMessage"] = notice
    return decorated
```

Notes:
- `dict(response)` is a shallow copy; do not mutate the caller's dict.
- Do not touch `response["hookSpecificOutput"]`.

### `src/conductor/hooks/pre_tool_use.py` — new module-level helpers

```python
def _spawn_notice(model: str, effort: str, task: str) -> str:
    return f"Spawning {model} · {effort} · {task}"


def _spawn_notice_for(
    decision: Decision,
    store: Store,
    run_id: str,
    config: ConductorConfig,
) -> str | None:
    """Return the spawn-notice text for a display-eligible decision, else None.

    Eligible = approved AND operation is SPAWN AND mode is ROUTING AND
    savings_eligible AND a reservation id is present AND the committed
    reservation still yields a model whose tier effort is resolvable.
    Any missing datum returns None (no notice); this function never raises."""
    if not (
        decision.allowed
        and decision.operation is OperationName.SPAWN
        and decision.mode is OperatingMode.ROUTING
        and decision.savings_eligible
        and decision.reservation_id is not None
    ):
        return None
    try:
        reservation = store.reservation(decision.reservation_id, run_id=run_id)
    except (StateError, ValueError) as exc:
        log_error("pre_tool_use", exc)
        return None
    model = reservation.model
    if not model:
        return None
    effort = reservation.reasoning_effort or _tier_effort(config, model)
    if effort is None:
        return None
    return _spawn_notice(model, effort, reservation.task_id)


def _tier_effort(config: ConductorConfig, model: str) -> str | None:
    tier = config.tier_for_model(model)
    return tier.reasoning_effort if tier is not None else None
```

`Decision`, `OperationName`, `OperatingMode`, `StateError`, `log_error`,
`store_path`, and `Store` are already imported in `pre_tool_use.py`;
`ConductorConfig` is already imported from `conductor.config`. No new imports
are required except `Reservation` is **not** needed (the object is used
duck-typed via attributes).

### Integration point in `main()`

`main()` currently ends the success path with a single
`write_json(provider.emit_decision(...))` shared by both the
`caller.run_id is None` branch and the `else` branch. Refactor so the response
is built per branch and enriched only where a live `store`/`run` exists:

- In the `if caller.run_id is None:` branch (no store): build
  `response = provider.emit_decision("block" if not decision.allowed else "approve", f"{decision.rule}: {decision.message}")`
  with no enrichment (decision here is always a fail-closed ephemeral, never a
  savings-eligible spawn).
- In the `else:` branch (store and `run` exist): after `decision = decide(...)`,
  build the base response the same way, then:

  ```python
  if decision.allowed:
      notice = _spawn_notice_for(decision, store, caller.run_id, config)
      if notice is not None:
          response = provider.decorate_spawn_notice(response, notice)
  ```

- Call `write_json(response)` once after the branches.

The `except (ConductorError, ...)` and `except BaseException` fail-closed paths
are unchanged: they never enrich.

No env vars, API routes, or CLI flags change.

## Implementation Plan

Ordered; steps 1–2 are independent and may run in parallel, step 3 depends on
both, steps 4–5 depend on step 3.

1. Add `decorate_spawn_notice` no-op to `providers/base.py`.
2. Add `decorate_spawn_notice` override to `providers/claude.py`.
3. Add `_spawn_notice`, `_spawn_notice_for`, `_tier_effort` to
   `hooks/pre_tool_use.py` and wire enrichment into `main()`'s success path as
   specified in "Integration point in `main()`".
4. Add `tests/test_claude_spawn_display.py` and the Codex-unchanged assertion.
5. Add the CHANGELOG entry.

## Error Handling

| Failure mode | Behavior |
| --- | --- |
| Decision not eligible (denied, non-spawn, non-routing, not savings-eligible, no reservation id) | `_spawn_notice_for` returns `None`; original `allow`/`block` response emitted unchanged. |
| `store.reservation(...)` raises `StateError`/`ValueError` (reservation missing/expired/invalid id) | Caught; `log_error("pre_tool_use", exc)` records a bounded diagnostic; returns `None`; original `allow` response emitted. Spawn is **not** denied or retried. |
| Committed reservation has null/empty `model` | Returns `None`; original `allow` response emitted. |
| Tier for model not found in config (effort unresolvable) | Returns `None`; original `allow` response emitted. |
| Any exception inside `main()` before/around enrichment | Existing fail-closed `except` blocks apply unchanged (governed work denied safely). Enrichment code is confined to the success path and its own `try/except`, so it cannot convert an approval into a denial. |
| Non-Claude provider (Codex) | `decorate_spawn_notice` is the base no-op; output is byte-for-byte unchanged. |

## Test Plan

Framework: pytest (existing). All tests mock at the store/provider boundary and
hit no live services. Use `tests/helpers.py` (`DEFAULT_CONFIG`, `write_config`,
`set_env`/`restore_env`) and, for Claude, the packaged Claude config at
`src/conductor/assets/config/conductor.claude.toml` and contract
`claude-current` (mirror the setup in `tests/test_provider_claude.py`).

New file `tests/test_claude_spawn_display.py`:

1. **Provider unit — Claude decorates.**
   `ClaudeProvider().decorate_spawn_notice({"hookSpecificOutput": {...allow...}}, "Spawning claude-sonnet-5 · medium · tests_ledger")`
   returns a dict where `systemMessage == "Spawning claude-sonnet-5 · medium · tests_ledger"`,
   `hookSpecificOutput.permissionDecision == "allow"` unchanged, and the input
   dict is not mutated (assert original has no `systemMessage`).

2. **Provider unit — base/Codex no-op.**
   `Provider().decorate_spawn_notice(resp, "x") is resp`-equivalent (returns
   response with no `systemMessage`); `CodexProvider().decorate_spawn_notice`
   likewise adds nothing.

3. **`_spawn_notice` format.** Exact string:
   `_spawn_notice("claude-sonnet-5", "medium", "tests_ledger") == "Spawning claude-sonnet-5 · medium · tests_ledger"`.

4. **`_spawn_notice_for` — eligible.** Build a fake store object exposing
   `reservation(key, run_id=...)` that returns an object with
   `model="claude-sonnet-5"`, `reasoning_effort=None`, `task_id="tests_ledger"`,
   and a `Decision` with `allowed=True`, `operation=OperationName.SPAWN`,
   `mode=OperatingMode.ROUTING`, `savings_eligible=True`,
   `reservation_id="reservation-abc"`. With the packaged Claude config loaded,
   assert the result is `"Spawning claude-sonnet-5 · medium · tests_ledger"`
   (effort resolved from the `standard` tier).

5. **`_spawn_notice_for` — each disqualifier returns None** (parametrized):
   `allowed=False`; `operation=OperationName.OTHER`; `mode=OperatingMode.ADMISSION`;
   `mode=OperatingMode.OBSERVE`; `savings_eligible=False`; `reservation_id=None`.

6. **`_spawn_notice_for` — best-effort failures return None:**
   (a) fake store `reservation` raises `StateError` → None (and does not raise);
   (b) reservation `model=None` → None;
   (c) reservation model not in config ladder (e.g. `"unknown-model"`) → None.

7. **Integration via `pre_tool_use.main` — Claude approved savings-eligible
   spawn shows the notice.** Set up a Claude environment (Claude config +
   contract) and a routing run whose caller/root model is `claude-opus-4-8`,
   following `tests/test_provider_claude.py`'s run/store construction (create the
   run with a `RunContext` whose `provider="claude"`, `mode="routing"`,
   `provider_contract="claude-current"`, and a `contract_digest` matching
   `contract_digest(load_contract("claude-current"))`, and matching
   `config_digest`). Invoke `main(["--provider", "claude"])` (using the
   `_invoke` helper from `tests/test_hook_commands.py`) with a `Task` payload
   whose `session_id` is the run id, a distinct `agent_id`/`tool_use_id`
   correlation, `model: "sonnet"`, and a valid `CONDUCTOR_TASK` envelope with
   `task_name: "tests_ledger"`, `task_class: "tests"`. Assert the response has
   `hookSpecificOutput.permissionDecision == "allow"` and
   `systemMessage == "Spawning claude-sonnet-5 · medium · tests_ledger"`.

8. **Integration — Claude denied spawn shows no notice.** Same setup but choose
   a model that fails a ceiling (e.g. route `opus` caller is fine; instead make
   the caller `claude-sonnet-5` requesting `claude-opus-4-8`, triggering a
   capability/generation ceiling deny). Assert `permissionDecision == "deny"`
   and `"systemMessage" not in response`.

9. **Integration — non-spawn / ungoverned tool shows no notice.** Invoke with a
   `Bash`/`shell` tool payload; assert `allow` and no `systemMessage`.

10. **Codex unchanged.** In `tests/test_hook_commands.py` (or the new file),
    assert a Codex approved savings-eligible spawn `allow` response equals
    exactly `{"hookSpecificOutput": {"hookEventName": "PreToolUse",
    "permissionDecision": "allow"}}` with no `systemMessage` (the base no-op is
    in effect for Codex in this change).

Mocks/fixtures: reuse existing `pre_tool_use_spawn.json` and Claude payload
builders where convenient; a lightweight hand-rolled fake store (a class with a
`reservation` method) is sufficient for the `_spawn_notice_for` unit tests — no
real SQLite needed for those.

## Acceptance Criteria

- [ ] `providers/base.py` defines `decorate_spawn_notice` as a no-op returning
      the response unchanged and not mutating it.
- [ ] `providers/claude.py` overrides `decorate_spawn_notice` to add a top-level
      `systemMessage` equal to the notice, leaving `hookSpecificOutput` intact
      and not mutating the input dict.
- [ ] `hooks/pre_tool_use.py` adds `_spawn_notice`, `_spawn_notice_for`,
      `_tier_effort`; `main()` enriches only approved, `SPAWN`, `ROUTING`,
      `savings_eligible` decisions with a resolvable reservation, and only on
      the live-store success path.
- [ ] The notice format is exactly `Spawning <model> · <effort> · <task>` with
      `" · "` separators; `<effort>` for Claude comes from the selected
      model's tier `reasoning_effort`.
- [ ] Enrichment is best-effort: any missing/failed datum yields the original
      `allow` response and a bounded `log_error` diagnostic; no approval is ever
      converted to a denial by display code.
- [ ] Codex `allow` output is byte-for-byte unchanged (no `systemMessage`).
- [ ] Denial responses and their `permissionDecisionReason` are unchanged.
- [ ] New tests in `tests/test_claude_spawn_display.py` cover: Claude decoration,
      base/Codex no-op, notice format, eligible notice, every disqualifier,
      best-effort failure paths, and the three integration scenarios; plus the
      Codex-unchanged assertion.
- [ ] Repository gates pass:
      `make check PYTHON=.venv/bin/python`,
      `make dist-test PYTHON=.venv/bin/python`,
      `make e2e PYTHON=.venv/bin/python`.
- [ ] `CHANGELOG.md` "Unreleased" → "Added" documents the Claude spawn display.
