import json
from dataclasses import replace
from pathlib import Path

import pytest

from agent_harness.models import CapacityPolicy, Event
from agent_harness.receipts import export_receipt, reconstruct_run
from agent_harness.store import EventStore


def _event(run_id: str, kind: str, actor: str = "runtime") -> Event:
    return replace(Event.example(run_id), kind=kind, actor=actor)


def test_receipt_export_is_replayable(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")
    store.append(_event("run-1", "run.started", "user"))
    store.append(_event("run-1", "participant.joined"))
    store.append(_event("run-1", "run.completed"))
    output = tmp_path / "receipt.jsonl"

    export_receipt(store, "run-1", output)

    lines = output.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2, 3]


def test_receipt_export_refuses_unknown_run(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.db")

    with pytest.raises(ValueError, match="unknown run ID"):
        export_receipt(store, "missing", tmp_path / "receipt.jsonl")


def test_reconstruct_run_tracks_terminal_participants() -> None:
    events = [
        replace(_event("run-1", "run.started", "user"), sequence=1),
        replace(
            _event("run-1", "participant.joined"),
            sequence=2,
            payload={"participant_id": "builder"},
        ),
        replace(_event("run-1", "message.started", "builder"), sequence=3),
        replace(_event("run-1", "message.completed", "builder"), sequence=4),
        replace(
            _event("run-1", "participant.joined"),
            sequence=5,
            payload={"participant_id": "reviewer"},
        ),
    ]

    reconstructed = reconstruct_run(events)

    assert not reconstructed.terminal
    assert reconstructed.participant_states == {
        "builder": "terminal",
        "reviewer": "active",
    }
    assert reconstructed.last_sequence == 5


def test_reconstruct_run_rejects_history_without_start() -> None:
    with pytest.raises(ValueError, match="does not begin"):
        reconstruct_run([_event("run-1", "run.completed")])


def test_reconstruct_run_restores_roster_lineage_context_and_spent_budget() -> None:
    events = [
        replace(
            _event("run-1", "run.started", "user"),
            sequence=1,
            payload={
                "goal": "recover",
                "capacity": {
                    "max_participants": 4,
                    "max_dynamic_children": 2,
                    "max_children_per_parent": 1,
                    "max_spawn_depth": 1,
                    "max_simultaneous_speakers": 2,
                },
                "total_token_budget": 1000,
            },
        ),
        replace(
            _event("run-1", "participant.joined"),
            sequence=2,
            payload={
                "participant_id": "builder",
                "adapter": "fake",
                "model": "offline-builder",
                "roles": ["builder"],
                "context_limit": 8000,
                "parent_id": None,
            },
        ),
        replace(
            _event("run-1", "participant.admitted"),
            sequence=3,
            payload={
                "participant_id": "builder/tester-1",
                "adapter": "fake",
                "model": "offline-builder",
                "roles": ["tester"],
                "context_limit": 8000,
                "parent_id": "builder",
                "context": ["selected evidence"],
                "token_budget": 300,
            },
        ),
    ]

    reconstructed = reconstruct_run(events)

    child = reconstructed.participants["builder/tester-1"]
    assert child.parent_id == "builder"
    assert child.context == ("selected evidence",)
    assert reconstructed.consumed_token_budget == 300
    assert reconstructed.capacity == CapacityPolicy(4, 2, 1, 1, 2)
    assert reconstructed.total_token_budget == 1000


def test_reconstruct_run_rejects_mixed_ids_sequences_and_invalid_child_budget() -> None:
    started = replace(_event("run-1", "run.started", "user"), sequence=1)
    with pytest.raises(ValueError, match="multiple run IDs"):
        reconstruct_run([started, replace(_event("run-2", "run.completed"), sequence=2)])
    with pytest.raises(ValueError, match="strictly increasing"):
        reconstruct_run([started, replace(_event("run-1", "run.completed"), sequence=1)])
    with pytest.raises(ValueError, match="invalid token budget"):
        reconstruct_run(
            [
                started,
                replace(
                    _event("run-1", "participant.admitted"),
                    sequence=2,
                    payload={"participant_id": "child", "token_budget": -1},
                ),
            ]
        )
