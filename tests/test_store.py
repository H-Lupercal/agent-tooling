from __future__ import annotations

import sqlite3
import time
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
    )


def test_store_enables_wal_foreign_keys_and_complete_v1_schema(
    store_path: Path,
) -> None:
    from conductor.migrations import SCHEMA_VERSION
    from conductor.store import Store

    store = Store(store_path)

    assert store.schema_version() == SCHEMA_VERSION == 1
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
    }


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
