from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from tests.test_executor_v2 import NOW, _fixture
from toolbelt.executor import Executor
from toolbelt.state import StateStore


@pytest.mark.parametrize(
    "arguments",
    [
        {"command_timeout": 0},
        {"max_output_bytes": 10},
        {"lock_timeout": 0},
        {"fault_after": 0},
    ],
)
def test_executor_rejects_unsafe_bounds(arguments: dict) -> None:
    with pytest.raises(ValueError):
        Executor(**arguments)


@pytest.mark.parametrize("fail_after", range(1, 8))
def test_failure_at_every_boundary_restores_original_state(tmp_path: Path, fail_after: int) -> None:
    plan, catalog, capabilities, state, _ = _fixture(tmp_path)

    result = Executor(fault_after=fail_after).apply(
        plan,
        tmp_path,
        catalog,
        capabilities,
        now=NOW,
    )

    assert result.state in {"rolled_back", "rollback_failed"}
    if result.state == "rolled_back":
        assert not state.exists()
        assert not (tmp_path / ".toolbelt" / "lock.toml").exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX process liveness assertion")
def test_timeout_kills_child_group_and_rolls_back(tmp_path: Path) -> None:
    plan, catalog, capabilities, state, pid_file = _fixture(tmp_path, sleeps=True)

    started = time.monotonic()
    result = Executor(command_timeout=0.3).apply(
        plan,
        tmp_path,
        catalog,
        capabilities,
        now=NOW,
    )

    assert time.monotonic() - started < 5
    assert result.state == "rolled_back"
    assert not state.exists()
    child_pid = int(pid_file.read_text(encoding="ascii"))
    with pytest.raises(ProcessLookupError):
        os.kill(child_pid, 0)


def test_recovery_replays_recorded_rollback_exactly_once(tmp_path: Path) -> None:
    plan, _, _, state, _ = _fixture(tmp_path)
    state.write_text("installed", encoding="utf-8")
    control = tmp_path / ".toolbelt"
    control.mkdir(exist_ok=True)
    store = StateStore(control / "state.sqlite3")
    transaction_id = store.begin_transaction(
        plan_id=plan.plan_id,
        repository_identity=plan.repository.identity,
    )
    store.set_transaction_state(transaction_id, "preflight")
    store.set_transaction_state(transaction_id, "applying")
    store.record_action(
        transaction_id,
        plan.actions[0].id,
        sequence=1,
        state="mutated",
        payload=plan.actions[0].model_dump(mode="json"),
    )

    first = Executor(state_store=store).recover(tmp_path, transaction_id)
    second = Executor(state_store=store).recover(tmp_path, transaction_id)

    assert first.state == "rolled_back"
    assert second.state == "rolled_back"
    assert not state.exists()
