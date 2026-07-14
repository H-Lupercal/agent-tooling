"""Immutable, versioned event and participant contracts."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import cast

_IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,255}\Z")


def _identifier(value: str, label: str) -> str:
    if not _IDENTIFIER.fullmatch(value) or ".." in value.split("/"):
        raise ValueError(f"{label} must be a safe identifier")
    return value


@dataclass(frozen=True)
class Participant:
    participant_id: str
    adapter: str
    model: str
    roles: tuple[str, ...]
    context_limit: int
    parent_id: str | None

    def __post_init__(self) -> None:
        _identifier(self.participant_id, "participant ID")
        if self.context_limit <= 0:
            raise ValueError("context limit must be positive")


@dataclass(frozen=True)
class CapacityPolicy:
    max_participants: int
    max_dynamic_children: int
    max_children_per_parent: int
    max_spawn_depth: int
    max_simultaneous_speakers: int

    def __post_init__(self) -> None:
        if self.max_participants <= 0:
            raise ValueError("participant capacity must be positive")
        for label, value in (
            ("dynamic child capacity", self.max_dynamic_children),
            ("children per parent", self.max_children_per_parent),
            ("spawn depth", self.max_spawn_depth),
        ):
            if value < 0:
                raise ValueError(f"{label} cannot be negative")
        if self.max_simultaneous_speakers <= 0:
            raise ValueError("simultaneous speaker limit must be positive")


@dataclass(frozen=True)
class ChildRequest:
    role: str
    objective: str
    context: tuple[str, ...]
    token_budget: int

    def __post_init__(self) -> None:
        _identifier(self.role, "child role")
        if not self.objective.strip():
            raise ValueError("child objective cannot be empty")
        if self.token_budget <= 0:
            raise ValueError("child token budget must be positive")


@dataclass(frozen=True)
class Event:
    schema_version: int
    run_id: str
    sequence: int
    occurred_at: datetime
    actor: str
    kind: str
    causation_id: str | None
    correlation_id: str
    payload: dict[str, object]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported event schema version")
        _identifier(self.run_id, "run ID")
        _identifier(self.actor, "actor")
        _identifier(self.kind, "event kind")
        _identifier(self.correlation_id, "correlation ID")
        if self.sequence < 1:
            raise ValueError("event sequence must be positive")
        if self.occurred_at.tzinfo is None:
            raise ValueError("event timestamp must be timezone-aware")

    @classmethod
    def example(cls, run_id: str) -> Event:
        return cls(
            schema_version=1,
            run_id=run_id,
            sequence=1,
            occurred_at=datetime.now(UTC),
            actor="user",
            kind="run.started",
            causation_id=None,
            correlation_id="goal",
            payload={},
        )


def event_to_json(event: Event) -> str:
    value = cast(dict[str, object], asdict(event))
    value["occurred_at"] = event.occurred_at.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n"


def event_from_json(raw: str) -> Event:
    value = cast(dict[str, object], json.loads(raw))
    occurred_at = datetime.fromisoformat(str(value["occurred_at"]).replace("Z", "+00:00"))
    payload = cast(dict[str, object], value["payload"])
    return Event(
        schema_version=int(str(value["schema_version"])),
        run_id=str(value["run_id"]),
        sequence=int(str(value["sequence"])),
        occurred_at=occurred_at,
        actor=str(value["actor"]),
        kind=str(value["kind"]),
        causation_id=(None if value["causation_id"] is None else str(value["causation_id"])),
        correlation_id=str(value["correlation_id"]),
        payload=payload,
    )
