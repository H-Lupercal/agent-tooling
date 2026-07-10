from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest

from toolbelt.schemas import DeclarationV2, DeclaredToolV2
from toolbelt.state import (
    StateStore,
    load_declaration,
    render_declaration,
    write_declaration,
)


def _write_transaction(database: str, index: int, queue: multiprocessing.Queue) -> None:
    try:
        store = StateStore(Path(database))
        store.begin_transaction(
            plan_id=f"{index:064x}",
            repository_identity="a" * 64,
            transaction_id=f"tx-{index}",
        )
        queue.put(None)
    except BaseException as exc:  # pragma: no cover - surfaced by parent assertion
        queue.put(repr(exc))


def test_store_uses_versioned_wal_schema_and_foreign_keys(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")

    assert store.schema_version() == 1
    assert store.journal_mode().lower() == "wal"
    assert store.foreign_keys_enabled() is True
    assert store.table_names() >= {
        "transactions",
        "actions",
        "command_results",
        "backups",
        "recovery_records",
    }


def test_32_concurrent_state_writers_preserve_all_transactions(tmp_path: Path) -> None:
    database = tmp_path / "state.sqlite3"
    StateStore(database)
    context = multiprocessing.get_context("spawn")
    queue = context.Queue()
    processes = [
        context.Process(target=_write_transaction, args=(str(database), index, queue))
        for index in range(32)
    ]
    for process in processes:
        process.start()
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    errors = [queue.get(timeout=2) for _ in processes]

    assert errors == [None] * 32
    assert StateStore(database).transaction_count() == 32


def test_transaction_state_machine_rejects_invalid_transition(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    transaction_id = store.begin_transaction(
        plan_id="b" * 64,
        repository_identity="a" * 64,
    )

    with pytest.raises(ValueError, match="invalid transaction transition"):
        store.set_transaction_state(transaction_id, "succeeded")


def test_declaration_rendering_is_deterministic_and_atomic(tmp_path: Path) -> None:
    declaration = DeclarationV2(
        repository_identity="a" * 64,
        catalog_digest="b" * 64,
        tools=(
            DeclaredToolV2(
                tool_id="ruff",
                version="0.8.6",
                provenance="pypi:ruff==0.8.6",
                install_scope="project",
                permissions=("network", "process-spawn"),
                artifacts=("pyproject.toml",),
            ),
        ),
    )

    first = render_declaration(declaration)
    second = render_declaration(declaration)
    path = write_declaration(tmp_path, declaration)

    assert first == second
    assert path == tmp_path / ".toolbelt" / "lock.toml"
    assert path.read_text(encoding="utf-8") == first
    assert "schema_version = 2" in first
    assert not list(path.parent.glob("*.tmp"))
    assert load_declaration(tmp_path) == declaration


def test_action_command_backup_and_recovery_journal_round_trip(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    transaction_id = store.begin_transaction(
        plan_id="b" * 64,
        repository_identity="a" * 64,
    )
    store.record_action(
        transaction_id,
        "a0001",
        sequence=1,
        state="mutated",
        payload={"schema_version": 2, "id": "a0001"},
    )
    store.record_command(
        transaction_id,
        "a0001",
        phase="apply",
        argv=("fixture", "run"),
        returncode=0,
        stdout="ok",
        stderr="",
        duration_seconds=0.1,
        timed_out=False,
    )
    store.record_backup(
        transaction_id,
        ".toolbelt/lock.toml",
        backup_path=".toolbelt/backups/lock.toml",
        sha256_digest="c" * 64,
    )
    store.record_recovery(transaction_id, "pending", "recovery requested")

    assert store.actions_for_transaction(transaction_id)[0]["payload"]["id"] == "a0001"
    assert store.backups_for_transaction(transaction_id)[0]["restored"] == 0
    store.mark_backup_restored(transaction_id, ".toolbelt/lock.toml")
    assert store.backups_for_transaction(transaction_id)[0]["restored"] == 1
    assert store.incomplete_transactions()[0]["transaction_id"] == transaction_id


def test_supported_transaction_lifecycle_reaches_terminal_state(tmp_path: Path) -> None:
    store = StateStore(tmp_path / "state.sqlite3")
    transaction_id = store.begin_transaction(
        plan_id="b" * 64,
        repository_identity="a" * 64,
    )

    for state in ("preflight", "applying", "verifying", "succeeded"):
        store.set_transaction_state(transaction_id, state)

    assert store.get_transaction(transaction_id)["state"] == "succeeded"
    assert not store.incomplete_transactions()


def test_invalid_declaration_is_rejected(tmp_path: Path) -> None:
    control = tmp_path / ".toolbelt"
    control.mkdir()
    (control / "lock.toml").write_text("schema_version = 1\n", encoding="utf-8")

    with pytest.raises(Exception, match="invalid Toolbelt declaration"):
        load_declaration(tmp_path)
