from __future__ import annotations

from copy import deepcopy

import pytest

from conductor.schemas import TaskEnvelopeV2
from tests.test_schemas import envelope_payload


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("spawn_agent", "spawn"),
        ("collaboration.spawn_agent", "spawn"),
        ("functions.collaboration.spawn_agent", "spawn"),
        ("mcp__collaboration__spawn_agent", "spawn"),
        ("Task", "spawn"),
        ("assign_agent_task", "assign"),
        ("collaboration.followup_task", "followup"),
        ("send_agent_message", "message"),
        ("collaboration.send_message", "message"),
    ],
)
def test_tool_names_are_canonicalized(raw: str, expected: str) -> None:
    from conductor.operations import canonical_operation

    assert canonical_operation(raw) == expected


@pytest.mark.parametrize("raw", ["", "shell", "collaboration.interrupt_agent"])
def test_unknown_tool_names_are_other(raw: str) -> None:
    from conductor.operations import canonical_operation

    assert canonical_operation(raw) == "other"


def test_spawn_and_assign_are_always_new_work() -> None:
    from conductor.operations import is_new_work

    assert is_new_work("spawn_agent", {}, None) is True
    assert is_new_work("assign_agent_task", {}, None) is True


def test_followup_and_message_are_new_work_only_with_matching_v2_envelope() -> None:
    from conductor.operations import is_new_work

    followup_payload = deepcopy(envelope_payload())
    followup_payload["operation_intent"] = "followup"
    followup = TaskEnvelopeV2.model_validate(followup_payload)

    message_payload = deepcopy(envelope_payload())
    message_payload["operation_intent"] = "message"
    message = TaskEnvelopeV2.model_validate(message_payload)

    assert (
        is_new_work("collaboration.followup_task", {"message": "feedback"}, None)
        is False
    )
    assert (
        is_new_work("collaboration.send_message", {"message": "feedback"}, None)
        is False
    )
    assert (
        is_new_work("collaboration.followup_task", {"message": "new task"}, followup)
        is True
    )
    assert (
        is_new_work("collaboration.send_message", {"message": "new task"}, message)
        is True
    )

    not_new_payload = deepcopy(message_payload)
    not_new_payload["new_task"] = False
    not_new = TaskEnvelopeV2.model_validate(not_new_payload)
    assert (
        is_new_work("collaboration.send_message", {"message": "feedback"}, not_new)
        is False
    )


def test_explicit_operation_intent_must_match_canonical_operation() -> None:
    from conductor.operations import is_new_work

    payload = deepcopy(envelope_payload())
    payload["operation_intent"] = "spawn"
    envelope = TaskEnvelopeV2.model_validate(payload)

    assert is_new_work("collaboration.followup_task", {}, envelope) is False


def test_outer_hook_correlation_is_preserved_for_exact_lifecycle_matching() -> None:
    from conductor.tool_adapter import normalize_governed_payload

    envelope = envelope_payload()
    payload = {
        "provider": "codex",
        "tool_call_id": "call-outer-1",
        "tool_name": "spawn_agent",
        "tool_input": {
            "task_name": "bounded-task",
            "model": "gpt-5.4",
            "message": (
                "<CONDUCTOR_TASK>"
                + __import__("json").dumps(envelope, separators=(",", ":"))
                + "</CONDUCTOR_TASK>"
            ),
        },
    }

    result = normalize_governed_payload(payload)

    assert result.operation is not None
    assert result.operation.correlation_id == "call-outer-1"


def test_plain_feedback_never_requires_a_new_task_envelope() -> None:
    from conductor.tool_adapter import normalize_governed_payload

    result = normalize_governed_payload(
        {
            "provider": "codex",
            "tool_name": "collaboration.send_message",
            "tool_input": {"target": "agent-1", "message": "please clarify"},
        }
    )

    assert result.operation is not None
    assert result.operation.is_new_work is False
    assert result.decision.allowed is True
    assert result.decision.rule == "NOT_GOVERNED"


def test_invalid_outer_correlation_never_bypasses_strict_operation_validation() -> None:
    from conductor.tool_adapter import normalize_governed_payload

    payload = {
        "provider": "codex",
        "tool_call_id": "../not-an-id",
        "tool_name": "spawn_agent",
        "tool_input": {
            "message": (
                "<CONDUCTOR_TASK>"
                + __import__("json").dumps(envelope_payload(), separators=(",", ":"))
                + "</CONDUCTOR_TASK>"
            )
        },
    }

    result = normalize_governed_payload(payload)

    assert result.operation is not None
    assert result.operation.correlation_id is None
