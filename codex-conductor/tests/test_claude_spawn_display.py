from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from conductor.config import config_digest, load_config
from conductor.errors import StateError
from conductor.hooks.pre_tool_use import (
    _spawn_notice,
    _spawn_notice_for,
    decide,
)
from conductor.hooks.pre_tool_use import main as pre_tool_main
from conductor.hooks.session_start import main as session_main
from conductor.identity import Caller
from conductor.providers.base import Provider
from conductor.providers.claude import PROVIDER as CLAUDE
from conductor.providers.codex import PROVIDER as CODEX
from conductor.schemas import Decision, OperatingMode, OperationName, RunContext
from conductor.store import Store
from tests.helpers import PROJECT_ROOT, restore_env, set_env
from tests.test_hook_commands import _invoke

CLAUDE_CONFIG = (
    PROJECT_ROOT / "src" / "conductor" / "assets" / "config" / "conductor.claude.toml"
)

ALLOW_RESPONSE = {
    "hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "allow",
        "permissionDecisionReason": "ALLOW: reservation approved",
    }
}


def _claude_spawn_payload(
    *,
    task_name: str = "tests_ledger",
    model: str = "sonnet",
    task_class: str = "tests",
    tool_use_id: str = "call-1",
    session_id: str = "root-run",
) -> dict:
    envelope = (
        '<CONDUCTOR_TASK>{"schema_version":1,'
        f'"task_name":"{task_name}","task_class":"{task_class}",'
        '"risk_triggers":[],"owned_paths":["src/example.py"],'
        '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
    )
    return {
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "tool_input": {
            "subagent_type": "general-purpose",
            "model": model,
            "description": task_name,
            "prompt": envelope + "\nDo the work.",
        },
    }


def _decision(**overrides) -> Decision:
    values = dict(
        decision_id="decision-1",
        allowed=True,
        rule="ALLOW",
        message="reservation approved",
        mode=OperatingMode.ROUTING,
        operation=OperationName.SPAWN,
        selected_model="claude-sonnet-5",
        reservation_estimate_usd=0.0,
        savings_eligible=True,
        reservation_id="reservation-1",
        created_at=datetime.now(UTC),
    )
    values.update(overrides)
    return Decision(**values)


class _FakeStore:
    def __init__(self, *, reservation=None, error: Exception | None = None) -> None:
        self._reservation = reservation
        self._error = error

    def reservation(self, key: str, *, run_id: str | None = None):
        if self._error is not None:
            raise self._error
        return self._reservation


def _reservation(
    *,
    model: str | None = "claude-sonnet-5",
    effort: str | None = None,
    task_id: str = "tests_ledger",
):
    return SimpleNamespace(model=model, reasoning_effort=effort, task_id=task_id)


# --- provider decoration seam -------------------------------------------------


def test_claude_provider_adds_top_level_system_message() -> None:
    notice = "Spawning claude-sonnet-5 · medium · tests_ledger"
    decorated = CLAUDE.decorate_spawn_notice(ALLOW_RESPONSE, notice)

    assert decorated["systemMessage"] == notice
    assert decorated["hookSpecificOutput"] == ALLOW_RESPONSE["hookSpecificOutput"]
    # The caller's response dict must not be mutated in place.
    assert "systemMessage" not in ALLOW_RESPONSE


def test_base_and_codex_providers_do_not_decorate() -> None:
    for provider in (Provider(), CODEX):
        result = provider.decorate_spawn_notice(dict(ALLOW_RESPONSE), "x")
        assert "systemMessage" not in result


# --- notice formatting --------------------------------------------------------


def test_spawn_notice_format_uses_middle_dot_separator() -> None:
    assert (
        _spawn_notice("claude-sonnet-5", "medium", "tests_ledger")
        == "Spawning claude-sonnet-5 · medium · tests_ledger"
    )


def test_spawn_notice_for_eligible_resolves_tier_effort() -> None:
    config = load_config(CLAUDE_CONFIG)
    store = _FakeStore(reservation=_reservation())

    notice = _spawn_notice_for(_decision(), store, "root-run", config)

    assert notice == "Spawning claude-sonnet-5 · medium · tests_ledger"


@pytest.mark.parametrize(
    "overrides",
    [
        {"allowed": False},
        {"operation": OperationName.OTHER},
        {"mode": OperatingMode.ADMISSION},
        {"mode": OperatingMode.OBSERVE},
        {"savings_eligible": False},
        {"reservation_id": None},
    ],
)
def test_spawn_notice_for_returns_none_when_ineligible(overrides) -> None:
    config = load_config(CLAUDE_CONFIG)
    store = _FakeStore(reservation=_reservation())

    assert _spawn_notice_for(_decision(**overrides), store, "root-run", config) is None


@pytest.mark.parametrize(
    "store",
    [
        _FakeStore(error=StateError("reservation not found")),
        _FakeStore(error=ValueError("bad id")),
        _FakeStore(reservation=_reservation(model=None)),
        _FakeStore(reservation=_reservation(model="ghost-model")),
    ],
)
def test_spawn_notice_for_is_best_effort(store) -> None:
    config = load_config(CLAUDE_CONFIG)

    # Never raises; simply yields no notice when a datum is missing.
    assert _spawn_notice_for(_decision(), store, "root-run", config) is None


# --- integration against a real committed reservation -------------------------


def _real_run(tmp_path: Path):
    config = load_config(CLAUDE_CONFIG)
    now = datetime.now(UTC)
    run = RunContext(
        provider="claude",
        run_id="root-run",
        thread_id="root-run",
        root_model="claude-opus-4-8",
        model_source="provider",
        provider_contract="claude-current",
        contract_digest="0" * 64,
        mode=OperatingMode.ROUTING,
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest=config_digest(config),
    )
    store = Store(tmp_path / "conductor.db")
    store.create_run(
        run.run_id,
        provider="claude",
        generation=1,
        mode="routing",
        context=run.model_dump(mode="json"),
    )
    caller = Caller("root-run", "root-run", 0, 0, "claude-opus-4-8", "")
    return config, run, store, caller


def test_approved_savings_eligible_claude_spawn_yields_notice(tmp_path: Path) -> None:
    config, run, store, caller = _real_run(tmp_path)

    decision = decide(
        _claude_spawn_payload(),
        config,
        store,
        run,
        caller,
        (0, 1, 2),
        provider_name="claude",
    )

    assert decision.allowed is True
    assert decision.savings_eligible is True
    assert decision.reservation_id is not None

    notice = _spawn_notice_for(decision, store, "root-run", config)
    assert notice == "Spawning claude-sonnet-5 · medium · tests_ledger"

    decorated = CLAUDE.decorate_spawn_notice(
        CLAUDE.emit_decision("approve", f"{decision.rule}: {decision.message}"),
        notice,
    )
    assert decorated["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert decorated["systemMessage"] == notice


def test_same_model_claude_spawn_has_no_notice(tmp_path: Path) -> None:
    config, run, store, caller = _real_run(tmp_path)

    # Requesting the caller's own model is not savings-eligible.
    decision = decide(
        _claude_spawn_payload(model="opus"),
        config,
        store,
        run,
        caller,
        (0, 1, 2),
        provider_name="claude",
    )

    assert decision.savings_eligible is False
    assert _spawn_notice_for(decision, store, "root-run", config) is None


# --- full hook entrypoint end to end ------------------------------------------


def test_pre_tool_use_main_claude_spawn_emits_system_message(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(CLAUDE_CONFIG),
    )
    try:
        session_rc, _ = _invoke(
            session_main,
            {"session_id": "root-run", "model": "claude-opus-4-8"},
            ["--provider", "claude"],
        )
        assert session_rc == 0

        rc, response = _invoke(
            pre_tool_main,
            _claude_spawn_payload(),
            ["--provider", "claude"],
        )
    finally:
        restore_env(old)

    assert rc == 0
    assert response["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert (
        response["systemMessage"] == "Spawning claude-sonnet-5 · medium · tests_ledger"
    )


def test_pre_tool_use_main_ungoverned_tool_has_no_notice(tmp_path: Path) -> None:
    home = tmp_path / "home"
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(CLAUDE_CONFIG),
    )
    try:
        _invoke(
            session_main,
            {"session_id": "root-run", "model": "claude-opus-4-8"},
            ["--provider", "claude"],
        )
        rc, response = _invoke(
            pre_tool_main,
            {
                "session_id": "root-run",
                "tool_name": "Bash",
                "tool_input": {"command": "true"},
            },
            ["--provider", "claude"],
        )
    finally:
        restore_env(old)

    assert rc == 0
    assert response["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert "systemMessage" not in response
