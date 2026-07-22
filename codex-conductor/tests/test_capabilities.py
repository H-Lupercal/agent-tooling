from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from conductor.schemas import CapabilityContract, OperatingMode

FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_current_codex_contract_routes_verified_model_and_effort_fields() -> None:
    from conductor.capabilities import load_contract, negotiate

    contract = load_contract("codex-current")
    result = negotiate(contract, fixture("codex-spawn"))

    assert result.mode == OperatingMode.ROUTING
    assert result.child_model_selectable is True
    spawn = next(tool for tool in contract.tools if tool.canonical_name == "spawn")
    properties = spawn.input_schema["properties"]
    assert properties["model"]["enum"] == ["gpt-5.6-sol", "gpt-5.6-terra"]
    assert properties["reasoning_effort"]["enum"] == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ]
    assert contract.model_selector_path == "model"
    assert contract.reasoning_effort_selector_path == "reasoning_effort"


def test_codex_contract_without_effort_control_cannot_claim_routing() -> None:
    from conductor.capabilities import contract_mode, load_contract

    contract = load_contract("codex-current")
    missing_declaration = contract.model_copy(
        update={"reasoning_effort_selector_path": None}
    )
    spawn = next(tool for tool in contract.tools if tool.canonical_name == "spawn")
    properties = dict(spawn.input_schema["properties"])
    properties.pop("reasoning_effort")
    missing_schema = contract.model_copy(
        update={
            "tools": tuple(
                tool.model_copy(
                    update={
                        "input_schema": {
                            **tool.input_schema,
                            "properties": properties,
                        }
                    }
                )
                if tool.canonical_name == "spawn"
                else tool
                for tool in contract.tools
            )
        }
    )

    assert contract_mode(missing_declaration) is OperatingMode.ADMISSION
    assert contract_mode(missing_schema) is OperatingMode.UNSUPPORTED


def test_claude_keeps_existing_model_only_routing_contract() -> None:
    from conductor.capabilities import contract_mode, load_contract

    contract = load_contract("claude-current")

    assert contract.reasoning_effort_selector_path is None
    assert contract_mode(contract) is OperatingMode.ROUTING


def test_current_codex_contract_declares_current_hook_wire_fields() -> None:
    from conductor.capabilities import load_contract

    contract = load_contract("codex-current")

    assert contract.cli_version_range.minimum == "0.144.0"
    assert contract.correlation_fields.run_id[0] == "session_id"
    assert "tool_use_id" in contract.correlation_fields.lifecycle_id
    assert "agent_id" in contract.correlation_fields.child_id
    assert contract.decision_response_schema["required"] == ["hookSpecificOutput"]


def test_payload_field_absent_from_checked_contract_is_not_assumed() -> None:
    from conductor.capabilities import load_contract, negotiate

    result = negotiate(load_contract("codex-current"), fixture("codex-spawn-drift"))

    assert result.mode == OperatingMode.UNSUPPORTED
    assert result.child_model_selectable is False
    assert "does not match" in result.reason


def test_verified_claude_model_selector_selects_routing() -> None:
    from conductor.capabilities import load_contract, negotiate

    result = negotiate(load_contract("claude-current"), fixture("claude-task"))

    assert result.mode == OperatingMode.ROUTING
    assert result.child_model_selectable is True
    assert result.matched_operation == "spawn"


def test_packaged_contracts_match_checked_in_golden_fixtures() -> None:
    from conductor.capabilities import contract_digest, load_contract

    for name in ("codex-current", "claude-current"):
        expected = CapabilityContract.model_validate(fixture(name))
        installed = load_contract(name)
        packaged = json.loads(
            files("conductor.assets")
            .joinpath("contracts", f"{name}.json")
            .read_text(encoding="utf-8")
        )

        assert installed == expected
        assert packaged == fixture(name)
        assert len(contract_digest(installed)) == 64


def test_contract_digest_drift_is_unsupported() -> None:
    from conductor.capabilities import load_contract, negotiate

    installed = load_contract("codex-current")
    payload = installed.model_dump(mode="python")
    payload["trust_visibility"] = False
    drifted = CapabilityContract.model_validate(payload)

    result = negotiate(drifted, fixture("codex-spawn"))

    assert result.mode == OperatingMode.UNSUPPORTED
    assert "digest drift" in result.reason


@pytest.mark.parametrize(
    ("value", "schema", "expected"),
    [
        ("x", {"type": "string", "minLength": 1, "maxLength": 2}, True),
        ("", {"type": "string", "minLength": 1}, False),
        ("xxx", {"type": "string", "maxLength": 2}, False),
        (True, {"type": "boolean"}, True),
        (1, {"type": "boolean"}, False),
        (1, {"type": "integer"}, True),
        (True, {"type": "integer"}, False),
        (1.5, {"type": "number"}, True),
        (False, {"type": "number"}, False),
        ([1, 2], {"type": "array", "items": {"type": "integer"}}, True),
        ([1, "x"], {"type": "array", "items": {"type": "integer"}}, False),
        ("a", {"type": "string", "enum": ["a", "b"]}, True),
        ("c", {"type": "string", "enum": ["a", "b"]}, False),
        (
            {"x": 1},
            {
                "type": "object",
                "required": ["x"],
                "properties": {"x": {"type": "integer"}},
                "additionalProperties": False,
            },
            True,
        ),
        ({"y": 1}, {"type": "object", "required": ["x"], "properties": {}}, False),
        (
            {"x": 1},
            {"type": "object", "properties": {}, "additionalProperties": False},
            False,
        ),
        (None, {"type": "null"}, False),
        (1, "not-a-schema", False),
    ],
)
def test_contract_schema_matcher_is_closed_and_type_strict(
    value: object, schema: object, expected: bool
) -> None:
    from conductor.capabilities import _matches_schema

    assert _matches_schema(value, schema) is expected


def test_contract_mode_downgrades_missing_hooks_identity_and_blocking() -> None:
    from conductor.capabilities import contract_mode, load_contract

    contract = load_contract("claude-current")
    no_hooks = contract.model_copy(update={"hook_events": ()})
    no_lifecycle = contract.model_copy(
        update={
            "correlation_fields": contract.correlation_fields.model_copy(
                update={"lifecycle_id": ()}
            )
        }
    )
    observe = contract.model_copy(update={"can_block": False})

    assert contract_mode(no_hooks) is OperatingMode.UNSUPPORTED
    assert contract_mode(no_lifecycle) is OperatingMode.UNSUPPORTED
    assert contract_mode(observe) is OperatingMode.OBSERVE
