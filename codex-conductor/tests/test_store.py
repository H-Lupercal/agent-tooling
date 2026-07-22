from __future__ import annotations

import os
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest


@pytest.fixture
def store_path(tmp_path: Path) -> Path:
    return tmp_path / "state" / "conductor.db"


def request(
    run_id: str,
    task_id: str,
    *,
    correlation_id: str | None = None,
    idempotency_key: str | None = None,
    estimate: float = 0.15,
    ttl_seconds: int = 300,
    generation: int = 1,
    model: str = "gpt-5.4-mini",
    reasoning_effort: str | None = None,
):
    from conductor.store import ReservationRequest

    return ReservationRequest(
        run_id=run_id,
        task_id=task_id,
        correlation_id=correlation_id or f"call-{task_id}",
        idempotency_key=idempotency_key or f"request-{task_id}",
        operation="spawn",
        tier="mini",
        model=model,
        estimated_usd=estimate,
        ttl_seconds=ttl_seconds,
        generation=generation,
        mode="admission",
        reasoning_effort=reasoning_effort,
    )


def test_store_enables_wal_foreign_keys_and_complete_v4_schema(
    store_path: Path,
) -> None:
    from conductor.migrations import SCHEMA_VERSION
    from conductor.store import Store

    store = Store(store_path)

    assert store.schema_version() == SCHEMA_VERSION == 4
    assert store.journal_mode().lower() == "wal"
    assert store.foreign_keys_enabled() is True
    assert store.table_names() >= {
        "runs",
        "leases",
        "operations",
        "decisions",
        "reservations",
        "lifecycle_events",
        "raw_usage",
        "costs",
        "installation_state",
        "correlation_aliases",
    }


def test_existing_v1_database_migrates_forward_without_legacy_runtime(
    store_path: Path,
) -> None:
    from conductor.migrations import MIGRATIONS
    from conductor.store import Store

    store_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(store_path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for statement in MIGRATIONS[1]:
            connection.execute(statement)
        connection.execute("PRAGMA user_version = 1")
        connection.commit()
    finally:
        connection.close()

    store = Store(store_path)

    assert store.schema_version() == 4
    assert "correlation_aliases" in store.table_names()
    assert "legacy_events" not in store.table_names()


def test_reservation_round_trips_reasoning_effort(store_path: Path) -> None:
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-effort", provider="codex", generation=1, mode="routing")

    decision = store.reserve(
        request("run-effort", "task-effort", reasoning_effort="medium"),
        concurrency_cap=2,
        budget_cap=10.0,
    )

    assert decision.allowed
    assert store.reservation("task-effort", run_id="run-effort").reasoning_effort == (
        "medium"
    )


def test_existing_v3_reservation_migrates_with_unknown_effort(
    store_path: Path,
) -> None:
    from conductor.migrations import MIGRATIONS
    from conductor.store import Store

    store_path.parent.mkdir(parents=True)
    connection = sqlite3.connect(store_path, isolation_level=None)
    try:
        connection.execute("BEGIN IMMEDIATE")
        for version in (1, 2, 3):
            for statement in MIGRATIONS[version]:
                connection.execute(statement)
        connection.execute(
            "INSERT INTO runs VALUES (?, ?, ?, ?, NULL, ?, ?)",
            ("run-v3", "codex", 1, "admission", 1_000.0, 1_000.0),
        )
        connection.execute(
            """
            INSERT INTO reservations (
                reservation_id, run_id, task_id, correlation_id, operation,
                tier, model, estimated_usd, state, recoverable, recovery_reason,
                created_at, updated_at, expires_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "reservation-v3",
                "run-v3",
                "task-v3",
                "call-v3",
                "spawn",
                "mini",
                "gpt-5.4-mini",
                0.15,
                "approved",
                0,
                None,
                1_000.0,
                1_000.0,
                1_300.0,
            ),
        )
        connection.execute("PRAGMA user_version = 3")
        connection.commit()
    finally:
        connection.close()

    store = Store(store_path)

    assert store.schema_version() == 4
    assert store.reservation("task-v3", run_id="run-v3").reasoning_effort is None


def test_decide_and_reserve_is_idempotent(store_path: Path) -> None:
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    reservation = request("run-1", "task-1")

    first = store.reserve(reservation, concurrency_cap=4, budget_cap=10.0)
    duplicate = store.reserve(reservation, concurrency_cap=4, budget_cap=10.0)

    assert first.allowed is True
    assert duplicate == first
    assert store.reserved_count(run_id="run-1") == 1
    assert store.decision_count(run_id="run-1") == 1


def test_run_context_is_strictly_persisted_and_revalidated(store_path: Path) -> None:
    from conductor.schemas import RunContext
    from conductor.store import Store

    now = datetime.now(UTC)
    context = RunContext(
        provider="codex",
        run_id="run-context",
        thread_id="thread-context",
        root_model="gpt-5.5",
        model_source="provider",
        provider_contract="codex-current",
        contract_digest="0" * 64,
        mode="admission",
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest="1" * 64,
    )
    store = Store(store_path)
    store.create_run(
        context.run_id,
        provider=context.provider.value,
        generation=context.generation,
        mode=context.mode.value,
        context=context.model_dump(mode="json"),
    )

    assert store.run_context(context.run_id) == context


def test_stale_reservation_expires_inside_next_decision(store_path: Path) -> None:
    from conductor.store import Store

    now = [1_000.0]
    store = Store(store_path, clock=lambda: now[0])
    store.create_run(
        "run-1", provider="codex", generation=1, mode="admission", lease_seconds=100
    )

    first = store.reserve(
        request("run-1", "task-1", ttl_seconds=1),
        concurrency_cap=1,
        budget_cap=10.0,
    )
    now[0] += 2
    second = store.reserve(
        request("run-1", "task-2", ttl_seconds=1),
        concurrency_cap=1,
        budget_cap=10.0,
    )

    assert first.allowed is True
    assert second.allowed is True
    assert store.reservation("task-1").state == "expired"
    assert store.reserved_count(run_id="run-1") == 1


def test_started_reservation_never_expires_while_child_is_unfinished(
    store_path: Path,
) -> None:
    from conductor.schemas import LifecycleEvent
    from conductor.store import Store

    now = [1_000.0]
    store = Store(store_path, clock=lambda: now[0])
    store.create_run(
        "run-1", provider="codex", generation=1, mode="admission", lease_seconds=100
    )
    assert store.reserve(
        request("run-1", "task-1", correlation_id="call-1", ttl_seconds=1),
        concurrency_cap=1,
        budget_cap=10.0,
    ).allowed
    store.record_lifecycle(
        LifecycleEvent(
            event_id="start-call-1",
            provider="codex",
            run_id="run-1",
            correlation_id="call-1",
            kind="start",
            occurred_at=datetime.now(UTC),
        )
    )

    now[0] += 2
    second = store.reserve(
        request("run-1", "task-2", ttl_seconds=1),
        concurrency_cap=1,
        budget_cap=10.0,
    )

    assert second.allowed is False
    assert second.rule == "CONCURRENCY_CAP"
    unfinished = store.reservation("task-1")
    assert unfinished.state == "started"
    assert unfinished.recoverable is True
    assert "exceeded TTL" in unfinished.recovery_reason


def test_stopped_but_uncosted_reservation_still_holds_budget(
    store_path: Path,
) -> None:
    from conductor.schemas import LifecycleEvent
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    assert store.reserve(
        request("run-1", "task-1", correlation_id="call-1", estimate=0.6),
        concurrency_cap=1,
        budget_cap=1.0,
    ).allowed
    store.record_lifecycle(
        LifecycleEvent(
            event_id="stop-call-1",
            provider="codex",
            run_id="run-1",
            correlation_id="call-1",
            kind="stop",
            occurred_at=datetime.now(UTC),
        )
    )

    second = store.reserve(
        request("run-1", "task-2", estimate=0.6),
        concurrency_cap=1,
        budget_cap=1.0,
    )

    assert second.allowed is False
    assert second.rule == "BUDGET_CAP"


def test_duplicate_lifecycle_id_with_different_payload_is_rejected(
    store_path: Path,
) -> None:
    from conductor.errors import StateError
    from conductor.schemas import LifecycleEvent
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    for task, correlation in (("task-1", "call-1"), ("task-2", "call-2")):
        assert store.reserve(
            request("run-1", task, correlation_id=correlation),
            concurrency_cap=2,
            budget_cap=10.0,
        ).allowed
    first = LifecycleEvent(
        event_id="shared-event",
        provider="codex",
        run_id="run-1",
        correlation_id="call-1",
        kind="start",
        occurred_at=datetime.now(UTC),
    )
    conflicting = first.model_copy(update={"correlation_id": "call-2"})

    store.record_lifecycle(first)
    with pytest.raises(StateError, match="conflicting lifecycle event"):
        store.record_lifecycle(conflicting)


def test_generation_and_active_lease_are_validated(store_path: Path) -> None:
    from conductor.store import Store

    now = [1_000.0]
    store = Store(store_path, clock=lambda: now[0])
    store.create_run(
        "run-1", provider="codex", generation=2, mode="admission", lease_seconds=2
    )

    stale_generation = store.reserve(
        request("run-1", "task-1", generation=1),
        concurrency_cap=1,
        budget_cap=10.0,
    )
    now[0] += 3
    expired_lease = store.reserve(
        request("run-1", "task-2", generation=2),
        concurrency_cap=1,
        budget_cap=10.0,
    )

    assert stale_generation.allowed is False
    assert stale_generation.rule == "STALE_GENERATION"
    assert expired_lease.allowed is False
    assert expired_lease.rule == "RUN_LEASE_EXPIRED"


def test_active_run_leases_are_never_gc_candidates(store_path: Path) -> None:
    from conductor.store import Store

    now = [10_000.0]
    store = Store(store_path, clock=lambda: now[0])
    store.create_run(
        "active", provider="codex", generation=1, mode="admission", lease_seconds=100
    )
    store.create_run(
        "expired", provider="codex", generation=1, mode="admission", lease_seconds=1
    )
    now[0] += 2

    assert store.gc_candidates(older_than=now[0] + 1) == ["expired"]


def test_duplicate_correlation_cannot_create_second_reservation(
    store_path: Path,
) -> None:
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    first = store.reserve(
        request("run-1", "task-1", correlation_id="shared"),
        concurrency_cap=4,
        budget_cap=10.0,
    )
    duplicate = store.reserve(
        request(
            "run-1",
            "task-2",
            correlation_id="shared",
            idempotency_key="different-request",
        ),
        concurrency_cap=4,
        budget_cap=10.0,
    )

    assert first.allowed is True
    assert duplicate.allowed is False
    assert duplicate.rule == "DUPLICATE_CORRELATION"
    assert store.reserved_count(run_id="run-1") == 1


def test_post_tool_result_links_child_identity_without_fifo_guessing(
    store_path: Path,
) -> None:
    from conductor.errors import StateError
    from conductor.store import Store

    store = Store(store_path)
    store.create_run("run-1", provider="claude", generation=1, mode="routing")
    assert store.reserve(
        request("run-1", "task-1", correlation_id="tool-use-1"),
        concurrency_cap=4,
        budget_cap=10.0,
    ).allowed

    linked = store.link_correlation(
        "run-1",
        source_correlation="tool-use-1",
        alias="agent-1",
        source_event_id="post-tool-1",
    )
    duplicate = store.link_correlation(
        "run-1",
        source_correlation="tool-use-1",
        alias="agent-1",
        source_event_id="post-tool-1",
    )

    assert linked == duplicate
    assert store.reservation("agent-1", run_id="run-1") == linked
    with pytest.raises(StateError, match="already linked"):
        store.link_correlation(
            "run-1",
            source_correlation="tool-use-1",
            alias="agent-2",
            source_event_id="post-tool-1",
        )


def test_lock_contention_fails_within_hook_bounded_timeout(store_path: Path) -> None:
    from conductor.errors import StoreBusyError
    from conductor.store import Store

    store = Store(store_path, busy_timeout_ms=100)
    store.create_run("run-1", provider="codex", generation=1, mode="admission")
    blocker = sqlite3.connect(store_path, isolation_level=None)
    blocker.execute("BEGIN IMMEDIATE")
    started = time.monotonic()
    try:
        with pytest.raises(StoreBusyError, match="100ms"):
            store.reserve(
                request("run-1", "task-1"),
                concurrency_cap=1,
                budget_cap=10.0,
            )
    finally:
        blocker.rollback()
        blocker.close()

    assert time.monotonic() - started < 1.0


def test_store_rejects_database_and_sidecar_symlinks(tmp_path: Path) -> None:
    from conductor.errors import StateError
    from conductor.store import Store

    victim = tmp_path / "victim.db"
    victim.write_text("preserve", encoding="utf-8")
    database = tmp_path / "state.db"
    try:
        os.symlink(victim, database)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    with pytest.raises(StateError, match="symbolic link"):
        Store(database)
    assert victim.read_text(encoding="utf-8") == "preserve"

    sidecar_database = tmp_path / "sidecar.db"
    sidecar = tmp_path / "sidecar.db-wal"
    try:
        os.symlink(victim, sidecar)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")
    with pytest.raises(StateError, match="symbolic link"):
        Store(sidecar_database)
    assert victim.read_text(encoding="utf-8") == "preserve"
