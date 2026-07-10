from __future__ import annotations

import multiprocessing
from pathlib import Path

import pytest


def _reservation_worker(
    path: str,
    run_id: str,
    index: int,
    concurrency_cap: int,
    budget_cap: float,
    estimate: float,
    start,
    results,
) -> None:
    from conductor.store import ReservationRequest, Store

    start.wait()
    try:
        store = Store(Path(path), busy_timeout_ms=4_000)
        decision = store.reserve(
            ReservationRequest(
                run_id=run_id,
                task_id=f"task-{index}",
                correlation_id=f"call-{index}",
                idempotency_key=f"request-{index}",
                operation="spawn",
                tier="mini",
                model="gpt-5.4-mini",
                estimated_usd=estimate,
                ttl_seconds=300,
                generation=1,
                mode="admission",
            ),
            concurrency_cap=concurrency_cap,
            budget_cap=budget_cap,
        )
        results.put(("decision", decision.allowed, decision.rule))
    except BaseException as exc:
        results.put(("error", type(exc).__name__, str(exc)))


def run_concurrent_decisions(
    store_path: Path,
    *,
    processes: int,
    concurrency_cap: int,
    budget_cap: float,
    estimate: float,
) -> list[tuple]:
    from conductor.store import Store

    Store(store_path, busy_timeout_ms=4_000).create_run(
        "stress-run",
        provider="codex",
        generation=1,
        mode="admission",
        lease_seconds=120,
    )
    context = multiprocessing.get_context("spawn")
    start = context.Event()
    results = context.Queue()
    workers = [
        context.Process(
            target=_reservation_worker,
            args=(
                str(store_path),
                "stress-run",
                index,
                concurrency_cap,
                budget_cap,
                estimate,
                start,
                results,
            ),
        )
        for index in range(processes)
    ]
    for worker in workers:
        worker.start()
    start.set()
    output = [results.get(timeout=30) for _ in workers]
    for worker in workers:
        worker.join(timeout=30)
        assert worker.exitcode == 0
    errors = [item for item in output if item[0] == "error"]
    assert errors == []
    return output


@pytest.mark.slow
def test_100_processes_never_exceed_concurrency_cap(tmp_path: Path) -> None:
    from conductor.store import Store

    store_path = tmp_path / "concurrency.db"
    decisions = run_concurrent_decisions(
        store_path,
        processes=100,
        concurrency_cap=4,
        budget_cap=100.0,
        estimate=0.15,
    )

    assert sum(item[1] for item in decisions) == 4
    assert Store(store_path).reserved_count(run_id="stress-run") == 4


@pytest.mark.slow
def test_one_task_budget_allows_exactly_one_concurrent_reservation(
    tmp_path: Path,
) -> None:
    from conductor.store import Store

    store_path = tmp_path / "budget.db"
    decisions = run_concurrent_decisions(
        store_path,
        processes=100,
        concurrency_cap=100,
        budget_cap=0.15,
        estimate=0.15,
    )

    assert sum(item[1] for item in decisions) == 1
    assert Store(store_path).reserved_count(run_id="stress-run") == 1
