"""Portable event receipts and replay-only run reconstruction."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from agent_harness.models import Event, event_to_json
from agent_harness.store import EventStore

_TERMINAL_RUN_KINDS = {"run.completed", "run.failed", "run.aborted"}
_TERMINAL_PARTICIPANT_KINDS = {"message.completed", "message.interrupted"}
_ACTIVE_PARTICIPANT_KINDS = {"message.started", "message.delta"}


@dataclass(frozen=True)
class ReconstructedRun:
    run_id: str
    terminal: bool
    participant_states: dict[str, str]
    last_sequence: int


def _atomic_write(output: Path, content: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)


def export_receipt(store: EventStore, run_id: str, output: Path) -> None:
    events = store.replay(run_id)
    if not events:
        raise ValueError(f"unknown run ID: {run_id}")
    _atomic_write(output, "".join(event_to_json(event) for event in events))


def reconstruct_run(events: list[Event]) -> ReconstructedRun:
    if not events or events[0].kind != "run.started":
        raise ValueError("run history does not begin with run.started")
    run_id = events[0].run_id
    states: dict[str, str] = {}
    terminal = False
    previous_sequence = 0
    for event in events:
        if event.run_id != run_id:
            raise ValueError("run history contains multiple run IDs")
        if event.sequence <= previous_sequence:
            raise ValueError("run history sequence is not strictly increasing")
        previous_sequence = event.sequence
        if event.kind in _TERMINAL_RUN_KINDS:
            terminal = True
        if event.kind in {"participant.joined", "participant.admitted"}:
            participant_id = event.payload.get("participant_id")
            if isinstance(participant_id, str):
                states[participant_id] = "active"
        elif event.actor in states and event.kind in _ACTIVE_PARTICIPANT_KINDS:
            states[event.actor] = "active"
        elif event.actor in states and event.kind in _TERMINAL_PARTICIPANT_KINDS:
            states[event.actor] = "terminal"
    return ReconstructedRun(run_id, terminal, states, events[-1].sequence)
