from __future__ import annotations

import os
from pathlib import Path

import pytest

from conductor.config import load_config
from conductor.schemas import Provider
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
