from __future__ import annotations

import math
from pathlib import PurePosixPath

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from toolbelt.errors import (
    ApplyError,
    DeclinedError,
    DriftError,
    InternalError,
    RollbackError,
    StalePlanError,
    ToolbeltError,
    UsageError,
    ValidationToolbeltError,
    VerificationError,
)
from toolbelt.schemas import (
    ActionStepV2,
    CapabilitySnapshot,
    CatalogToolV2,
    CommandResultV2,
    DeclarationV2,
    EvidenceV2,
    PlanV2,
    TransactionState,
    VerificationState,
    relative_path_or_none,
)


def valid_plan_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "plan_id": "3" * 64,
        "repository": {
            "root": ".",
            "identity": "0" * 64,
            "content_digest": "1" * 64,
            "git_head": "abc123",
            "dirty_digest": "2" * 64,
        },
        "catalog_digest": "4" * 64,
        "capability_digest": "5" * 64,
        "catalog_tools": {"ruff": "0.8.6"},
        "actions": [
            {
                "id": "a1",
                "operation": "install",
                "tool_id": "ruff",
                "tool_version": "0.8.6",
                "install_scope": "project",
                "permissions": ["process-spawn"],
                "evidence": [
                    {
                        "type": "test",
                        "key": "pytest",
                        "detail": "pytest configured",
                        "source": "pyproject.toml",
                        "strength": "strong",
                    }
                ],
                "confidence": 0.9,
                "why": "The repository configures pytest.",
                "steps": [
                    {
                        "argv": ["python", "-m", "pip", "install", "ruff==0.8.6"],
                        "requires_network": True,
                    }
                ],
                "verify": [{"argv": ["ruff", "--version"]}],
                "rollback": [
                    {
                        "argv": ["python", "-m", "pip", "uninstall", "-y", "ruff"],
                    }
                ],
                "required_env": [],
            }
        ],
        "created_at": "2026-07-09T12:00:00Z",
        "expires_at": "2026-07-09T13:00:00Z",
    }


def valid_catalog_tool_payload() -> dict[str, object]:
    return {
        "schema_version": 2,
        "id": "ruff",
        "name": "Ruff",
        "summary": "Python linting and formatting",
        "kind": "dev_tool",
        "provenance": "pypi:ruff==0.8.6",
        "version": "0.8.6",
        "homepage": "https://docs.astral.sh/ruff/",
        "license": "MIT",
        "platforms": ["linux", "macos", "windows"],
        "harnesses": ["claude", "codex"],
        "permissions": ["process-spawn"],
        "install_scope": "project",
        "artifacts": ["pyproject.toml"],
        "required_env": [],
        "strong_evidence": ["test:pytest"],
        "weak_evidence": ["lang:python"],
        "required_capabilities": [],
        "suppressed_by_capabilities": [],
        "live_name": "ruff",
        "install": {
            "argv": ["python", "-m", "pip", "install", "ruff==0.8.6"],
            "requires_network": True,
        },
        "verify": {"argv": ["ruff", "--version"]},
        "rollback": {
            "argv": ["python", "-m", "pip", "uninstall", "-y", "ruff"],
        },
        "enabled": True,
    }


def test_plan_rejects_unknown_fields_and_absolute_paths():
    payload = valid_plan_payload()
    payload["surprise"] = True
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)

    payload = valid_plan_payload()
    payload["repository"]["root"] = "/tmp/elsewhere"  # type: ignore[index]
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)


@given(st.text(max_size=300))
def test_relative_path_schema_never_accepts_escape(value: str):
    accepted = relative_path_or_none(value)
    if accepted is not None:
        assert isinstance(accepted, PurePosixPath)
        assert not accepted.is_absolute()
        assert ".." not in accepted.parts


@pytest.mark.parametrize(
    "value",
    [
        "../outside",
        "safe/../../outside",
        "/absolute",
        "C:/Windows",
        "\\\\server\\share",
        "bad\0path",
    ],
)
def test_artifact_paths_reject_escapes(value: str):
    payload = valid_catalog_tool_payload()
    payload["artifacts"] = [value]
    with pytest.raises(ValidationError):
        CatalogToolV2.model_validate(payload)


@pytest.mark.parametrize("argv", [[], [""], ["sh", "-c", "echo ok"], ["cmd.exe", "/c", "echo ok"]])
def test_action_steps_require_non_shell_argv(argv: list[str]):
    with pytest.raises(ValidationError):
        ActionStepV2.model_validate({"argv": argv})


def test_plan_rejects_duplicate_actions_and_inexact_catalog_reference():
    payload = valid_plan_payload()
    payload["actions"] = [payload["actions"][0], payload["actions"][0]]  # type: ignore[index]
    with pytest.raises(ValidationError, match="action IDs"):
        PlanV2.model_validate(payload)

    payload = valid_plan_payload()
    payload["actions"][0]["tool_version"] = "0.8.5"  # type: ignore[index]
    with pytest.raises(ValidationError, match="catalog reference"):
        PlanV2.model_validate(payload)


@pytest.mark.parametrize("confidence", [math.nan, math.inf, -0.1, 1.1])
def test_plan_rejects_non_finite_or_out_of_range_confidence(confidence: float):
    payload = valid_plan_payload()
    payload["actions"][0]["confidence"] = confidence  # type: ignore[index]
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)


def test_public_models_are_frozen_strict_and_round_trip():
    evidence = EvidenceV2.model_validate(
        {
            "type": "lang",
            "key": "python",
            "detail": "one Python file",
            "source": "src/app.py",
            "strength": "weak",
        }
    )
    with pytest.raises(ValidationError):
        evidence.key = "rust"

    with pytest.raises(ValidationError):
        EvidenceV2.model_validate({**evidence.model_dump(), "unknown": True})

    plan = PlanV2.model_validate(valid_plan_payload())
    assert PlanV2.model_validate_json(plan.model_dump_json()) == plan


@pytest.mark.parametrize("schema_version", [1, 3, "2"])
def test_plan_accepts_only_integer_schema_version_two(schema_version: object):
    payload = valid_plan_payload()
    payload["schema_version"] = schema_version
    with pytest.raises(ValidationError):
        PlanV2.model_validate(payload)


def test_stable_error_exit_codes():
    expected = {
        UsageError: 2,
        ValidationToolbeltError: 3,
        StalePlanError: 4,
        DeclinedError: 5,
        ApplyError: 6,
        RollbackError: 7,
        VerificationError: 8,
        DriftError: 9,
        InternalError: 10,
    }
    for error_type, exit_code in expected.items():
        error = error_type("message")
        assert isinstance(error, ToolbeltError)
        assert error.exit_code == exit_code
        assert str(error) == "message"


def test_unknown_capabilities_fail_closed_and_managed_tools_are_installed():
    with pytest.raises(ValidationError, match="require an error"):
        CapabilitySnapshot.model_validate(
            {"schema_version": 2, "provider": "codex", "status": "unknown"}
        )

    with pytest.raises(ValidationError, match="also be installed"):
        CapabilitySnapshot.model_validate(
            {
                "schema_version": 2,
                "provider": "claude",
                "status": "known",
                "installed": [],
                "managed": ["ruff"],
            }
        )

    with pytest.raises(ValidationError, match="duplicates"):
        CapabilitySnapshot.model_validate(
            {
                "schema_version": 2,
                "provider": "codex",
                "status": "known",
                "native": ["git", "git"],
            }
        )

    snapshot = CapabilitySnapshot.model_validate(
        {
            "schema_version": 2,
            "provider": "codex",
            "provider_version": "1.2.3",
            "status": "known",
            "native": ["filesystem", "git"],
            "installed": ["ruff"],
            "managed": [],
            "errors": [],
        }
    )
    assert CapabilitySnapshot.model_validate_json(snapshot.model_dump_json()) == snapshot


def test_declaration_rejects_duplicate_tool_ids():
    tool = {
        "tool_id": "ruff",
        "version": "0.8.6",
        "provenance": "pypi:ruff==0.8.6",
        "install_scope": "project",
        "permissions": ["process-spawn"],
        "required_env": [],
        "artifacts": ["pyproject.toml"],
    }
    payload = {
        "schema_version": 2,
        "repository_identity": "a" * 64,
        "catalog_digest": "b" * 64,
        "tools": [tool, tool],
    }
    with pytest.raises(ValidationError, match="tool IDs"):
        DeclarationV2.model_validate(payload)


def test_command_result_is_bounded_and_transaction_enums_are_closed():
    result = CommandResultV2.model_validate(
        {
            "schema_version": 2,
            "argv": ["ruff", "--version"],
            "returncode": 0,
            "stdout": "ruff 0.8.6",
            "duration_seconds": 0.01,
            "verification": "passed",
        }
    )
    assert result.verification is VerificationState.PASSED

    payload = result.model_dump()
    payload["duration_seconds"] = math.nan
    with pytest.raises(ValidationError):
        CommandResultV2.model_validate(payload)

    payload = result.model_dump()
    payload["stdout"] = "x" * 65537
    with pytest.raises(ValidationError):
        CommandResultV2.model_validate(payload)

    assert {state.value for state in VerificationState} == {
        "not_run",
        "passed",
        "failed",
        "skipped",
    }

    assert {state.value for state in TransactionState} == {
        "planned",
        "preflight",
        "applying",
        "verifying",
        "succeeded",
        "rolling_back",
        "rolled_back",
        "rollback_failed",
        "interrupted",
    }
