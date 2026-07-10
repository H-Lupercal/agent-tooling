from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from conductor.config import config_digest, load_config
from conductor.identity import Caller
from conductor.schemas import RunContext
from conductor.store import Store
from tests.helpers import PROJECT_ROOT, restore_env, set_env
from tests.test_store import request

CLAUDE_CONFIG = (
    PROJECT_ROOT / "src" / "conductor" / "assets" / "config" / "conductor.claude.toml"
)
ENVELOPE = (
    '<CONDUCTOR_TASK>{"schema_version":1,"task_name":"impl_worker",'
    '"task_class":"implementation","risk_triggers":[],"owned_paths":["src/conductor/providers/claude.py"],'
    '"acceptance_checks":["pytest -q"],"new_task":true}</CONDUCTOR_TASK>'
)


def claude_task_payload(**tool_input):
    payload = {
        "session_id": "claude-run",
        "hook_event_name": "PreToolUse",
        "tool_name": "Task",
        "tool_input": {
            "subagent_type": "general-purpose",
            "model": "sonnet",
            "description": "Implement Claude support",
            "prompt": ENVELOPE + "\nDo the work.",
        },
    }
    payload["tool_input"].update(tool_input)
    return payload


def test_task_payload_normalizes_alias_and_emits_claude_decision() -> None:
    from conductor.providers.claude import PROVIDER

    normalized = PROVIDER.normalize_request(claude_task_payload())
    allowed = PROVIDER.emit_decision("approve", "approved")
    denied = PROVIDER.emit_decision("block", "denied")

    assert normalized.kind == "spawn"
    assert normalized.requested_model == "claude-sonnet-5"
    assert normalized.task_name == "impl_worker"
    assert normalized.envelope is not None
    assert normalized.envelope.task_class == "implementation"
    assert allowed["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert denied["hookSpecificOutput"]["permissionDecision"] == "deny"

    other = PROVIDER.normalize_request({"tool_name": "Bash", "tool_input": {}})
    assert other.kind == "other"


def test_caller_identity_comes_from_v2_run_and_reservation_not_fifo_events(
    tmp_path: Path,
) -> None:
    from conductor.providers.claude import PROVIDER

    home = tmp_path / "home"
    old = set_env(
        CODEX_CONDUCTOR_HOME=str(home), CODEX_CONDUCTOR_CONFIG=str(CLAUDE_CONFIG)
    )
    try:
        config = load_config()
        now = datetime.now(UTC)
        context = RunContext(
            provider="claude",
            run_id="claude-run",
            thread_id="claude-run",
            root_model="claude-opus-4-8",
            model_source="provider",
            provider_contract="claude-current",
            contract_digest="0" * 64,
            mode="routing",
            generation=1,
            started_at=now,
            heartbeat_at=now,
            config_digest=config_digest(config),
        )
        database = Store(home / "state" / "conductor.db")
        database.create_run(
            context.run_id,
            provider="claude",
            generation=1,
            mode="routing",
            context=context.model_dump(mode="json"),
        )
        assert database.reserve(
            request(
                "claude-run",
                "child-task",
                correlation_id="agent-1",
                model="claude-sonnet-5",
            ),
            concurrency_cap=4,
            budget_cap=10.0,
        ).allowed

        caller = PROVIDER.resolve_caller(
            {"session_id": "claude-run", "agent_id": "agent-1"}, config
        )
    finally:
        restore_env(old)

    assert caller.thread_id == "agent-1"
    assert caller.depth == 1
    assert caller.model == "claude-sonnet-5"
    assert caller.tier_index == 1


def test_unknown_claude_identity_never_fabricates_a_frontier_caller(
    tmp_path: Path,
) -> None:
    from conductor.providers.claude import PROVIDER

    old = set_env(
        CODEX_CONDUCTOR_HOME=str(tmp_path / "empty"),
        CODEX_CONDUCTOR_CONFIG=str(CLAUDE_CONFIG),
    )
    try:
        caller = PROVIDER.resolve_caller({"session_id": "claude-run"}, load_config())
    finally:
        restore_env(old)

    assert caller.model == ""
    assert caller.tier_index is None


def test_claude_hook_routes_alias_and_reserves_by_tool_use_id(
    tmp_path: Path,
) -> None:
    from conductor.hooks.pre_tool_use import decide

    config = load_config(CLAUDE_CONFIG)
    now = datetime.now(UTC)
    run = RunContext(
        provider="claude",
        run_id="claude-run",
        thread_id="claude-run",
        root_model="claude-opus-4-8",
        model_source="provider",
        provider_contract="claude-current",
        contract_digest="0" * 64,
        mode="routing",
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest=config_digest(config),
    )
    store = Store(tmp_path / "claude.db")
    store.create_run(
        run.run_id,
        provider="claude",
        generation=1,
        mode="routing",
        context=run.model_dump(mode="json"),
    )
    payload = {**claude_task_payload(), "tool_use_id": "tool-use-1"}

    decision = decide(
        payload,
        config,
        store,
        run,
        Caller("claude-run", "claude-run", 0, 0, "claude-opus-4-8"),
        (0, 1, 2),
        provider_name="claude",
    )

    assert decision.allowed is True
    assert decision.selected_model == "claude-sonnet-5"
    assert (
        store.reservation("tool-use-1", run_id="claude-run").model == "claude-sonnet-5"
    )


def test_claude_child_transcript_is_aggregated_and_parent_is_ignored(
    tmp_path: Path,
) -> None:
    from conductor.providers.claude import PROVIDER

    child = tmp_path / "child.jsonl"
    child.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-5",
                            "usage": {
                                "input_tokens": 100,
                                "cache_read_input_tokens": 20,
                                "cache_creation_input_tokens": 30,
                                "output_tokens": 40,
                            },
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-sonnet-5",
                            "usage": {"input_tokens": 10, "output_tokens": 5},
                        },
                    }
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    parent = tmp_path / "parent.jsonl"
    parent.write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "model": "claude-opus-4-8",
                    "usage": {"input_tokens": 999_999, "output_tokens": 999_999},
                },
            }
        )
        + "\n",
        encoding="utf-8",
    )

    terminal, cost = PROVIDER.normalize_lifecycle_events(
        {
            "hook_event_name": "SubagentStop",
            "session_id": "claude-run",
            "agent_id": "agent-1",
            "agent_transcript_path": str(child),
            "transcript_path": str(parent),
        },
        load_config(CLAUDE_CONFIG),
        reservation_model="claude-sonnet-5",
        reservation_estimate_usd=0.6,
    )

    assert terminal.correlation_id == "agent-1"
    assert cost.usage is not None
    assert cost.usage.input_tokens == 160
    assert cost.usage.cache_read_tokens == 20
    assert cost.usage.cache_write_tokens == 30
    assert cost.usage.output_tokens == 45
    # Packaged Claude prices are intentionally unknown, so the reserved estimate
    # is explicit instead of a fabricated measured-dollar value.
    assert cost.cost_usd == 0.6
    assert cost.estimated is True


def test_claude_post_tool_link_parser_is_exact_and_never_guesses() -> None:
    from conductor.providers.claude import PROVIDER

    link = PROVIDER.correlation_link(
        {
            "session_id": "run-1",
            "tool_use_id": "tool-1",
            "event_id": "event-1",
            "tool_response": {"agentId": "agent-1"},
        }
    )
    assert link is not None
    assert link.source_correlation == "tool-1"
    assert link.child_alias == "agent-1"
    assert link.source_event_id == "event-1"
    assert PROVIDER.correlation_link({"session_id": "run-1"}) is None
    assert PROVIDER.session_run_id({"root_thread_id": "root-1"}) == "root-1"

    # The outer agent id identifies the caller on Claude hooks, not the child
    # returned by the Task tool. It must never be guessed as the child.
    assert (
        PROVIDER.correlation_link(
            {
                "session_id": "run-1",
                "tool_use_id": "tool-1",
                "agent_id": "caller-agent",
            }
        )
        is None
    )


def test_claude_post_tool_default_event_id_is_bounded() -> None:
    from conductor.providers.claude import PROVIDER

    link = PROVIDER.correlation_link(
        {
            "session_id": "run-1",
            "tool_use_id": "t" * 128,
            "tool_response": {"agentId": "agent-1"},
        }
    )

    assert link is not None
    assert len(link.source_event_id) <= 128
