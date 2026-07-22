from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError


def deep_merge(base: dict[str, Any], change: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in change.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def valid_config() -> dict[str, Any]:
    return {
        "schema_version": 2,
        "budget": {
            "run_usd_cap": 10.0,
            "warn_at_fraction": 0.75,
            "enforce": True,
        },
        "policy": {
            "max_depth": 3,
            "require_strictly_cheaper": True,
            "same_tier_spawns_from_root_max": 2,
            "minimum_mode": "admission",
        },
        "tiers": [
            _tier(
                "frontier",
                "gpt-5.5",
                100,
                2.0,
                ["architecture", "high_risk", "integration", "review_gate"],
                max_concurrent=2,
            ),
            _tier(
                "standard",
                "gpt-5.4",
                25,
                0.6,
                ["implementation", "refactor", "debug", "cross_module_change"],
                max_concurrent=4,
            ),
            _tier(
                "mini",
                "gpt-5.4-mini",
                6,
                0.15,
                ["tests", "docs", "mechanical_edit", "rename", "config_change"],
                enabled="auto",
                max_concurrent=6,
            ),
            _tier(
                "spark",
                "gpt-5.3-codex-spark",
                2,
                0.05,
                ["search", "summarize", "boilerplate", "formatting", "data_extraction"],
                enabled="auto",
                max_concurrent=8,
                may_spawn=False,
            ),
        ],
    }


def _tier(
    name: str,
    model: str,
    weight: int,
    estimate: float,
    task_classes: list[str],
    *,
    enabled: str = "always",
    max_concurrent: int,
    may_spawn: bool = True,
) -> dict[str, Any]:
    return {
        "name": name,
        "model": model,
        "reasoning_effort": "medium",
        "enabled": enabled,
        "pricing": {
            "input_usd_per_mtok": 1.0,
            "cache_read_usd_per_mtok": 0.1,
            "cache_write_usd_per_mtok": 1.25,
            "output_usd_per_mtok": 3.0,
        },
        "relative_cost_weight": weight,
        "est_task_usd": estimate,
        "max_concurrent": max_concurrent,
        "may_spawn": may_spawn,
        "task_classes": task_classes,
    }


def contract_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "contract_name": "codex-current",
        "provider": "codex",
        "cli_version_range": {"minimum": "0.1.0", "maximum_exclusive": "1.0.0"},
        "hook_events": ["SessionStart", "PreToolUse", "SubagentStart", "SubagentStop"],
        "tools": [
            {
                "canonical_name": "spawn",
                "names": ["spawn_agent", "collaboration.spawn_agent"],
                "input_schema": {"type": "object", "additionalProperties": False},
            }
        ],
        "model_selector_path": None,
        "correlation_fields": {
            "run_id": ["thread_id"],
            "caller_id": ["caller_id"],
            "child_id": ["agent_id"],
            "task_id": ["task_name"],
            "lifecycle_id": ["tool_call_id"],
        },
        "usage_fields": ["input_tokens", "output_tokens"],
        "decision_response_schema": {"type": "object"},
        "trust_visibility": True,
        "can_block": True,
    }


def envelope_payload() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_name": "tests_ledger",
        "task_class": "tests",
        "risk_triggers": [],
        "owned_paths": ["tests/test_ledger.py"],
        "acceptance_checks": ["python3 -m unittest tests.test_ledger -v"],
        "new_task": True,
        "operation_intent": "spawn",
    }


def test_all_public_contract_models_are_frozen_and_forbid_unknown_fields() -> None:
    from conductor.schemas import (
        BudgetConfig,
        CapabilityContract,
        ConductorConfig,
        Decision,
        LifecycleEvent,
        NormalizedOperation,
        PolicyConfig,
        Pricing,
        RawUsage,
        ReportRow,
        Reservation,
        RunContext,
        TaskEnvelopeV2,
        TierConfig,
    )

    now = datetime.now(UTC)
    envelope = TaskEnvelopeV2.model_validate(envelope_payload())
    usage = RawUsage(
        source_event_id="stop-1",
        provider="codex",
        parser_version="1",
        model="gpt-5.4-mini",
        input_tokens=10,
        cache_read_tokens=2,
        cache_write_tokens=1,
        output_tokens=5,
        reasoning_tokens=1,
        measured=True,
        occurred_at=now,
    )
    instances: list[BaseModel] = [
        BudgetConfig.model_validate(valid_config()["budget"]),
        PolicyConfig.model_validate(valid_config()["policy"]),
        Pricing.model_validate(valid_config()["tiers"][0]["pricing"]),
        TierConfig.model_validate(valid_config()["tiers"][0]),
        ConductorConfig.model_validate(valid_config()),
        CapabilityContract.model_validate(contract_payload()),
        RunContext(
            provider="codex",
            run_id="root-run",
            thread_id="root-run",
            root_model="gpt-5.5",
            model_source="session",
            provider_contract="codex-current",
            contract_digest="a" * 64,
            mode="admission",
            generation=1,
            started_at=now,
            heartbeat_at=now,
            config_digest="b" * 64,
        ),
        envelope,
        NormalizedOperation(
            provider="codex",
            operation="spawn",
            raw_tool_name="collaboration.spawn_agent",
            payload={"task_name": "tests_ledger"},
            envelope=envelope,
            is_new_work=True,
            correlation_id="call-1",
        ),
        Decision(
            decision_id="decision-1",
            allowed=True,
            rule="ALLOW",
            message="approved",
            mode="admission",
            operation="spawn",
            selected_model=None,
            reservation_estimate_usd=0.15,
            savings_eligible=False,
            reservation_id="reservation-1",
            created_at=now,
        ),
        Reservation(
            reservation_id="reservation-1",
            run_id="root-run",
            task_id="tests-ledger",
            operation="spawn",
            tier="mini",
            model="gpt-5.4-mini",
            estimated_usd=0.15,
            state="approved",
            correlation_id="call-1",
            created_at=now,
            updated_at=now,
            expires_at=now + timedelta(minutes=5),
        ),
        usage,
        LifecycleEvent(
            event_id="stop-1",
            provider="codex",
            run_id="root-run",
            correlation_id="call-1",
            kind="stop",
            occurred_at=now,
            status="completed",
            usage=usage,
        ),
        ReportRow(
            run_id="root-run",
            tier="mini",
            mode="admission",
            reservations=1,
            completed=1,
            failed=0,
            measured_usd=0.1,
            estimated_usd=0.05,
        ),
    ]

    for instance in instances:
        with pytest.raises(ValidationError):
            instance.__class__.model_validate(
                {**instance.model_dump(mode="json"), "unknown": 1}
            )
        with pytest.raises(ValidationError):
            instance.model_copy(update={"unknown": 1}).unknown = 2


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_pricing_rejects_negative_or_non_finite_values(value: float) -> None:
    from conductor.schemas import Pricing

    payload = valid_config()["tiers"][0]["pricing"]
    payload["cache_write_usd_per_mtok"] = value
    with pytest.raises(ValidationError):
        Pricing.model_validate(payload)


@pytest.mark.parametrize("effort", ["low", "medium", "high", "xhigh", "max", "ultra"])
def test_tier_accepts_canonical_effort_levels(effort: str) -> None:
    from conductor.schemas import TierConfig

    payload = valid_config()["tiers"][0]
    payload.update(
        reasoning_effort=effort,
        generation_rank=56,
        capability_rank=100,
    )

    tier = TierConfig.model_validate(payload)

    assert tier.reasoning_effort == effort
    assert tier.supports_effort(effort)


@pytest.mark.parametrize("field", ["generation_rank", "capability_rank"])
def test_model_authority_ranks_must_be_positive(field: str) -> None:
    from conductor.schemas import TierConfig

    payload = valid_config()["tiers"][0]
    payload[field] = 0

    with pytest.raises(ValidationError):
        TierConfig.model_validate(payload)


def test_legacy_tier_authority_defaults_preserve_config_compatibility() -> None:
    from conductor.schemas import TierConfig

    tier = TierConfig.model_validate(valid_config()["tiers"][0])

    assert tier.generation_rank is None
    assert tier.effective_capability_rank == tier.relative_cost_weight


def test_tier_may_own_no_task_class_recommendations() -> None:
    from conductor.schemas import TierConfig

    payload = valid_config()["tiers"][0]
    payload["task_classes"] = []

    assert TierConfig.model_validate(payload).task_classes == ()


@pytest.mark.parametrize(
    "run_id", ["", "../escape", "/absolute", "contains space", "x" * 129]
)
def test_run_context_rejects_unsafe_identifiers(run_id: str) -> None:
    from conductor.schemas import RunContext

    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        RunContext(
            provider="codex",
            run_id=run_id,
            thread_id="thread-1",
            root_model="gpt-5.5",
            model_source="session",
            provider_contract="codex-current",
            contract_digest="a" * 64,
            mode="admission",
            generation=1,
            started_at=now,
            heartbeat_at=now,
            config_digest="b" * 64,
        )


def test_stable_exit_codes_are_unique() -> None:
    from conductor.errors import ExitCode

    assert ExitCode.SUCCESS == 0
    assert len({item.value for item in ExitCode}) == len(ExitCode)
    assert {item.name for item in ExitCode} >= {
        "USAGE",
        "VALIDATION",
        "UNSUPPORTED_CAPABILITY",
        "POLICY_DENIAL",
        "DEGRADED_RUNTIME",
        "STATE",
        "INSTALLATION_CONFLICT",
        "INTERNAL",
    }
