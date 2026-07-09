from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from conductor.schemas import LifecycleEvent
from tests.helpers import DEFAULT_CONFIG, FIXTURES, restore_env, set_env, write_config
from tests.test_store import request


TERMINAL_OR_RECOVERABLE_STATES = {
    "stopped",
    "costed",
    "cancelled",
    "expired",
    "failed",
}


@pytest.fixture
def store(tmp_path: Path):
    from conductor.store import Store

    value = Store(tmp_path / "lifecycle.db")
    value.create_run("run-1", provider="codex", generation=1, mode="admission")
    decision = value.reserve(
        request("run-1", "task-1", correlation_id="task-1"),
        concurrency_cap=4,
        budget_cap=10.0,
    )
    assert decision.allowed
    return value


def lifecycle_events() -> dict[str, LifecycleEvent]:
    now = datetime.now(UTC)
    return {
        "start": LifecycleEvent(
            event_id="task-1-start",
            provider="codex",
            run_id="run-1",
            correlation_id="task-1",
            kind="start",
            occurred_at=now,
            status="running",
        ),
        "stop": LifecycleEvent(
            event_id="task-1-stop",
            provider="codex",
            run_id="run-1",
            correlation_id="task-1",
            kind="stop",
            occurred_at=now,
            status="completed",
            cost_usd=0.1,
            estimated=False,
        ),
        "cost": LifecycleEvent(
            event_id="task-1-cost",
            provider="codex",
            run_id="run-1",
            correlation_id="task-1",
            kind="cost",
            occurred_at=now,
            status="costed",
            cost_usd=0.1,
            estimated=False,
        ),
    }


def lifecycle_permutations() -> list[list[str]]:
    return [
        ["start", "stop", "cost"],
        ["stop", "start", "cost"],
        ["cost", "stop", "start"],
        ["start", "start", "stop", "stop", "cost", "cost"],
    ]


@pytest.mark.parametrize("order", lifecycle_permutations())
def test_lifecycle_is_correlated_and_idempotent(store, order: list[str]) -> None:
    events = lifecycle_events()
    for name in order:
        store.record_lifecycle(events[name])

    assert store.cost_record_count(event_id="task-1-stop") <= 1
    assert store.cost_record_count(event_id="task-1-cost") <= 1
    reservation = store.reservation("task-1")
    assert reservation.state in TERMINAL_OR_RECOVERABLE_STATES


def test_out_of_order_starts_never_swap_correlations(tmp_path: Path) -> None:
    from conductor.store import Store

    value = Store(tmp_path / "correlation.db")
    value.create_run("run-1", provider="codex", generation=1, mode="admission")
    for name, model in (("a", "gpt-a"), ("b", "gpt-b")):
        assert value.reserve(
            request("run-1", name, correlation_id=name, model=model),
            concurrency_cap=4,
            budget_cap=10.0,
        ).allowed
        reservation = value.reservation(name)
        assert reservation.model == model

    now = datetime.now(UTC)
    for name in ("b", "a"):
        value.record_lifecycle(
            LifecycleEvent(
                event_id=f"{name}-start",
                provider="codex",
                run_id="run-1",
                correlation_id=name,
                kind="start",
                occurred_at=now,
                status="running",
            )
        )

    assert value.reservation("a").state == "started"
    assert value.reservation("b").state == "started"
    assert value.reservation("a").model == "gpt-a"
    assert value.reservation("b").model == "gpt-b"


def test_stop_without_reservation_creates_explicit_recoverable_state(
    tmp_path: Path,
) -> None:
    from conductor.store import Store

    value = Store(tmp_path / "recoverable.db")
    value.create_run("run-1", provider="codex", generation=1, mode="admission")
    value.record_lifecycle(
        LifecycleEvent(
            event_id="orphan-stop",
            provider="codex",
            run_id="run-1",
            correlation_id="orphan",
            kind="stop",
            occurred_at=datetime.now(UTC),
            status="completed",
        )
    )

    reservation = value.reservation("orphan")
    assert reservation.state == "stopped"
    assert reservation.recoverable is True
    assert "stop before reservation" in reservation.recovery_reason


def test_duplicate_stop_costs_once(store) -> None:
    stop = lifecycle_events()["stop"]

    store.record_lifecycle(stop)
    store.record_lifecycle(stop)

    assert store.cost_record_count(event_id="task-1-stop") == 1


def test_legacy_hook_start_stop_record_lifecycle_and_cost(tmp_path: Path) -> None:
    from conductor.hooks.lifecycle import handle
    from conductor.ledger import read_events

    old = set_env(
        CODEX_CONDUCTOR_HOME=str(tmp_path / "home"),
        CODEX_CONDUCTOR_CONFIG=str(
            write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
        ),
    )
    try:
        start = json.loads(
            (FIXTURES / "hook_payloads" / "subagent_start.json").read_text(
                encoding="utf-8"
            )
        )
        stop = json.loads(
            (FIXTURES / "hook_payloads" / "subagent_stop.json").read_text(
                encoding="utf-8"
            )
        )
        start["agent_transcript_path"] = str(FIXTURES / "rollout_subagent.jsonl")
        stop["agent_transcript_path"] = str(FIXTURES / "rollout_subagent.jsonl")

        handle(start)
        handle(stop)
        events = read_events("root-run")

        assert [event["event"] for event in events] == [
            "subagent_start",
            "subagent_stop",
            "cost_recorded",
        ]
        assert events[-1]["tokens"]["total_tokens"] == 17753
        assert events[-1]["usd"] > 0
    finally:
        restore_env(old)
