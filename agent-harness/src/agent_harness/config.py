"""Strict project configuration for the collaboration harness."""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import cast

from agent_harness.models import CapacityPolicy, Participant

_ENVIRONMENT_VARIABLE = re.compile(r"[A-Z_][A-Z0-9_]*\Z")


@dataclass(frozen=True)
class HarnessConfig:
    participants: tuple[Participant, ...]
    capacity: CapacityPolicy
    total_token_budget: int
    queue_size: int
    credential_env: Mapping[str, str]


def _reject_unknown_keys(value: Mapping[str, object], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"unknown {label} key: {unknown[0]}")


def _mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a TOML table")
    return cast(dict[str, object], value)


def _positive_integer(value: object, label: str) -> int:
    if type(value) is not int or value <= 0:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _nonnegative_integer(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a nonnegative integer")
    return value


def _required_string(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _parse_participants(value: object) -> tuple[tuple[Participant, ...], dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise ValueError("participants must be a nonempty array of tables")
    participant_values = cast(list[object], value)
    participants: list[Participant] = []
    credentials: dict[str, str] = {}
    seen: set[str] = set()
    for index, raw in enumerate(participant_values):
        participant = _mapping(raw, f"participant {index}")
        _reject_unknown_keys(
            participant,
            {"id", "adapter", "model", "roles", "context_limit", "credential_env"},
            "participant",
        )
        participant_id = _required_string(participant.get("id"), "participant ID")
        if participant_id in seen:
            raise ValueError(f"duplicate participant ID: {participant_id}")
        roles_raw = participant.get("roles")
        if not isinstance(roles_raw, list) or not roles_raw:
            raise ValueError("participant roles must be a nonempty array")
        role_values = cast(list[object], roles_raw)
        roles = tuple(_required_string(role, "participant role") for role in role_values)
        parsed = Participant(
            participant_id=participant_id,
            adapter=_required_string(participant.get("adapter"), "participant adapter"),
            model=_required_string(participant.get("model"), "participant model"),
            roles=roles,
            context_limit=_positive_integer(
                participant.get("context_limit"), "participant context limit"
            ),
            parent_id=None,
        )
        credential = participant.get("credential_env")
        if credential is not None:
            credential_name = _required_string(credential, "credential environment variable")
            if not _ENVIRONMENT_VARIABLE.fullmatch(credential_name):
                raise ValueError("credential environment variable must be an uppercase name")
            credentials[participant_id] = credential_name
        participants.append(parsed)
        seen.add(participant_id)
    return tuple(participants), credentials


def _parse_capacity(value: object) -> CapacityPolicy:
    capacity = _mapping(value, "capacity")
    allowed = {
        "max_participants",
        "max_dynamic_children",
        "max_children_per_parent",
        "max_spawn_depth",
        "max_simultaneous_speakers",
    }
    _reject_unknown_keys(capacity, allowed, "capacity")
    missing = sorted(allowed - set(capacity))
    if missing:
        raise ValueError(f"missing capacity key: {missing[0]}")
    return CapacityPolicy(
        max_participants=_positive_integer(capacity["max_participants"], "participant capacity"),
        max_dynamic_children=_nonnegative_integer(
            capacity["max_dynamic_children"], "dynamic child capacity"
        ),
        max_children_per_parent=_nonnegative_integer(
            capacity["max_children_per_parent"], "children-per-parent capacity"
        ),
        max_spawn_depth=_nonnegative_integer(capacity["max_spawn_depth"], "spawn depth"),
        max_simultaneous_speakers=_positive_integer(
            capacity["max_simultaneous_speakers"], "simultaneous speaker capacity"
        ),
    )


def load_config(path: Path) -> HarnessConfig:
    with path.open("rb") as handle:
        raw = cast(dict[str, object], tomllib.load(handle))
    allowed = {"participants", "capacity", "budgets", "room"}
    _reject_unknown_keys(raw, allowed, "root")
    missing = sorted(allowed - set(raw))
    if missing:
        raise ValueError(f"missing root key: {missing[0]}")

    participants, credentials = _parse_participants(raw["participants"])
    capacity = _parse_capacity(raw["capacity"])
    if capacity.max_participants < len(participants):
        raise ValueError("participant capacity is below the configured root roster")

    budgets = _mapping(raw["budgets"], "budgets")
    _reject_unknown_keys(budgets, {"tokens"}, "budgets")
    room = _mapping(raw["room"], "room")
    _reject_unknown_keys(room, {"queue_size"}, "room")
    return HarnessConfig(
        participants=participants,
        capacity=capacity,
        total_token_budget=_positive_integer(budgets.get("tokens"), "token budget"),
        queue_size=_positive_integer(room.get("queue_size"), "queue size"),
        credential_env=MappingProxyType(credentials),
    )
