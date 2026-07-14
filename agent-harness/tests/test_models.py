from datetime import UTC, datetime

import pytest

from agent_harness.models import Event, Participant, event_from_json, event_to_json


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
