from __future__ import annotations

import tomllib
from datetime import UTC, datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from conductor.config import ConductorConfig
from conductor.policy import evaluate_policy
from conductor.schemas import (
    NormalizedOperation,
    Provider,
    RawUsage,
    RunContext,
    TaskEnvelopeV2,
)
from conductor.store import ReservationSnapshot
from tests.helpers import DEFAULT_CONFIG

CONFIG = ConductorConfig.model_validate(tomllib.loads(DEFAULT_CONFIG))
NOW = datetime.now(UTC)
RUN = RunContext(
    provider="codex",
    run_id="property-run",
    thread_id="property-run",
    root_model="gpt-5.5",
    model_source="operator",
    provider_contract="codex-current",
    contract_digest="0" * 64,
    mode="routing",
    generation=1,
    started_at=NOW,
    heartbeat_at=NOW,
    config_digest="1" * 64,
)
ENVELOPE = TaskEnvelopeV2(
    schema_version=1,
    task_name="property-task",
    task_class="implementation",
    risk_triggers=(),
    owned_paths=("src/property.py",),
    acceptance_checks=("pytest -q",),
    new_task=True,
)
OPERATION = NormalizedOperation(
    provider=Provider.CODEX,
    operation="spawn",
    raw_tool_name="spawn_agent",
    payload={"model": "gpt-5.4", "message": "bounded"},
    envelope=ENVELOPE,
    is_new_work=True,
    correlation_id="property-call",
)


@given(
    spent=st.floats(
        min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
    reserved=st.floats(
        min_value=0.0, max_value=10_000.0, allow_nan=False, allow_infinity=False
    ),
)
def test_enforced_budget_never_allows_an_over_cap_snapshot(
    spent: float, reserved: float
) -> None:
    result = evaluate_policy(
        operation=OPERATION,
        run=RUN,
        config=CONFIG,
        enabled_tiers=(0, 1, 2, 3),
        snapshot=ReservationSnapshot({}, reserved, spent),
        caller_model="gpt-5.5",
        caller_depth=0,
    )
    projected = spent + reserved + CONFIG.tiers[1].est_task_usd

    if projected > CONFIG.budget.run_usd_cap + 1e-12:
        assert result.spec.allowed is False
        assert result.spec.rule == "BUDGET_CAP"


@given(depth=st.integers(min_value=3, max_value=1_000_000))
def test_unbounded_depth_never_reaches_capacity_or_budget(depth: int) -> None:
    result = evaluate_policy(
        operation=OPERATION,
        run=RUN,
        config=CONFIG,
        enabled_tiers=(0, 1, 2, 3),
        snapshot=ReservationSnapshot({}, 0.0, 0.0),
        caller_model="gpt-5.5",
        caller_depth=depth,
    )

    assert result.spec.allowed is False
    assert result.spec.rule == "DEPTH_LIMIT"


@pytest.mark.parametrize("value", [2**63, 10**100])
def test_usage_counters_are_bounded_before_cost_math(value: int) -> None:
    with pytest.raises(ValidationError):
        RawUsage(
            source_event_id="usage-bounded",
            provider="codex",
            parser_version="test-v1",
            model="gpt-5.4",
            input_tokens=value,
            cache_read_tokens=0,
            cache_write_tokens=0,
            output_tokens=0,
            reasoning_tokens=0,
            measured=True,
            occurred_at=NOW,
        )
