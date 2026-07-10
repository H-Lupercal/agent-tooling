from __future__ import annotations

import os
from pathlib import Path

import pytest

import conductor.accounting as accounting
from conductor.config import load_config
from conductor.schemas import LifecycleKind, Provider
from tests.helpers import DEFAULT_CONFIG, FIXTURES, write_config


def _config(tmp_path: Path):
    return load_config(write_config(tmp_path / "conductor.toml", DEFAULT_CONFIG))


def test_stop_normalizes_measured_usage_and_exact_once_identifiers(
    tmp_path: Path,
) -> None:
    from conductor.accounting import normalize_lifecycle_events

    payload = {
        "hook_event_name": "SubagentStop",
        "root_thread_id": "run-1",
        "tool_call_id": "call-1",
        "event_id": "provider-retry-specific-id",
        "model": "gpt-5.4",
        "status": "completed",
        "usage": {
            "input_tokens": 1_000,
            "cached_input_tokens": 100,
            "output_tokens": 100,
            "reasoning_output_tokens": 20,
        },
    }

    terminal, cost = normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload=payload,
        config=_config(tmp_path),
        reservation_model="gpt-5.4",
        reservation_estimate_usd=0.6,
    )

    assert terminal.event_id == "terminal-call-1"
    assert terminal.kind.value == "stop"
    assert cost.event_id == "cost-call-1"
    assert cost.usage is not None
    assert cost.usage.source_event_id == "usage-call-1"
    assert cost.usage.input_tokens == 1_000
    assert cost.usage.cache_read_tokens == 100
    assert cost.cost_usd == pytest.approx(0.00242)
    assert cost.estimated is False


def test_claude_uncached_and_cache_categories_are_not_double_billed(
    tmp_path: Path,
) -> None:
    from conductor.accounting import normalize_lifecycle_events

    _, cost = normalize_lifecycle_events(
        provider=Provider.CLAUDE,
        payload={
            "hook_event_name": "SubagentStop",
            "session_id": "run-1",
            "agent_id": "agent-1",
            "model": "gpt-5.4",
            "usage": {
                "input_tokens": 1_000,
                "cache_read_input_tokens": 100,
                "cache_creation_input_tokens": 50,
                "output_tokens": 100,
            },
        },
        config=_config(tmp_path),
        reservation_model="gpt-5.4",
        reservation_estimate_usd=0.6,
    )

    assert cost.usage is not None
    assert cost.usage.input_tokens == 1_150
    assert cost.cost_usd == pytest.approx(0.002745)


def test_missing_usage_charges_only_the_reserved_estimate(tmp_path: Path) -> None:
    from conductor.accounting import normalize_lifecycle_events

    _, cost = normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "hook_event_name": "SubagentStop",
            "root_thread_id": "run-1",
            "tool_call_id": "call-1",
            "model": "gpt-5.4",
        },
        config=_config(tmp_path),
        reservation_model="gpt-5.4",
        reservation_estimate_usd=0.6,
    )

    assert cost.usage is None
    assert cost.cost_usd == 0.6
    assert cost.estimated is True


def test_bounded_transcript_parser_rejects_symlinks(tmp_path: Path) -> None:
    from conductor.rollout import latest_usage

    target = FIXTURES / "rollout_subagent.jsonl"
    link = tmp_path / "rollout.jsonl"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unavailable")

    assert latest_usage(link) is None


def test_transcript_usage_is_measured_when_direct_usage_is_absent(
    tmp_path: Path,
) -> None:
    from conductor.accounting import normalize_lifecycle_events

    _, cost = normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "hook_event_name": "SubagentStop",
            "root_thread_id": "run-1",
            "tool_call_id": "call-1",
            "model": "gpt-5.4",
            "agent_transcript_path": str(FIXTURES / "rollout_subagent.jsonl"),
        },
        config=_config(tmp_path),
        reservation_model="gpt-5.4",
        reservation_estimate_usd=0.6,
    )

    assert cost.usage is not None
    assert cost.usage.input_tokens == 17_425
    assert cost.usage.output_tokens == 328
    assert cost.estimated is False


def test_maximum_length_correlation_produces_bounded_stable_event_ids(
    tmp_path: Path,
) -> None:
    from conductor.accounting import normalize_lifecycle_events

    correlation = "c" * 128
    payload = {
        "hook_event_name": "SubagentStop",
        "root_thread_id": "run-1",
        "tool_call_id": correlation,
        "model": "gpt-5.4",
        "usage": {"input_tokens": 1, "output_tokens": 1},
    }

    first = normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload=payload,
        config=_config(tmp_path),
    )
    second = normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload=payload,
        config=_config(tmp_path),
    )

    assert [event.event_id for event in first] == [event.event_id for event in second]
    assert all(len(event.event_id) <= 128 for event in first)
    assert first[1].usage is not None
    assert len(first[1].usage.source_event_id) <= 128


def test_start_failure_cancel_and_unsupported_events_are_explicit(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    start = accounting.normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "hook_event_name": "SubagentStart",
            "run_id": "run-1",
            "task_id": "task-1",
            "timestamp": 1_700_000_000,
        },
        config=config,
    )
    assert len(start) == 1
    assert start[0].kind is LifecycleKind.START
    assert start[0].status == "running"
    assert int(start[0].occurred_at.timestamp()) == 1_700_000_000

    failed, _ = accounting.normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "event": "SubagentFailure",
            "session_id": "run-1",
            "lifecycle_id": "task-1",
            "status": "error",
        },
        config=config,
    )
    assert failed.kind is LifecycleKind.FAIL

    cancelled, _ = accounting.normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "event": "SubagentStop",
            "session_id": "run-1",
            "agent_id": "agent-1",
            "status": "cancelled",
        },
        config=config,
    )
    assert cancelled.kind is LifecycleKind.CANCEL

    with pytest.raises(ValueError, match="unsupported lifecycle event"):
        accounting.normalize_lifecycle_events(
            provider=Provider.CODEX,
            payload={"event": "Unknown", "run_id": "run-1", "task_id": "task-1"},
            config=config,
        )


def test_missing_identity_and_usage_model_fail_closed(tmp_path: Path) -> None:
    config = _config(tmp_path)
    with pytest.raises(ValueError, match="run id is missing"):
        accounting.normalize_lifecycle_events(
            provider=Provider.CODEX,
            payload={"event": "SubagentStart", "task_id": "task-1"},
            config=config,
        )
    with pytest.raises(ValueError, match="correlation id is missing"):
        accounting.normalize_lifecycle_events(
            provider=Provider.CODEX,
            payload={"event": "SubagentStart", "run_id": "run-1"},
            config=config,
        )

    _, direct_without_model = accounting.normalize_lifecycle_events(
        provider=Provider.CODEX,
        payload={
            "event": "SubagentStop",
            "run_id": "run-1",
            "task_id": "task-1",
            "usage": {"input_tokens": 1},
        },
        config=config,
        reservation_estimate_usd=0.4,
    )
    assert direct_without_model.usage is None
    assert direct_without_model.cost_usd == 0.4
    assert direct_without_model.estimated

    _, missing_claude_transcript = accounting.normalize_lifecycle_events(
        provider=Provider.CLAUDE,
        payload={
            "event": "SubagentStop",
            "run_id": "run-1",
            "task_id": "task-2",
            "model": "gpt-5.4",
            "agent_transcript_path": str(tmp_path / "missing.jsonl"),
        },
        config=config,
        reservation_estimate_usd=0.5,
    )
    assert missing_claude_transcript.usage is None
    assert missing_claude_transcript.cost_usd == 0.5


def test_timestamp_and_token_validation_covers_all_input_forms() -> None:
    now = accounting._timestamp(None)
    assert now.tzinfo is not None
    assert accounting._timestamp("2026-07-09T12:00:00Z").isoformat().endswith("+00:00")

    with pytest.raises(ValueError, match="timezone-aware"):
        accounting._timestamp("2026-07-09T12:00:00")
    with pytest.raises(ValueError, match="invalid lifecycle timestamp"):
        accounting._timestamp(True)
    with pytest.raises(ValueError, match="invalid lifecycle timestamp"):
        accounting._timestamp(object())

    for value in (True, "1", 1.0, -1):
        with pytest.raises(ValueError, match="nonnegative integers"):
            accounting._nonnegative_int(value)
