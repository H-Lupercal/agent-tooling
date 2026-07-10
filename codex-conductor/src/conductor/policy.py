from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from conductor.config import ConductorConfig, TierConfig
from conductor.schemas import (
    NormalizedOperation,
    OperatingMode,
    OperationName,
    RunContext,
)
from conductor.store import DecisionSpec, ReservationSnapshot

_GOVERNED_OPERATIONS = {
    OperationName.SPAWN,
    OperationName.ASSIGN,
    OperationName.FOLLOWUP,
    OperationName.MESSAGE,
}


@dataclass(frozen=True)
class PolicyEvaluation:
    """Pure policy result consumed by the atomic store transaction.

    ``tier`` and ``selected_model`` describe the tier against which capacity and
    budget are reserved. A selected model is only asserted in routing mode;
    admission mode must never claim that it can choose a child model.
    """

    spec: DecisionSpec
    tier: TierConfig | None
    selected_model: str | None
    estimate_usd: float
    reserve: bool


def evaluate_policy(
    *,
    operation: NormalizedOperation,
    run: RunContext,
    config: ConductorConfig,
    enabled_tiers: Sequence[int],
    snapshot: ReservationSnapshot,
    caller_model: str,
    caller_depth: int,
) -> PolicyEvaluation:
    """Evaluate one normalized operation without I/O or mutation.

    Tier indexes are ordered strongest-to-cheapest by the validated
    configuration. The store calls this function while holding its write
    transaction, so capacity and budget decisions observe one atomic snapshot.
    """

    if operation.operation not in _GOVERNED_OPERATIONS or not operation.is_new_work:
        return _result(True, "NOT_GOVERNED", "operation is not new governed work")

    if run.mode is OperatingMode.UNSUPPORTED:
        return _result(
            False,
            "UNSUPPORTED_CAPABILITY",
            "provider capability contract cannot enforce correlated agent work",
        )
    if run.mode is OperatingMode.OBSERVE:
        return _result(
            True,
            "OBSERVE_ONLY",
            "provider is observe-only; operation was recorded but not enforced",
        )

    envelope = operation.envelope
    if envelope is None:
        return _result(
            False,
            "MISSING_ENVELOPE",
            "new governed work requires one valid CONDUCTOR_TASK envelope",
        )
    if not envelope.new_task:
        return _result(
            False,
            "INVALID_NEW_WORK",
            "new governed work requires envelope.new_task=true",
        )
    if operation.provider is not run.provider:
        return _result(
            False,
            "PROVIDER_MISMATCH",
            "operation provider does not match the active run",
        )
    if caller_depth < 0:
        return _result(False, "INVALID_DEPTH", "caller depth cannot be negative")
    if caller_depth + 1 > config.policy.max_depth:
        return _result(
            False,
            "DEPTH_LIMIT",
            f"maximum delegation depth {config.policy.max_depth} reached",
        )

    caller_index = config.tier_index_for_model(caller_model)
    if caller_index is None:
        return _result(
            False,
            "UNKNOWN_CALLER_MODEL",
            "caller model is outside the configured tier ladder",
        )
    caller_tier = config.tiers[caller_index]
    if not caller_tier.may_spawn:
        return _result(
            False,
            "CALLER_MAY_NOT_SPAWN",
            f"tier {caller_tier.name} may not delegate work",
        )

    target_index = _target_tier_index(config, enabled_tiers, envelope.task_class)
    forced_frontier = envelope.task_class == "high_risk" or bool(envelope.risk_triggers)
    if forced_frontier:
        target_index = _frontier_index(config, enabled_tiers)
        if target_index is None:
            return _result(
                False,
                "FRONTIER_UNAVAILABLE",
                "high-risk work requires an enabled frontier tier",
            )
    elif target_index is None:
        return _result(
            False,
            "NO_ENABLED_TIER",
            f"no enabled tier can own task class {envelope.task_class}",
        )

    target = config.tiers[target_index]
    selected_model = target.model if run.mode is OperatingMode.ROUTING else None
    estimate = float(target.est_task_usd)

    if target_index < caller_index:
        return _result(
            False,
            "STRONGER_CHILD_FORBIDDEN",
            "delegated work may not use a stronger tier than its caller",
            tier=target,
            selected_model=selected_model,
            estimate=estimate,
        )

    same_tier = target_index == caller_index
    if config.policy.require_strictly_cheaper and same_tier:
        exception_allowed = (
            caller_depth == 0
            and snapshot.active_by_tier.get(target.name, 0)
            < config.policy.same_tier_spawns_from_root_max
        )
        if not exception_allowed:
            rule = (
                "SAME_TIER_LIMIT" if caller_depth == 0 else "STRICTLY_CHEAPER_REQUIRED"
            )
            return _result(
                False,
                rule,
                "child must be strictly cheaper; the bounded root exception is unavailable",
                tier=target,
                selected_model=selected_model,
                estimate=estimate,
            )

    if run.mode is OperatingMode.ADMISSION and target_index != caller_index:
        return _result(
            False,
            "ROUTING_REQUIRED",
            "provider can admit work but cannot enforce the configured child model",
            tier=target,
            estimate=estimate,
        )

    requested_model = _requested_model(operation)
    if run.mode is OperatingMode.ROUTING and requested_model != target.model:
        return _result(
            False,
            "MODEL_MISMATCH",
            f"task class {envelope.task_class} requires model {target.model}",
            tier=target,
            selected_model=target.model,
            estimate=estimate,
        )

    active = snapshot.active_by_tier.get(target.name, 0)
    if active >= target.max_concurrent:
        return _result(
            False,
            "CONCURRENCY_CAP",
            f"tier {target.name} reached max_concurrent={target.max_concurrent}",
            tier=target,
            selected_model=selected_model,
            estimate=estimate,
        )

    projected = snapshot.spent_usd + snapshot.reserved_usd + estimate
    if projected > config.budget.run_usd_cap + 1e-12:
        message = (
            f"projected run cost ${projected:.6f} exceeds "
            f"cap ${config.budget.run_usd_cap:.6f}"
        )
        if config.budget.enforce:
            return _result(
                False,
                "BUDGET_CAP",
                message,
                tier=target,
                selected_model=selected_model,
                estimate=estimate,
            )
        return _result(
            True,
            "BUDGET_CAP_WARNING",
            message,
            tier=target,
            selected_model=selected_model,
            estimate=estimate,
            reserve=True,
            savings=_savings_eligible(run.mode, caller_index, target_index),
        )

    warning_threshold = config.budget.run_usd_cap * config.budget.warn_at_fraction
    rule = "BUDGET_WARNING" if projected >= warning_threshold else "ALLOW"
    message = (
        f"reservation approved; projected run cost ${projected:.6f}"
        if rule == "ALLOW"
        else f"reservation approved above budget warning threshold: ${projected:.6f}"
    )
    return _result(
        True,
        rule,
        message,
        tier=target,
        selected_model=selected_model,
        estimate=estimate,
        reserve=True,
        savings=_savings_eligible(run.mode, caller_index, target_index),
    )


def _target_tier_index(
    config: ConductorConfig,
    enabled_tiers: Sequence[int],
    task_class: str,
) -> int | None:
    owner = next(
        (
            index
            for index, tier in enumerate(config.tiers)
            if task_class in tier.task_classes
        ),
        None,
    )
    if owner is None:
        return None
    valid_enabled = {index for index in enabled_tiers if 0 <= index < len(config.tiers)}
    candidates = [index for index in valid_enabled if index <= owner]
    return max(candidates) if candidates else None


def _frontier_index(
    config: ConductorConfig, enabled_tiers: Sequence[int]
) -> int | None:
    for index, tier in enumerate(config.tiers):
        if tier.name == "frontier":
            return index if index in enabled_tiers else None
    return None


def _requested_model(operation: NormalizedOperation) -> str | None:
    for name in ("model", "model_slug", "requested_model"):
        value = operation.payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _savings_eligible(
    mode: OperatingMode, caller_index: int, target_index: int
) -> bool:
    return mode is OperatingMode.ROUTING and target_index > caller_index


def _result(
    allowed: bool,
    rule: str,
    message: str,
    *,
    tier: TierConfig | None = None,
    selected_model: str | None = None,
    estimate: float = 0.0,
    reserve: bool = False,
    savings: bool = False,
) -> PolicyEvaluation:
    return PolicyEvaluation(
        spec=DecisionSpec(
            allowed=allowed,
            rule=rule,
            message=message,
            selected_model=selected_model,
            savings_eligible=savings,
            reserve=reserve and allowed,
        ),
        tier=tier,
        selected_model=selected_model,
        estimate_usd=estimate,
        reserve=reserve and allowed,
    )
