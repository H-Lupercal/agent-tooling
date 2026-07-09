from __future__ import annotations

import json

import pytest
from hypothesis import given, strategies as st

from tests.test_schemas import envelope_payload


def raw_spawn_with_envelope(payload: object) -> dict:
    return {
        "provider": "codex",
        "tool_name": "collaboration.spawn_agent",
        "tool_input": {
            "task_name": "tests_ledger",
            "message": (
                "<CONDUCTOR_TASK>"
                + json.dumps(payload, ensure_ascii=False)
                + "</CONDUCTOR_TASK>"
            ),
        },
    }


@pytest.mark.parametrize("payload", [None, [], 1, "text", {"unknown": True}])
def test_malformed_governed_envelope_is_controlled_denial(payload: object) -> None:
    from conductor.tool_adapter import normalize_governed_payload

    result = normalize_governed_payload(raw_spawn_with_envelope(payload))

    assert result.decision.rule == "INVALID_ENVELOPE"
    assert result.decision.allowed is False


def test_valid_envelope_normalizes_governed_operation() -> None:
    from conductor.tool_adapter import normalize_governed_payload

    result = normalize_governed_payload(raw_spawn_with_envelope(envelope_payload()))

    assert result.parse.kind == "valid"
    assert result.operation is not None
    assert result.operation.operation == "spawn"
    assert result.operation.envelope is not None
    assert result.operation.envelope.task_name == "tests_ledger"
    assert result.decision.allowed is True


@pytest.mark.parametrize(
    ("raw", "kind"),
    [
        (b"ordinary feedback", "missing"),
        (b"<CONDUCTOR_TASK>{not json}</CONDUCTOR_TASK>", "invalid"),
        (b"<CONDUCTOR_TASK>null</CONDUCTOR_TASK>", "invalid"),
        (
            b"<CONDUCTOR_TASK>{}</CONDUCTOR_TASK><CONDUCTOR_TASK>{}</CONDUCTOR_TASK>",
            "invalid",
        ),
        (b"</CONDUCTOR_TASK>", "invalid"),
        (b"\xff<CONDUCTOR_TASK>{}</CONDUCTOR_TASK>", "invalid"),
        (b"<CONDUCTOR_TASK>" + b" " * 20_000 + b"</CONDUCTOR_TASK>", "oversized"),
    ],
)
def test_parser_classifies_missing_invalid_duplicate_unicode_and_oversized(
    raw: bytes,
    kind: str,
) -> None:
    from conductor.tool_adapter import parse_envelope_bytes

    assert parse_envelope_bytes(raw).kind == kind


@pytest.mark.parametrize(
    "change",
    [
        {"schema_version": 99},
        {"new_task": 1},
        {"extra": True},
        {"owned_paths": ["/absolute"]},
        {"owned_paths": ["../escape"]},
        {"owned_paths": ["nested/../escape"]},
        {"owned_paths": []},
        {"acceptance_checks": []},
    ],
)
def test_strict_envelope_shape_and_paths_are_rejected(change: dict) -> None:
    from conductor.tool_adapter import parse_envelope_bytes

    payload = envelope_payload()
    payload.update(change)
    raw = (
        "<CONDUCTOR_TASK>"
        + json.dumps(payload, separators=(",", ":"))
        + "</CONDUCTOR_TASK>"
    ).encode()

    result = parse_envelope_bytes(raw)

    assert result.kind == "invalid"
    assert result.envelope is None


def test_duplicate_json_keys_are_rejected() -> None:
    from conductor.tool_adapter import parse_envelope_bytes

    raw = (
        b'<CONDUCTOR_TASK>{"schema_version":1,"schema_version":1,'
        b'"task_name":"x","task_class":"tests","risk_triggers":[],'
        b'"owned_paths":["x"],"acceptance_checks":["check"],'
        b'"new_task":true}</CONDUCTOR_TASK>'
    )

    assert parse_envelope_bytes(raw).kind == "invalid"


@given(st.binary(max_size=65536))
def test_envelope_parser_never_raises_unclassified(data: bytes) -> None:
    from conductor.tool_adapter import parse_envelope_bytes

    result = parse_envelope_bytes(data)
    assert result.kind in {"valid", "missing", "invalid", "oversized"}
