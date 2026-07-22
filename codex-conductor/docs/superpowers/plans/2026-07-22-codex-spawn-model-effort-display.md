# Codex Spawn Model and Effort Display Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show the committed lower-tier worker model, reasoning effort, and task in Codex CLI and VS Code when Conductor approves a savings-eligible spawn.

**Architecture:** Keep policy and reservation behavior unchanged. After an approved Codex spawn decision, derive a best-effort notice from the committed reservation plus the validated task envelope, then let the Codex provider decorate the normal allow response with the supported top-level `systemMessage`. A provider-base no-op keeps shared hook code provider-neutral and leaves Claude behavior unchanged.

**Tech Stack:** Python 3.11+, Pydantic v2 schemas, SQLite-backed Conductor store, pytest, Ruff, Pyright, Bash distribution smoke test.

---

## File structure

- Modify `src/conductor/providers/base.py`: define the provider-neutral, no-op decision-decoration seam.
- Modify `src/conductor/providers/codex.py`: emit a Codex `systemMessage` without mutating the permission payload.
- Modify `src/conductor/hooks/pre_tool_use.py`: select eligible decisions, read authoritative display data, and degrade safely.
- Modify `tests/test_hook_commands.py`: cover provider output, integrated routing display, filtering, and display failure behavior.
- Modify `tests/test_provider_claude.py`: prove the base decorator leaves Claude output unchanged.
- Modify `tests/e2e_smoke.sh`: exercise the installed Codex hook and assert the user-visible message.

### Task 1: Add the provider response-decoration seam

**Files:**
- Modify: `src/conductor/providers/base.py`
- Modify: `src/conductor/providers/codex.py`
- Test: `tests/test_hook_commands.py`
- Test: `tests/test_provider_claude.py`

- [ ] **Step 1: Write failing provider tests**

Extend `test_codex_provider_emits_current_pre_tool_use_decisions` with an exact decoration assertion:

```python
allowed = PROVIDER.emit_decision("approve", "allowed")
assert PROVIDER.decorate_decision(
    allowed, "Spawning gpt-5.6-terra · high · tests_ledger"
) == {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    },
    "systemMessage": "Spawning gpt-5.6-terra · high · tests_ledger",
}
assert allowed == {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
    }
}
```

Extend `test_task_payload_normalizes_alias_and_emits_claude_decision` to prove the provider-base default is a no-op:

```python
assert PROVIDER.decorate_decision(allowed, "Codex-only notice") == allowed
```

- [ ] **Step 2: Run the focused tests and verify they fail**

Run:

```sh
.venv/bin/python -m pytest tests/test_hook_commands.py::test_codex_provider_emits_current_pre_tool_use_decisions tests/test_provider_claude.py::test_task_payload_normalizes_alias_and_emits_claude_decision -q
```

Expected: both tests fail with `AttributeError` because `decorate_decision` does not exist.

- [ ] **Step 3: Add the provider-neutral no-op method**

Add this method to `Provider` immediately after `emit_decision`:

```python
def decorate_decision(self, response: dict, message: str) -> dict:
    """Add provider-specific user-visible metadata to a hook response."""
    return response
```

- [ ] **Step 4: Add Codex response decoration**

Add this override to `CodexProvider` immediately after `emit_decision`:

```python
def decorate_decision(self, response: dict, message: str) -> dict:
    return {**response, "systemMessage": message}
```

The shallow copy is intentional: callers can retain and reuse the original permission response, and existing denial serialization remains unchanged.

- [ ] **Step 5: Run the focused tests and verify they pass**

Run the Step 2 command again.

Expected: `2 passed`.

- [ ] **Step 6: Commit only Task 1 files**

```sh
git add codex-conductor/src/conductor/providers/base.py codex-conductor/src/conductor/providers/codex.py codex-conductor/tests/test_hook_commands.py codex-conductor/tests/test_provider_claude.py
git commit -m "feat: support codex hook display messages"
```

### Task 2: Decorate approved lower-tier spawn decisions

**Files:**
- Modify: `src/conductor/hooks/pre_tool_use.py`
- Test: `tests/test_hook_commands.py`

- [ ] **Step 1: Add a current-Codex test environment helper**

Add this constant and helper near the existing test environment setup:

```python
CURRENT_CODEX_CONFIG = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "conductor"
    / "assets"
    / "config"
    / "conductor.toml"
)


def _current_codex_environment(tmp_path: Path):
    home = tmp_path / "home"
    return home, set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(CURRENT_CODEX_CONFIG),
        CODEX_MODELS_CACHE=str(
            write_models_cache(
                tmp_path / "models.json", ["gpt-5.6-sol", "gpt-5.6-terra"]
            )
        ),
        CODEX_CONDUCTOR_SESSIONS_ROOT=str(tmp_path / "sessions"),
    )
```

- [ ] **Step 2: Write the failing integrated display test**

Add a test that starts a `gpt-5.6-sol`/`ultra` run, submits an implementation spawn for `gpt-5.6-terra`/`high`, and asserts the exact response:

```python
def test_codex_lower_tier_spawn_displays_committed_route(tmp_path: Path) -> None:
    from conductor.hooks.pre_tool_use import main as pre_tool_main
    from conductor.hooks.session_start import main as session_main

    _, old = _current_codex_environment(tmp_path)
    try:
        session = {
            "session_id": "display-run",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
        }
        assert _invoke(session_main, session)[0] == 0
        envelope = (
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"impl_worker",'
            '"task_class":"implementation","risk_triggers":[],'
            '"owned_paths":["src/worker.py"],'
            '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
        )
        rc, response = _invoke(
            pre_tool_main,
            {
                **session,
                "tool_use_id": "display-call",
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "impl_worker",
                    "message": envelope,
                    "fork_turns": "none",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                },
            },
        )
        assert rc == 0
        assert response == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            },
            "systemMessage": "Spawning gpt-5.6-terra · high · impl_worker",
        }
    finally:
        restore_env(old)
```

- [ ] **Step 3: Write filtering and failure tests**

Add this same-model test:

```python
def test_codex_same_model_spawn_does_not_display_route(tmp_path: Path) -> None:
    from conductor.hooks.pre_tool_use import main as pre_tool_main
    from conductor.hooks.session_start import main as session_main

    _, old = _current_codex_environment(tmp_path)
    try:
        session = {
            "session_id": "same-model-run",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
        }
        assert _invoke(session_main, session)[0] == 0
        envelope = (
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"risk_worker",'
            '"task_class":"high_risk","risk_triggers":[],'
            '"owned_paths":["src/risk.py"],'
            '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
        )
        _, response = _invoke(
            pre_tool_main,
            {
                **session,
                "tool_use_id": "same-model-call",
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "risk_worker",
                    "message": envelope,
                    "fork_turns": "none",
                    "model": "gpt-5.6-sol",
                    "reasoning_effort": "ultra",
                },
            },
        )
        assert response == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
    finally:
        restore_env(old)
```

Add this best-effort failure test. Install the monkeypatch only after
`session_main` has initialized the run:

```python
def test_codex_spawn_display_failure_preserves_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from conductor.errors import StateError
    from conductor.hooks.pre_tool_use import main as pre_tool_main
    from conductor.hooks.session_start import main as session_main
    from conductor.store import Store

    home, old = _current_codex_environment(tmp_path)
    try:
        session = {
            "session_id": "display-failure-run",
            "model": "gpt-5.6-sol",
            "reasoning_effort": "ultra",
        }
        assert _invoke(session_main, session)[0] == 0

        def fail_display_lookup(self, key, *, run_id=None):
            raise StateError("display lookup failed")

        monkeypatch.setattr(Store, "reservation", fail_display_lookup)
        envelope = (
            '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"impl_worker",'
            '"task_class":"implementation","risk_triggers":[],'
            '"owned_paths":["src/worker.py"],'
            '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
        )
        _, response = _invoke(
            pre_tool_main,
            {
                **session,
                "tool_use_id": "display-failure-call",
                "tool_name": "spawn_agent",
                "tool_input": {
                    "task_name": "impl_worker",
                    "message": envelope,
                    "fork_turns": "none",
                    "model": "gpt-5.6-terra",
                    "reasoning_effort": "high",
                },
            },
        )
        assert response == {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
            }
        }
        assert "display lookup failed" in (
            home / "state" / "errors.log"
        ).read_text(encoding="utf-8")
    finally:
        restore_env(old)
```

Existing exact-response tests continue to cover denied and ungoverned operations;
their lack of `systemMessage` is part of the regression contract.

- [ ] **Step 4: Run the new tests and verify they fail**

Run:

```sh
.venv/bin/python -m pytest tests/test_hook_commands.py -k 'lower_tier_spawn or same_model_spawn or display_lookup' -q
```

Expected: the lower-tier test lacks `systemMessage`; the failure diagnostic test also fails until best-effort handling exists.

- [ ] **Step 5: Add best-effort notice construction**

Import `Provider` as `ProviderName`, then add this helper above `main` in `pre_tool_use.py`:

```python
def _decorate_spawn_notice(
    provider,
    response: dict,
    payload: dict,
    decision: Decision,
    store: Store,
) -> dict:
    if not (
        provider.name == ProviderName.CODEX.value
        and decision.allowed
        and decision.mode is OperatingMode.ROUTING
        and decision.operation is OperationName.SPAWN
        and decision.savings_eligible
        and decision.reservation_id is not None
    ):
        return response
    try:
        reservation = store.reservation(decision.reservation_id)
        result = normalize_governed_payload({**payload, "provider": provider.name})
        operation = result.operation
        task_name = (
            operation.envelope.task_name
            if operation is not None and operation.envelope is not None
            else None
        )
        if (
            reservation.model is None
            or reservation.reasoning_effort is None
            or task_name is None
        ):
            raise StateError("approved spawn display metadata is incomplete")
        message = (
            f"Spawning {reservation.model} · "
            f"{reservation.reasoning_effort} · {task_name}"
        )
        return provider.decorate_decision(response, message)
    except BaseException as exc:
        log_error("pre_tool_use_notice", exc)
        return response
```

This catches display-only failures after an allow decision so user-interface enrichment can never convert approval into denial.

- [ ] **Step 6: Wire decoration into the successful main path**

Initialize the store before the caller branch:

```python
store: Store | None = None
```

Replace the direct successful `write_json(provider.emit_decision(...))` call with:

```python
response = provider.emit_decision(
    "approve" if decision.allowed else "block",
    f"{decision.rule}: {decision.message}",
)
if store is not None:
    response = _decorate_spawn_notice(provider, response, payload, decision, store)
write_json(response)
```

Do not alter either exception path or the early ungoverned-tool path.

- [ ] **Step 7: Run the focused hook tests**

Run:

```sh
.venv/bin/python -m pytest tests/test_hook_commands.py tests/test_provider_claude.py -q
```

Expected: all tests pass, including unchanged denial and Claude output assertions.

- [ ] **Step 8: Commit only Task 2 files**

```sh
git add codex-conductor/src/conductor/hooks/pre_tool_use.py codex-conductor/tests/test_hook_commands.py
git commit -m "feat: display lower-tier codex spawn route"
```

### Task 3: Verify the installed-hook path end to end

**Files:**
- Modify: `tests/e2e_smoke.sh`

- [ ] **Step 1: Change the Codex smoke spawn to a cheaper routed worker**

Replace the Codex `risk-task` spawn/lifecycle sequence with an `implementation-task` sequence that supplies:

```json
{
  "task_name": "implementation-task",
  "model": "gpt-5.6-terra",
  "reasoning_effort": "high"
}
```

Use a matching `implementation` task envelope. Assert the hook response contains both the unchanged allow decision and:

```python
assert result["systemMessage"] == "Spawning gpt-5.6-terra · high · implementation-task", result
```

Use `gpt-5.6-terra` in the subsequent `SubagentStart` and `SubagentStop` payloads, and change the report assertion from `tiers.frontier.completed == 1` to `tiers.standard.completed == 1`.

- [ ] **Step 2: Run the end-to-end smoke test**

Run:

```sh
make e2e PYTHON=.venv/bin/python
```

Expected final line: `codex-conductor e2e: PASS`.

- [ ] **Step 3: Commit the smoke-test coverage**

```sh
git add codex-conductor/tests/e2e_smoke.sh
git commit -m "test: cover codex spawn route display end to end"
```

### Task 4: Run complete verification

**Files:**
- Verify only; no planned source changes.

- [ ] **Step 1: Run formatting, lint, types, and unit tests**

Run:

```sh
make check PYTHON=.venv/bin/python
```

Expected: Ruff formatting and lint pass, Pyright reports zero errors, pytest meets the 90% branch-coverage threshold.

- [ ] **Step 2: Run distribution tests**

Run:

```sh
make dist-test PYTHON=.venv/bin/python
```

Expected: all distribution-marked tests pass.

- [ ] **Step 3: Re-run the package smoke test after all changes**

Run:

```sh
make e2e PYTHON=.venv/bin/python
```

Expected final line: `codex-conductor e2e: PASS`.

- [ ] **Step 4: Verify the working tree and commit scope**

Run from the monorepo root:

```sh
git status --short
git diff --check
```

Expected: only the pre-existing `install.py` and `test_install_transactional.py` changes remain uncommitted; no whitespace errors.

- [ ] **Step 5: Produce the required Conductor report**

Run from the monorepo root:

```sh
PYTHONPATH=codex-conductor/src codex-conductor/.venv/bin/python -m conductor.report --last
```

Expected: a bounded report for the most recent run, or an explicitly reported controlled no-run state.
