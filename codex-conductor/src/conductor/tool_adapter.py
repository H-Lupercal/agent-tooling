from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError

from conductor.operations import canonical_operation, is_new_work, normalize_operation
from conductor.schemas import (
    Decision,
    NormalizedOperation,
    OperatingMode,
    OperationName,
    TaskEnvelopeV2,
)

START = "<CONDUCTOR_TASK>"
END = "</CONDUCTOR_TASK>"
MAX_ENVELOPE_BYTES = 16_384
MAX_MESSAGE_BYTES = 65_536

TaskEnvelope = TaskEnvelopeV2
EnvelopeKind = Literal["valid", "missing", "invalid", "oversized"]


@dataclass(frozen=True)
class EnvelopeParseResult:
    kind: EnvelopeKind
    envelope: TaskEnvelopeV2 | None = None
    error: str | None = None


@dataclass(frozen=True)
class ToolRequest:
    kind: str
    tool_name: str
    requested_model: str | None
    task_name: str | None
    envelope: TaskEnvelopeV2 | None
    requested_effort: str | None = None


@dataclass(frozen=True)
class GovernedPayloadResult:
    parse: EnvelopeParseResult
    operation: NormalizedOperation | None
    decision: Decision


def parse_envelope_bytes(data: bytes) -> EnvelopeParseResult:
    if not isinstance(data, bytes):
        return EnvelopeParseResult("invalid", error="envelope input must be bytes")
    if len(data) > MAX_MESSAGE_BYTES:
        return EnvelopeParseResult(
            "oversized", error="governed message exceeds size limit"
        )
    try:
        text = data.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return EnvelopeParseResult(
            "invalid", error="governed message is not valid UTF-8"
        )

    starts = text.count(START)
    ends = text.count(END)
    if starts == 0 and ends == 0:
        return EnvelopeParseResult(
            "missing", error="conductor task envelope is missing"
        )
    if starts != 1 or ends != 1:
        return EnvelopeParseResult(
            "invalid", error="exactly one conductor task envelope is required"
        )

    start = text.find(START)
    end = text.find(END)
    if start < 0 or end < start + len(START):
        return EnvelopeParseResult(
            "invalid", error="conductor task envelope tags are malformed"
        )
    raw = text[start + len(START) : end]
    if len(raw.encode("utf-8")) > MAX_ENVELOPE_BYTES:
        return EnvelopeParseResult(
            "oversized", error="conductor task envelope exceeds size limit"
        )
    raw = raw.strip()
    if not raw:
        return EnvelopeParseResult("invalid", error="conductor task envelope is empty")

    try:
        parsed = json.loads(raw, object_pairs_hook=_unique_object)
    except (json.JSONDecodeError, DuplicateJsonKey):
        return EnvelopeParseResult(
            "invalid", error="conductor task envelope is not unique valid JSON"
        )
    if not isinstance(parsed, dict):
        return EnvelopeParseResult(
            "invalid", error="conductor task envelope must be a JSON object"
        )
    if _contains_invalid_unicode(parsed):
        return EnvelopeParseResult(
            "invalid", error="conductor task envelope contains invalid Unicode"
        )
    try:
        envelope = TaskEnvelopeV2.model_validate(parsed)
    except ValidationError as exc:
        return EnvelopeParseResult(
            "invalid", error=f"conductor task envelope failed validation: {exc}"
        )
    return EnvelopeParseResult("valid", envelope=envelope)


def extract_envelope(text: str) -> TaskEnvelopeV2 | None:
    if not isinstance(text, str):
        return None
    try:
        encoded = text.encode("utf-8", errors="strict")
    except UnicodeEncodeError:
        return None
    result = parse_envelope_bytes(encoded)
    return result.envelope if result.kind == "valid" else None


def normalize_tool_request(payload: dict, schema: dict | None = None) -> ToolRequest:
    del schema
    tool_name = str(payload.get("tool_name") or payload.get("name") or "")
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    operation = canonical_operation(tool_name)
    envelope = (
        extract_envelope(_prompt_text(tool_input)) if operation != "other" else None
    )
    if operation == "spawn":
        kind = "spawn"
    elif operation == "assign":
        kind = "new_task"
    elif operation in {"followup", "message"}:
        kind = (
            "new_task" if is_new_work(tool_name, tool_input, envelope) else "feedback"
        )
    else:
        kind = "other"
    requested_model = _first_string(
        tool_input, ("model", "model_slug", "requested_model")
    )
    requested_effort = _first_string(
        tool_input, ("reasoning_effort", "model_reasoning_effort")
    )
    task_name = _first_string(tool_input, ("task_name", "name"))
    if envelope is not None:
        task_name = task_name or envelope.task_name
    return ToolRequest(
        kind=kind,
        tool_name=tool_name,
        requested_model=requested_model,
        task_name=task_name,
        envelope=envelope,
        requested_effort=requested_effort,
    )


def normalize_governed_payload(payload: object) -> GovernedPayloadResult:
    if not isinstance(payload, dict):
        parse = EnvelopeParseResult(
            "invalid", error="provider payload must be an object"
        )
        return GovernedPayloadResult(
            parse, None, _normalization_decision("INVALID_ENVELOPE", False)
        )

    tool_name = str(payload.get("tool_name") or payload.get("name") or "")
    operation_name = canonical_operation(tool_name)
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    prompt = _prompt_text(tool_input)
    try:
        parse = parse_envelope_bytes(prompt.encode("utf-8", errors="strict"))
    except UnicodeEncodeError:
        parse = EnvelopeParseResult(
            "invalid", error="governed message contains invalid Unicode"
        )

    operation: NormalizedOperation | None = None
    if operation_name != "other":
        provider = payload.get("provider")
        provider_name = provider if provider in {"codex", "claude"} else "codex"
        operation = normalize_operation(
            provider_name, tool_name, tool_input, parse.envelope
        )
        outer_correlation = _first_string(
            payload,
            (
                "correlation_id",
                "tool_call_id",
                "tool_use_id",
                "event_id",
                "task_id",
            ),
        )
        candidate = operation.model_dump(mode="python")
        candidate["correlation_id"] = outer_correlation
        try:
            operation = NormalizedOperation.model_validate(candidate)
        except ValidationError:
            # Provider correlation is a trust boundary. Never fall back to a
            # user-controlled id embedded in the tool input.
            candidate["correlation_id"] = None
            operation = NormalizedOperation.model_validate(candidate)

    if operation_name == "other":
        return GovernedPayloadResult(
            parse,
            operation,
            _normalization_decision("NOT_GOVERNED", True, OperationName.OTHER),
        )
    if operation is not None and not operation.is_new_work:
        return GovernedPayloadResult(
            parse,
            operation,
            _normalization_decision(
                "NOT_GOVERNED", True, OperationName(operation_name)
            ),
        )
    if parse.kind == "missing":
        return GovernedPayloadResult(
            parse,
            operation,
            _normalization_decision(
                "MISSING_ENVELOPE", False, OperationName(operation_name)
            ),
        )
    if parse.kind == "oversized":
        return GovernedPayloadResult(
            parse,
            operation,
            _normalization_decision(
                "ENVELOPE_OVERSIZED", False, OperationName(operation_name)
            ),
        )
    if parse.kind != "valid":
        return GovernedPayloadResult(
            parse,
            operation,
            _normalization_decision(
                "INVALID_ENVELOPE", False, OperationName(operation_name)
            ),
        )
    return GovernedPayloadResult(
        parse,
        operation,
        _normalization_decision("NORMALIZED", True, OperationName(operation_name)),
    )


def _normalization_decision(
    rule: str,
    allowed: bool,
    operation: OperationName = OperationName.OTHER,
) -> Decision:
    return Decision(
        decision_id="normalization",
        allowed=allowed,
        rule=rule,
        message="governed payload normalized"
        if allowed
        else rule.replace("_", " ").lower(),
        mode=OperatingMode.ADMISSION,
        operation=operation,
        selected_model=None,
        reservation_estimate_usd=0.0,
        savings_eligible=False,
        reservation_id=None,
        created_at=datetime.now(UTC),
    )


def _first_string(data: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = data.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _prompt_text(tool_input: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ("message", "prompt", "task", "instructions", "content"):
        value = tool_input.get(key)
        if isinstance(value, str):
            parts.append(value)
    items = tool_input.get("items")
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
    return "\n".join(parts)


class DuplicateJsonKey(ValueError):
    pass


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def _contains_invalid_unicode(value: object) -> bool:
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, list):
        return any(_contains_invalid_unicode(item) for item in value)
    if isinstance(value, dict):
        return any(
            _contains_invalid_unicode(key) or _contains_invalid_unicode(item)
            for key, item in value.items()
        )
    return False
