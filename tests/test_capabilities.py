from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

from conductor.schemas import CapabilityContract, OperatingMode


FIXTURES = Path(__file__).parent / "fixtures" / "contracts"


def fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def test_current_codex_contract_selects_admission_without_model_field() -> None:
    from conductor.capabilities import load_contract, negotiate

    contract = load_contract("codex-current")
    result = negotiate(contract, fixture("codex-spawn"))

    assert result.mode == OperatingMode.ADMISSION
    assert result.child_model_selectable is False
    spawn = next(tool for tool in contract.tools if tool.canonical_name == "spawn")
    assert "model" not in spawn.input_schema["properties"]


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
