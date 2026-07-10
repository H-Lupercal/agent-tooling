from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from conductor.config import load_config
from conductor.schemas import (
    NormalizedOperation,
    OperatingMode,
    OperationName,
    Provider,
    RunContext,
    TaskEnvelopeV2,
)
from conductor.store import ReservationSnapshot
from tests.helpers import DEFAULT_CONFIG, write_config


def _config(tmp_path: Path, *, enforce: bool = True):
    text = DEFAULT_CONFIG.replace("enforce = true", f"enforce = {str(enforce).lower()}")
    return load_config(write_config(tmp_path / "conductor.toml", text))


def _run(mode: OperatingMode, *, model: str = "gpt-5.5") -> RunContext:
    now = datetime.now(UTC)
    return RunContext(
        provider=Provider.CODEX,
        run_id="run-1",
        thread_id="thread-1",
        root_model=model,
        model_source="provider",
        provider_contract="codex-current",
        contract_digest="0" * 64,
        mode=mode,
        generation=1,
        started_at=now,
        heartbeat_at=now,
        config_digest="1" * 64,
    )


def _operation(
    task_class: str = "implementation",
    *,
    model: str | None = "gpt-5.4",
    operation: OperationName = OperationName.SPAWN,
    is_new_work: bool = True,
    risk_triggers: tuple[str, ...] = (),
) -> NormalizedOperation:
    payload = {"message": "do it", "task_name": f"task-{task_class}"}
    if model is not None:
        payload["model"] = model
    envelope = TaskEnvelopeV2(
        schema_version=1,
        task_name=f"task-{task_class}",
        task_class=task_class,
        risk_triggers=risk_triggers,
        owned_paths=("src/example.py",),
        acceptance_checks=("pytest -q",),
        new_task=is_new_work,
        operation_intent=operation
        if operation in {OperationName.FOLLOWUP, OperationName.MESSAGE}
        else None,
    )
    return NormalizedOperation(
        provider=Provider.CODEX,
        operation=operation,
        raw_tool_name="spawn_agent",
        payload=payload,
        envelope=envelope,
        is_new_work=is_new_work,
        correlation_id="call-1",
    )


EMPTY = ReservationSnapshot(active_by_tier={}, reserved_usd=0.0, spent_usd=0.0)


def _evaluate(tmp_path: Path, operation: NormalizedOperation, **overrides):
    from conductor.policy import evaluate_policy

    values = {
        "operation": operation,
        "run": _run(OperatingMode.ROUTING),
        "config": _config(tmp_path),
        "enabled_tiers": (0, 1, 2, 3),
        "snapshot": EMPTY,
        "caller_model": "gpt-5.5",
        "caller_depth": 0,
    }
    values.update(overrides)
    return evaluate_policy(**values)


def test_non_new_work_is_not_governed_or_reserved(tmp_path: Path) -> None:
    result = _evaluate(
        tmp_path,
        _operation(
            operation=OperationName.MESSAGE,
            is_new_work=False,
            model=None,
        ),
    )

    assert result.spec.allowed is True
    assert result.spec.rule == "NOT_GOVERNED"
    assert result.reserve is False
    assert result.tier is None


@pytest.mark.parametrize(
    ("mode", "allowed", "rule", "reserve"),
    [
        (OperatingMode.UNSUPPORTED, False, "UNSUPPORTED_CAPABILITY", False),
        (OperatingMode.OBSERVE, True, "OBSERVE_ONLY", False),
        (OperatingMode.ADMISSION, False, "ROUTING_REQUIRED", False),
        (OperatingMode.ROUTING, True, "ALLOW", True),
    ],
)
def test_operating_modes_never_overstate_enforcement(
    tmp_path: Path,
    mode: OperatingMode,
    allowed: bool,
    rule: str,
    reserve: bool,
) -> None:
    result = _evaluate(tmp_path, _operation(), run=_run(mode))

    assert result.spec.allowed is allowed
    assert result.spec.rule == rule
    assert result.reserve is reserve
    assert result.spec.savings_eligible is (mode is OperatingMode.ROUTING and allowed)


def test_routing_requires_the_exact_selected_model(tmp_path: Path) -> None:
    result = _evaluate(tmp_path, _operation(model="gpt-5.4-mini"))

    assert result.spec.allowed is False
    assert result.spec.rule == "MODEL_MISMATCH"
    assert result.selected_model == "gpt-5.4"


def test_high_risk_trigger_forces_frontier_even_for_a_cheap_class(
    tmp_path: Path,
) -> None:
    operation = _operation(
        "tests",
        model="gpt-5.5",
        risk_triggers=("public API contract change",),
    )

    result = _evaluate(tmp_path, operation)

    assert result.spec.allowed is True
    assert result.tier is not None and result.tier.name == "frontier"
    assert result.spec.savings_eligible is False


def test_high_risk_never_falls_back_to_a_non_frontier_tier(tmp_path: Path) -> None:
    operation = _operation("high_risk", model="gpt-5.4")

    result = _evaluate(tmp_path, operation, enabled_tiers=(1, 2, 3))

    assert result.spec.allowed is False
    assert result.spec.rule == "FRONTIER_UNAVAILABLE"


def test_same_tier_exception_is_root_only_and_bounded_in_enforced_modes(
    tmp_path: Path,
) -> None:
    operation = _operation("high_risk", model="gpt-5.5")

    allowed = _evaluate(tmp_path, operation)
    nested = _evaluate(tmp_path, operation, caller_depth=1)
    admission = _evaluate(tmp_path, operation, run=_run(OperatingMode.ADMISSION))
    exhausted = _evaluate(
        tmp_path,
        operation,
        snapshot=ReservationSnapshot(
            active_by_tier={"frontier": 2}, reserved_usd=4.0, spent_usd=0.0
        ),
    )

    assert allowed.spec.allowed is True
    assert nested.spec.rule == "STRICTLY_CHEAPER_REQUIRED"
    assert admission.spec.allowed is True
    assert admission.spec.rule == "ALLOW"
    assert admission.spec.selected_model is None
    assert admission.spec.savings_eligible is False
    assert exhausted.spec.rule == "SAME_TIER_LIMIT"


def test_depth_may_spawn_and_stronger_child_rules_are_explicit(tmp_path: Path) -> None:
    depth = _evaluate(tmp_path, _operation(), caller_depth=3)
    may_spawn = _evaluate(
        tmp_path,
        _operation("search", model=None),
        caller_model="gpt-5.3-codex-spark",
    )
    stronger = _evaluate(
        tmp_path,
        _operation("implementation", model="gpt-5.4"),
        caller_model="gpt-5.4-mini",
    )

    assert depth.spec.rule == "DEPTH_LIMIT"
    assert may_spawn.spec.rule == "CALLER_MAY_NOT_SPAWN"
    assert stronger.spec.rule == "STRONGER_CHILD_FORBIDDEN"


def test_concurrency_and_budget_use_the_atomic_snapshot(tmp_path: Path) -> None:
    operation = _operation()
    concurrency = _evaluate(
        tmp_path,
        operation,
        snapshot=ReservationSnapshot(
            active_by_tier={"standard": 4}, reserved_usd=2.4, spent_usd=0.0
        ),
    )
    budget = _evaluate(
        tmp_path,
        operation,
        snapshot=ReservationSnapshot(
            active_by_tier={}, reserved_usd=1.0, spent_usd=8.5
        ),
    )

    assert concurrency.spec.rule == "CONCURRENCY_CAP"
    assert budget.spec.rule == "BUDGET_CAP"


def test_warn_only_budget_is_allowed_but_not_hidden(tmp_path: Path) -> None:
    result = _evaluate(
        tmp_path,
        _operation(),
        config=_config(tmp_path, enforce=False),
        snapshot=ReservationSnapshot(
            active_by_tier={}, reserved_usd=1.0, spent_usd=8.5
        ),
    )

    assert result.spec.allowed is True
    assert result.spec.rule == "BUDGET_CAP_WARNING"
    assert result.reserve is True


def test_disabled_owner_falls_back_only_to_a_stronger_enabled_tier(
    tmp_path: Path,
) -> None:
    result = _evaluate(
        tmp_path,
        _operation("tests", model="gpt-5.4"),
        enabled_tiers=(0, 1),
    )

    assert result.spec.allowed is True
    assert result.tier is not None and result.tier.name == "standard"


def test_unknown_caller_model_and_missing_envelope_fail_closed(
    tmp_path: Path,
) -> None:
    unknown = _evaluate(tmp_path, _operation(), caller_model="unknown")
    missing = _operation().model_copy(update={"envelope": None})

    assert unknown.spec.rule == "UNKNOWN_CALLER_MODEL"
    assert _evaluate(tmp_path, missing).spec.rule == "MISSING_ENVELOPE"
