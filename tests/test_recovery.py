from __future__ import annotations

import contextlib
import io
import json
from datetime import UTC, datetime
from pathlib import Path

from conductor.schemas import LifecycleEvent
from conductor.store import Store


def test_recoverable_lifecycle_is_listed_and_explicitly_resolved(
    tmp_path: Path,
) -> None:
    store = Store(tmp_path / "recovery.db")
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    store.record_lifecycle(
        LifecycleEvent(
            event_id="orphan-stop",
            provider="codex",
            run_id="run-1",
            correlation_id="orphan-1",
            kind="stop",
            occurred_at=datetime.now(UTC),
        )
    )

    recoverable = store.recoverable_reservations(run_id="run-1")
    assert [item.correlation_id for item in recoverable] == ["orphan-1"]

    resolved = store.resolve_recovery("orphan-1", run_id="run-1", outcome="failed")
    assert resolved.state == "failed"
    assert resolved.recoverable is False
    assert store.recoverable_reservations(run_id="run-1") == []


def test_recovery_command_lists_resolves_and_reports_missing_state(
    tmp_path: Path,
) -> None:
    from conductor.recovery import main
    from tests.helpers import restore_env, set_env

    home = tmp_path / "home"
    store = Store(home / "state" / "conductor.db")
    store.create_run("run-cli", provider="codex", generation=1, mode="admission")
    store.record_lifecycle(
        LifecycleEvent(
            event_id="orphan-cli",
            provider="codex",
            run_id="run-cli",
            correlation_id="orphan-cli",
            kind="stop",
            occurred_at=datetime.now(UTC),
        )
    )
    old = set_env(CODEX_CONDUCTOR_HOME=str(home))
    try:
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert main(["--run", "run-cli", "--json"]) == 0
        payload = json.loads(output.getvalue())
        assert payload["schema_version"] == 1
        assert payload["recoverable"][0]["correlation_id"] == "orphan-cli"

        with contextlib.redirect_stdout(io.StringIO()):
            assert (
                main(
                    [
                        "--run",
                        "run-cli",
                        "--reservation",
                        "orphan-cli",
                        "--outcome",
                        "cancelled",
                    ]
                )
                == 0
            )
    finally:
        restore_env(old)

    empty = set_env(CODEX_CONDUCTOR_HOME=str(tmp_path / "missing"))
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            assert main([]) != 0
    finally:
        restore_env(empty)
