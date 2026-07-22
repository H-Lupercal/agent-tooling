from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from conductor.config import ConductorConfig, TierConfig
from conductor.schemas import (
    REASONING_EFFORTS,
    NormalizedOperation,
    OperatingMode,
    OperationName,
    Provider,
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
    reasoning_effort: str | None
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
    caller_effort: str = "",
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

    forced_frontier = envelope.task_class == "high_risk" or bool(envelope.risk_triggers)
    model_led_routing = run.mode is OperatingMode.ROUTING
    # Effort is enforced only for a provider whose contract exposes a VERIFIED
    # per-call reasoning-effort selector. Today that is Codex alone: the Claude
    # Task tool exposes a model selector but no per-call effort field, so Claude
    # gets model-led routing with effort left unenforced (recorded as NULL).
    # This proxy is guarded by capabilities.py and tests/test_capabilities.py
    # (test_codex_contract_without_effort_control_cannot_claim_routing,
    #  test_claude_keeps_existing_model_only_routing_contract) and by
    # test_effort_authority_matches_verified_contract_selectors. If a future
    # Claude contract adds a verified effort selector, update this line and that
    # test together.
    effort_enforced = run.provider is Provider.CODEX
    requested_effort: str | None = None

    if model_led_routing:
        requested_model = _requested_model(operation)
        if effort_enforced:
            requested_effort = _requested_effort(operation)
            inherits_authority = (
                operation.payload.get("fork_turns") == "all"
                and requested_model is None
                and requested_effort is None
            )
            if inherits_authority:
                requested_model = caller_model
                requested_effort = caller_effort
            if requested_model is None:
                return _result(
                    False,
                    "MISSING_MODEL_SELECTION",
                    "Codex routing requires the orchestrator to choose a worker model",
                )
            if requested_effort is None:
                return _result(
                    False,
                    "MISSING_EFFORT_SELECTION",
                    "Codex routing requires the orchestrator to choose worker reasoning effort",
                )
        else:
            # Claude: an omitted model inherits the caller's model (the
            # documented Agent-tool default). Per-call effort is unobservable,
            # so it is left unenforced and recorded as NULL.
            if requested_model is None:
                requested_model = caller_model
            requested_effort = None
        target_index = config.tier_index_for_model(requested_model)
        if target_index is None:
            return _result(
                False,
                "UNKNOWN_TARGET_MODEL",
                f"requested model {requested_model} is outside the configured ladder",
            )
        if target_index not in enabled_tiers:
            return _result(
                False,
                "TARGET_MODEL_DISABLED",
                f"requested model {requested_model} is not enabled",
            )
        if forced_frontier:
            frontier_index = _frontier_index(config, enabled_tiers)
            if frontier_index is None:
                return _result(
                    False,
                    "FRONTIER_UNAVAILABLE",
                    "high-risk work requires an enabled frontier tier",
                )
            if caller_index != frontier_index:
                return _result(
                    False,
                    "HIGH_RISK_CALLER_NOT_FRONTIER",
                    "the current caller cannot delegate high-risk work to a stronger frontier model; keep it local",
                )
            if target_index != frontier_index:
                frontier = config.tiers[frontier_index]
                return _result(
                    False,
                    "HIGH_RISK_REQUIRES_FRONTIER",
                    f"high-risk work must remain on frontier model {frontier.model}",
                )
        target = config.tiers[target_index]
        selected_model = target.model
        estimate = float(target.est_task_usd)

        if target.model != caller_tier.model and (
            target.generation_rank is None or caller_tier.generation_rank is None
        ):
            return _result(
                False,
                "UNKNOWN_MODEL_AUTHORITY",
                "cross-model Codex routing requires explicit generation ranks for both caller and worker",
                tier=target,
                selected_model=selected_model,
                effort=requested_effort,
                estimate=estimate,
            )
        if (
            target.generation_rank is not None
            and caller_tier.generation_rank is not None
            and target.generation_rank > caller_tier.generation_rank
        ):
            return _result(
                False,
                "MODEL_GENERATION_CEILING",
                f"requested model {target.model} is newer than caller ceiling {caller_model}",
                tier=target,
                selected_model=selected_model,
                effort=requested_effort,
                estimate=estimate,
            )
        if target.effective_capability_rank > caller_tier.effective_capability_rank:
            return _result(
                False,
                "MODEL_CAPABILITY_CEILING",
                f"requested model {target.model} exceeds caller capability ceiling {caller_model}",
                tier=target,
                selected_model=selected_model,
                effort=requested_effort,
                estimate=estimate,
            )
        if effort_enforced:
            if caller_effort not in REASONING_EFFORTS:
                return _result(
                    False,
                    "UNKNOWN_CALLER_EFFORT",
                    "caller reasoning effort is unavailable; Codex routing fails closed",
                    tier=target,
                    selected_model=selected_model,
                    effort=requested_effort,
                    estimate=estimate,
                )
            if requested_effort not in REASONING_EFFORTS:
                return _result(
                    False,
                    "UNKNOWN_TARGET_EFFORT",
                    f"requested effort {requested_effort!r} is not canonical",
                    tier=target,
                    selected_model=selected_model,
                    effort=requested_effort,
                    estimate=estimate,
                )
            if REASONING_EFFORTS.index(requested_effort) > REASONING_EFFORTS.index(
                caller_effort
            ):
                return _result(
                    False,
                    "EFFORT_CEILING",
                    f"requested effort {requested_effort} exceeds caller ceiling {caller_effort}; choose an effort at or below {caller_effort}",
                    tier=target,
                    selected_model=selected_model,
                    effort=requested_effort,
                    estimate=estimate,
                )
            if not target.supports_effort(requested_effort):
                return _result(
                    False,
                    "UNSUPPORTED_MODEL_EFFORT",
                    f"model {target.model} supports effort only through {target.reasoning_effort}",
                    tier=target,
                    selected_model=selected_model,
                    effort=requested_effort,
                    estimate=estimate,
                )

        strictly_cheaper = (
            target.relative_cost_weight < caller_tier.relative_cost_weight
        )
        exact_same_model = target.model == caller_tier.model
        if config.policy.require_strictly_cheaper and not strictly_cheaper:
            exception_allowed = (
                exact_same_model
                and caller_depth == 0
                and snapshot.active_by_tier.get(target.name, 0)
                < config.policy.same_tier_spawns_from_root_max
            )
            if not exception_allowed:
                rule = (
                    "SAME_TIER_LIMIT"
                    if exact_same_model and caller_depth == 0
                    else "STRICTLY_CHEAPER_REQUIRED"
                )
                return _result(
                    False,
                    rule,
                    "child must be strictly cheaper; the bounded root same-model exception is unavailable",
                    tier=target,
                    selected_model=selected_model,
                    effort=requested_effort,
                    estimate=estimate,
                )
    else:
        target_index = _target_tier_index(config, enabled_tiers, envelope.task_class)
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
                    "SAME_TIER_LIMIT"
                    if caller_depth == 0
                    else "STRICTLY_CHEAPER_REQUIRED"
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
            effort=requested_effort,
            savings=_savings_eligible(run.mode, caller_tier, target),
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
        effort=requested_effort,
        estimate=estimate,
        reserve=True,
        savings=_savings_eligible(run.mode, caller_tier, target),
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


def _requested_effort(operation: NormalizedOperation) -> str | None:
    for name in ("reasoning_effort", "model_reasoning_effort"):
        value = operation.payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _savings_eligible(
    mode: OperatingMode, caller: TierConfig, target: TierConfig
) -> bool:
    return (
        mode is OperatingMode.ROUTING
        and target.relative_cost_weight < caller.relative_cost_weight
    )


def _result(
    allowed: bool,
    rule: str,
    message: str,
    *,
    tier: TierConfig | None = None,
    selected_model: str | None = None,
    effort: str | None = None,
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
        reasoning_effort=effort,
        estimate_usd=estimate,
        reserve=reserve and allowed,
    )
