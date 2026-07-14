from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agent_harness.models import (
    CapacityPolicy,
    ChildRequest,
    Event,
    Participant,
    event_from_json,
    event_to_json,
)


def test_event_round_trip_is_canonical() -> None:
    event = Event(
        schema_version=1,
        run_id="run-1",
        sequence=1,
        occurred_at=datetime(2026, 7, 14, tzinfo=UTC),
        actor="user",
        kind="run.started",
        causation_id=None,
        correlation_id="goal-1",
        payload={"goal": "repair parser"},
    )

    assert event_from_json(event_to_json(event)) == event
    assert event_to_json(event) == event_to_json(event_from_json(event_to_json(event)))


def test_event_rejects_unsafe_identifiers() -> None:
    with pytest.raises(ValueError, match="run ID"):
        Event.example(run_id="../escape")


def test_participant_requires_positive_context_limit() -> None:
    with pytest.raises(ValueError, match="context limit"):
        Participant("reviewer", "fake", "fake-v1", (), 0, None)


def test_capacity_policy_rejects_invalid_limits() -> None:
    with pytest.raises(ValueError, match="participant capacity"):
        CapacityPolicy(0, 0, 0, 0, 1)
    with pytest.raises(ValueError, match="dynamic child"):
        CapacityPolicy(1, -1, 0, 0, 1)
    with pytest.raises(ValueError, match="children per parent"):
        CapacityPolicy(1, 0, -1, 0, 1)
    with pytest.raises(ValueError, match="spawn depth"):
        CapacityPolicy(1, 0, 0, -1, 1)
    with pytest.raises(ValueError, match="simultaneous speaker"):
        CapacityPolicy(1, 0, 0, 0, 0)


def test_child_request_rejects_invalid_role_objective_and_budget() -> None:
    with pytest.raises(ValueError, match="child role"):
        ChildRequest("../unsafe", "test", (), 1)
    with pytest.raises(ValueError, match="objective"):
        ChildRequest("tester", " ", (), 1)
    with pytest.raises(ValueError, match="token budget"):
        ChildRequest("tester", "test", (), 0)


def test_event_rejects_invalid_contract_fields() -> None:
    example = Event.example("run-1")
    with pytest.raises(ValueError, match="schema version"):
        replace(example, schema_version=2)
    with pytest.raises(ValueError, match="sequence"):
        replace(example, sequence=0)
    with pytest.raises(ValueError, match="timezone-aware"):
        replace(example, occurred_at=datetime(2026, 7, 14))
