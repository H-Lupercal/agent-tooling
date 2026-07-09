from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from toolbelt.executor import Executor
from tests.test_executor_v2 import NOW, _fixture


@pytest.mark.parametrize("fail_after", range(1, 8))
def test_failure_at_every_boundary_restores_original_state(
    tmp_path: Path, fail_after: int
) -> None:
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
