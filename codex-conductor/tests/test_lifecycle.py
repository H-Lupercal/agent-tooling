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


def test_hook_start_stop_record_strict_lifecycle_and_cost_exactly_once(
    tmp_path: Path,
) -> None:
    from conductor.hooks.lifecycle import handle
    from conductor.store import Store

    home = tmp_path / "home"
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home),
        CODEX_CONDUCTOR_CONFIG=str(
            write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
        ),
    )
    try:
        database = Store(home / "state" / "conductor.db")
        database.create_run(
            "root-run", provider="codex", generation=1, mode="admission"
        )
        assert database.reserve(
            request(
                "root-run",
                "task-hook",
                correlation_id="call-hook",
                model="gpt-5.4",
                estimate=0.6,
            ),
            concurrency_cap=4,
            budget_cap=10.0,
        ).allowed
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
        start["tool_call_id"] = "call-hook"
        stop["tool_call_id"] = "call-hook"

        handle(start)
        handle(stop)
        stop["event_id"] = "provider-retry-with-another-id"
        handle(stop)

        assert database.reservation("call-hook").state == "costed"
        assert database.cost_record_count(event_id="cost-call-hook") == 1
        assert (
            database.raw_usage_count(
                run_id="root-run", source_event_id="usage-call-hook"
            )
            == 1
        )
        assert database.total_cost_usd(run_id="root-run") > 0
    finally:
        restore_env(old)


def test_post_tool_use_links_concurrent_child_identity_before_lifecycle(
    tmp_path: Path,
) -> None:
    from conductor.hooks.lifecycle import handle
    from conductor.store import Store

    old = set_env(
        CODEX_CONDUCTOR_CONFIG=str(
            write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
        )
    )
    try:
        database = Store(tmp_path / "linked.db")
        database.create_run(
            "root-run", provider="codex", generation=1, mode="admission"
        )
        assert database.reserve(
            request(
                "root-run",
                "linked-task",
                correlation_id="tool-call-1",
                model="gpt-5.4",
                estimate=0.6,
            ),
            concurrency_cap=4,
            budget_cap=10.0,
        ).allowed

        handle(
            {
                "hook_event_name": "PostToolUse",
                "root_thread_id": "root-run",
                "thread_id": "root-run",
                "tool_call_id": "tool-call-1",
                "tool_response": {"agent_id": "child-1"},
            },
            provider_name="codex",
            store=database,
        )
        for event_name in ("SubagentStart", "SubagentStop"):
            handle(
                {
                    "hook_event_name": event_name,
                    "root_thread_id": "root-run",
                    "thread_id": "child-1",
                    "model": "gpt-5.4",
                    "agent_transcript_path": str(FIXTURES / "rollout_subagent.jsonl"),
                },
                provider_name="codex",
                store=database,
            )
    finally:
        restore_env(old)

    assert database.reservation("child-1", run_id="root-run").state == "costed"
    assert database.cost_record_count(event_id="cost-tool-call-1") == 1


def test_codex_post_tool_link_never_treats_outer_caller_as_child() -> None:
    from conductor.providers.codex import PROVIDER

    assert (
        PROVIDER.correlation_link(
            {
                "root_thread_id": "run-1",
                "thread_id": "caller-thread",
                "agent_id": "caller-agent",
                "tool_call_id": "tool-1",
            }
        )
        is None
    )
    direct = PROVIDER.correlation_link(
        {
            "root_thread_id": "run-1",
            "tool_call_id": "t" * 128,
            "child_id": "child-1",
        }
    )
    assert direct is not None
    assert direct.child_alias == "child-1"
    assert len(direct.source_event_id) <= 128


def test_post_tool_feedback_is_an_explicit_noop(tmp_path: Path) -> None:
    from conductor.hooks.lifecycle import handle
    from conductor.store import Store

    old = set_env(
        CODEX_CONDUCTOR_CONFIG=str(
            write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG)
        )
    )
    try:
        database = Store(tmp_path / "feedback.db")
        database.create_run("run-1", provider="codex", generation=1, mode="admission")
        recorded = handle(
            {
                "hook_event_name": "PostToolUse",
                "root_thread_id": "run-1",
                "tool_call_id": "message-1",
                "tool_name": "send_message",
                "tool_input": {"target": "child-1", "message": "status?"},
            },
            provider_name="codex",
            store=database,
        )
    finally:
        restore_env(old)

    assert recorded == ()
