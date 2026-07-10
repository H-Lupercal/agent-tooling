from __future__ import annotations

from typing import Any

from conductor.schemas import (
    NormalizedOperation,
    OperationName,
    Provider,
    TaskEnvelopeV2,
)

_ALIASES = {
    "spawn_agent": OperationName.SPAWN,
    "task": OperationName.SPAWN,
    "assign_agent_task": OperationName.ASSIGN,
    "followup_task": OperationName.FOLLOWUP,
    "send_message": OperationName.MESSAGE,
    "send_agent_message": OperationName.MESSAGE,
}


def canonical_operation(raw_name: str) -> str:
    if not isinstance(raw_name, str):
        return OperationName.OTHER.value
    normalized = raw_name.strip().lower()
    if not normalized:
        return OperationName.OTHER.value
    leaf = normalized.rsplit(".", 1)[-1].rsplit("__", 1)[-1]
    return _ALIASES.get(leaf, OperationName.OTHER).value


def is_new_work(
    raw_name: str,
    payload: dict[str, Any],
    envelope: TaskEnvelopeV2 | None,
) -> bool:
    operation = canonical_operation(raw_name)
    if operation in {OperationName.SPAWN.value, OperationName.ASSIGN.value}:
        return True
    if operation not in {OperationName.FOLLOWUP.value, OperationName.MESSAGE.value}:
        return False
    if envelope is None or not envelope.new_task or envelope.operation_intent is None:
        return False
    message = payload.get("message")
    if not isinstance(message, str) or not message.strip():
        return False
    return envelope.operation_intent.value == operation


def normalize_operation(
    provider: str,
    raw_name: str,
    payload: dict[str, Any],
    envelope: TaskEnvelopeV2 | None = None,
) -> NormalizedOperation:
    operation = OperationName(canonical_operation(raw_name))
    correlation = _correlation_id(payload)
    return NormalizedOperation(
        provider=Provider(provider),
        operation=operation,
        raw_tool_name=raw_name,
        payload=payload,
        envelope=envelope,
        is_new_work=is_new_work(raw_name, payload, envelope),
        correlation_id=correlation,
    )


def _correlation_id(payload: dict[str, Any]) -> str | None:
    for key in (
        "correlation_id",
        "tool_call_id",
        "tool_use_id",
        "event_id",
        "task_id",
    ):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None
