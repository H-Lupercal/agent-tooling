from __future__ import annotations

import os
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import toolbelt.executor as executor_module
from tests.test_executor_v2 import NOW, _fixture
from toolbelt.errors import ApplyError, DriftError, ValidationError
from toolbelt.executor import Executor, _ApplyLock
from toolbelt.schemas import ActionOperation, DeclarationV2, InstallScope, TransactionState
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


def test_keyboard_interrupt_records_interrupted_transaction(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, catalog, capabilities, _, _ = _fixture(tmp_path)
    store = StateStore(tmp_path / ".toolbelt" / "interrupt.sqlite3")
    executor = Executor(state_store=store)

    def interrupt(*_args, **_kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(executor, "_preflight", interrupt)
    with pytest.raises(KeyboardInterrupt):
        executor.apply(plan, tmp_path, catalog, capabilities, now=NOW)


def test_recover_rejects_unknown_transaction(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".toolbelt" / "state.sqlite3")
    with pytest.raises(ValidationError, match="unknown transaction"):
        Executor(state_store=store).recover(tmp_path, "missing")


def test_preflight_rejects_catalog_and_permission_drift(tmp_path: Path) -> None:
    plan, catalog, _, _, _ = _fixture(tmp_path)
    executor = Executor(environment={"PATH": os.environ.get("PATH", "")})
    options = {
        "allow_network": False,
        "allow_user_scope": False,
        "allow_elevation": False,
    }

    with pytest.raises(DriftError, match="catalog contract missing"):
        executor._preflight(plan, tmp_path, replace(catalog, tools=()), **options)

    user_action = plan.actions[0].model_copy(update={"install_scope": InstallScope.USER})
    with pytest.raises(ApplyError, match="user-scope approval"):
        executor._preflight(
            plan.model_copy(update={"actions": (user_action,)}), tmp_path, catalog, **options
        )

    env_action = plan.actions[0].model_copy(update={"required_env": ("MISSING_TOKEN",)})
    with pytest.raises(ApplyError, match="environment variable"):
        executor._preflight(
            plan.model_copy(update={"actions": (env_action,)}), tmp_path, catalog, **options
        )

    network_step = plan.actions[0].steps[0].model_copy(update={"requires_network": True})
    network_action = plan.actions[0].model_copy(update={"steps": (network_step,)})
    with pytest.raises(ApplyError, match="network approval"):
        executor._preflight(
            plan.model_copy(update={"actions": (network_action,)}), tmp_path, catalog, **options
        )

    elevation_step = plan.actions[0].steps[0].model_copy(update={"requires_elevation": True})
    elevation_action = plan.actions[0].model_copy(update={"steps": (elevation_step,)})
    with pytest.raises(ApplyError, match="elevation approval"):
        executor._preflight(
            plan.model_copy(update={"actions": (elevation_action,)}), tmp_path, catalog, **options
        )

    cwd_step = plan.actions[0].steps[0].model_copy(update={"cwd": "../escape"})
    cwd_action = plan.actions[0].model_copy(update={"steps": (cwd_step,)})
    with pytest.raises(ValidationError, match="escape"):
        executor._preflight(
            plan.model_copy(update={"actions": (cwd_action,)}), tmp_path, catalog, **options
        )

    missing_step = (
        plan.actions[0].steps[0].model_copy(update={"argv": ("definitely-not-a-real-executable",)})
    )
    missing_action = plan.actions[0].model_copy(update={"steps": (missing_step,)})
    with pytest.raises(ApplyError, match="required executable"):
        executor._preflight(
            plan.model_copy(update={"actions": (missing_action,)}), tmp_path, catalog, **options
        )


def test_preflight_rejects_existing_declaration_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, catalog, _, _, _ = _fixture(tmp_path)
    executor = Executor()
    existing = executor._updated_declaration(plan, catalog, None)
    options = {
        "allow_network": False,
        "allow_user_scope": False,
        "allow_elevation": False,
    }

    monkeypatch.setattr(
        executor_module,
        "load_declaration",
        lambda _root: existing.model_copy(update={"repository_identity": "f" * 64}),
    )
    with pytest.raises(DriftError, match="different repository identity"):
        executor._preflight(plan, tmp_path, catalog, **options)

    wrong_tool = existing.tools[0].model_copy(update={"version": "999.0"})
    monkeypatch.setattr(
        executor_module,
        "load_declaration",
        lambda _root: existing.model_copy(update={"tools": (wrong_tool,)}),
    )
    with pytest.raises(DriftError, match="declared tool versions"):
        executor._preflight(plan, tmp_path, catalog, **options)

    monkeypatch.setattr(
        executor_module,
        "load_declaration",
        lambda _root: existing.model_copy(update={"catalog_digest": "0" * 64}),
    )
    with pytest.raises(DriftError, match="verify every declared tool"):
        executor._preflight(plan, tmp_path, catalog, **options)

    monkeypatch.setattr(executor_module, "load_declaration", lambda _root: existing)
    with pytest.raises(DriftError, match="already declared"):
        executor._preflight(plan, tmp_path, catalog, **options)

    verify_action = plan.actions[0].model_copy(
        update={
            "operation": ActionOperation.VERIFY,
            "steps": (),
            "rollback": (),
        }
    )
    empty = DeclarationV2(
        repository_identity=plan.repository.identity,
        catalog_digest=catalog.digest,
        tools=(),
    )
    monkeypatch.setattr(executor_module, "load_declaration", lambda _root: empty)
    with pytest.raises(DriftError, match="not declared"):
        executor._preflight(
            plan.model_copy(update={"actions": (verify_action,)}), tmp_path, catalog, **options
        )


def test_rollback_surfaces_every_persistence_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan, _, _, _, _ = _fixture(tmp_path)
    executor = Executor()

    class BrokenStore:
        def get_transaction(self, _transaction_id):
            return None

        def actions_for_transaction(self, _transaction_id):
            raise OSError("action read failed")

        def mark_backup_restored(self, *_args):
            raise OSError("backup mark failed")

        def set_transaction_state(self, *_args):
            raise OSError("state failed")

    monkeypatch.setattr(executor, "_run_step", lambda *_args: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(
        executor, "_restore_declaration", lambda *_args: (_ for _ in ()).throw(OSError())
    )

    assert executor._rollback(
        BrokenStore(),  # type: ignore[arg-type]
        "transaction",
        tmp_path,
        [plan.actions[0]],
        [],
        declaration_before=b"original",
        restore_declaration=True,
    )


def test_rollback_transition_is_idempotent_and_validated(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    executor = Executor()
    with pytest.raises(ValidationError, match="unknown transaction"):
        executor._transition_to_rollback(store, "missing")

    transaction_id = store.begin_transaction(
        plan_id="a" * 64,
        repository_identity="b" * 64,
    )
    executor._transition_to_rollback(store, transaction_id)
    assert store.get_transaction(transaction_id)["state"] == TransactionState.ROLLING_BACK
    executor._transition_to_rollback(store, transaction_id)
    assert store.get_transaction(transaction_id)["state"] == TransactionState.ROLLING_BACK


def test_declaration_backup_restore_and_digest_validation(tmp_path: Path) -> None:
    store = StateStore(tmp_path / ".toolbelt" / "state.sqlite3")
    executor = Executor()
    transaction_id = store.begin_transaction(
        plan_id="a" * 64,
        repository_identity="b" * 64,
    )
    assert executor._backup_bytes(store, tmp_path, transaction_id) is None

    store.record_backup(
        transaction_id,
        ".toolbelt/lock.toml",
        backup_path="",
        sha256_digest="0" * 64,
    )
    assert executor._backup_bytes(store, tmp_path, transaction_id) is None

    content = b"original declaration"
    backup = tmp_path / ".toolbelt" / "backups" / "bad.toml"
    backup.parent.mkdir(parents=True, exist_ok=True)
    backup.write_bytes(content)
    store.record_backup(
        transaction_id,
        ".toolbelt/lock.toml",
        backup_path=".toolbelt/backups/bad.toml",
        sha256_digest="f" * 64,
    )
    with pytest.raises(DriftError, match="digest mismatch"):
        executor._backup_bytes(store, tmp_path, transaction_id)

    target = tmp_path / ".toolbelt" / "lock.toml"
    executor._restore_declaration(tmp_path, content)
    assert target.read_bytes() == content
    executor._restore_declaration(tmp_path, None)
    assert not target.exists()


@pytest.mark.skipif(os.name == "nt", reason="POSIX advisory lock behavior")
def test_apply_lock_rejects_changed_unsafe_and_busy_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    changed = tmp_path / "changed.lock"
    real_fstat = executor_module.os.fstat
    monkeypatch.setattr(
        executor_module.os,
        "fstat",
        lambda descriptor: SimpleNamespace(
            st_dev=real_fstat(descriptor).st_dev + 1,
            st_ino=real_fstat(descriptor).st_ino,
        ),
    )
    with pytest.raises(ApplyError, match="path changed"):
        with _ApplyLock(changed, timeout=0.1):
            pass
    monkeypatch.setattr(executor_module.os, "fstat", real_fstat)

    monkeypatch.setattr(
        executor_module.os,
        "open",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unsafe")),
    )
    with pytest.raises(ApplyError, match="unsafe or unavailable"):
        with _ApplyLock(tmp_path / "unsafe.lock", timeout=0.1):
            pass
    monkeypatch.undo()

    lock_path = tmp_path / "busy.lock"
    with _ApplyLock(lock_path, timeout=0.1):
        with pytest.raises(ApplyError, match="another Toolbelt"):
            with _ApplyLock(lock_path, timeout=0.01):
                pass

    unopened = _ApplyLock(tmp_path / "unused.lock", timeout=0.1)
    unopened.__exit__(None, None, None)


@pytest.mark.skipif(os.name == "nt", reason="POSIX process-group cleanup behavior")
def test_process_and_pipe_cleanup_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    completed = subprocess.Popen([sys.executable, "-c", "pass"])
    completed.wait()
    executor_module._terminate_process_group(completed)

    process = SimpleNamespace(
        pid=12345,
        poll=lambda: None,
        wait=lambda **_kwargs: (_ for _ in ()).throw(subprocess.TimeoutExpired("x", 1)),
    )
    monkeypatch.setattr(
        executor_module.os,
        "killpg",
        lambda *_args: (_ for _ in ()).throw(OSError("missing")),
    )
    executor_module._terminate_process_group(process)

    class BrokenPipe:
        def read(self, _size):
            raise OSError("closed")

    output = bytearray()
    executor_module._drain_pipe(BrokenPipe(), output, 1024)  # type: ignore[arg-type]
    assert output == b""
