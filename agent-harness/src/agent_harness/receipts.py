"""Portable event receipts and replay-only run reconstruction."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from agent_harness.models import Event, event_to_json
from agent_harness.store import EventStore

_TERMINAL_RUN_KINDS = {"run.completed", "run.failed", "run.aborted"}
_TERMINAL_PARTICIPANT_KINDS = {"message.completed", "message.interrupted"}
_ACTIVE_PARTICIPANT_KINDS = {"message.started", "message.delta"}


@dataclass(frozen=True)
class ReconstructedParticipant:
    participant_id: str
    adapter: str
    model: str
    roles: tuple[str, ...]
    context_limit: int
    parent_id: str | None
    context: tuple[str, ...]
    token_budget: int


@dataclass(frozen=True)
class ReconstructedRun:
    run_id: str
    terminal: bool
    participant_states: dict[str, str]
    participants: dict[str, ReconstructedParticipant]
    consumed_token_budget: int
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
    participants: dict[str, ReconstructedParticipant] = {}
    consumed_token_budget = 0
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
                snapshot = _participant_snapshot(event)
                if snapshot is not None:
                    participants[participant_id] = snapshot
            if event.kind == "participant.admitted":
                token_budget = event.payload.get("token_budget", 0)
                if type(token_budget) is not int or token_budget < 0:
                    raise ValueError("admitted participant has invalid token budget")
                consumed_token_budget += token_budget
        elif event.actor in states and event.kind in _ACTIVE_PARTICIPANT_KINDS:
            states[event.actor] = "active"
        elif event.actor in states and event.kind in _TERMINAL_PARTICIPANT_KINDS:
            states[event.actor] = "terminal"
        elif event.kind == "participant.degraded":
            participant_id = event.payload.get("participant_id")
            if isinstance(participant_id, str) and participant_id in states:
                states[participant_id] = "terminal"
    return ReconstructedRun(
        run_id,
        terminal,
        states,
        participants,
        consumed_token_budget,
        events[-1].sequence,
    )


def _participant_snapshot(event: Event) -> ReconstructedParticipant | None:
    participant_id = event.payload.get("participant_id")
    adapter = event.payload.get("adapter")
    model = event.payload.get("model")
    roles = event.payload.get("roles")
    context_limit = event.payload.get("context_limit")
    parent_id = event.payload.get("parent_id")
    if not (
        isinstance(participant_id, str)
        and isinstance(adapter, str)
        and isinstance(model, str)
        and isinstance(roles, tuple)
        and all(isinstance(role, str) for role in cast(tuple[object, ...], roles))
        and type(context_limit) is int
        and context_limit > 0
        and (parent_id is None or isinstance(parent_id, str))
    ):
        return None
    parsed_roles = cast(tuple[str, ...], roles)
    context_value = event.payload.get("context", ())
    if not isinstance(context_value, tuple) or not all(
        isinstance(item, str) for item in cast(tuple[object, ...], context_value)
    ):
        raise ValueError("participant context is invalid")
    parsed_context = cast(tuple[str, ...], context_value)
    token_budget = event.payload.get("token_budget", 0)
    if type(token_budget) is not int or token_budget < 0:
        raise ValueError("participant token budget is invalid")
    return ReconstructedParticipant(
        participant_id,
        adapter,
        model,
        parsed_roles,
        context_limit,
        parent_id,
        parsed_context,
        token_budget,
    )
