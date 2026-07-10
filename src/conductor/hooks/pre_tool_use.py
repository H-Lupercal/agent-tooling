from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime

from conductor.capabilities import contract_digest, load_contract, negotiate
from conductor.config import (
    ConductorConfig,
    config_digest,
    enabled_tiers,
    load_config,
    models_cache_path,
)
from conductor.errors import ConductorError, StateError
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.identity import Caller
from conductor.ledger import store_path
from conductor.operations import canonical_operation
from conductor.policy import evaluate_policy
from conductor.schemas import (
    Decision,
    NormalizedOperation,
    OperatingMode,
    OperationName,
    RunContext,
)
from conductor.store import DecisionSpec, ReservationRequest, ReservationSnapshot, Store
from conductor.tool_adapter import normalize_governed_payload


def decide(
    payload: dict,
    config: ConductorConfig,
    store: Store,
    run: RunContext,
    caller: Caller,
    enabled: Sequence[int],
    *,
    provider_name: str | None = None,
) -> Decision:
    """Normalize, evaluate, and atomically reserve one hook operation."""

    provider = provider_name or run.provider.value
    normalized_payload = {**payload, "provider": provider}
    result = normalize_governed_payload(normalized_payload)
    operation = result.operation
    if operation is not None:
        from conductor.providers import get_provider

        provider_request = get_provider(provider).normalize_request(payload)
        if provider_request.requested_model is not None:
            operation_data = operation.model_dump(mode="python")
            operation_data["payload"] = {
                **operation.payload,
                "model": provider_request.requested_model,
            }
            operation = NormalizedOperation.model_validate(operation_data)

    if operation is None or not operation.is_new_work:
        return _ephemeral(
            allowed=True,
            rule="NOT_GOVERNED",
            message="operation is not new governed work",
            mode=run.mode,
            operation=operation,
        )
    if caller.run_id != run.run_id or caller.thread_id is None:
        return _identity_decision(
            config.policy.unknown_identity,
            "caller identity does not match the active run",
            run,
            operation,
        )
    if caller.tier_index is None:
        return _identity_decision(
            config.policy.unknown_model,
            "caller model is outside the configured ladder",
            run,
            operation,
        )
    if run.config_digest != config_digest(config):
        return _persist(
            store,
            operation,
            run,
            caller,
            config,
            enabled,
            forced=DecisionSpec(
                False,
                "CONFIG_DRIFT",
                "active run configuration differs from SessionStart",
            ),
        )
    if result.decision.rule != "NORMALIZED":
        return _persist(
            store,
            operation,
            run,
            caller,
            config,
            enabled,
            forced=DecisionSpec(
                result.decision.allowed,
                result.decision.rule,
                result.decision.message,
            ),
        )
    if (
        run.mode in {OperatingMode.ADMISSION, OperatingMode.ROUTING}
        and operation.correlation_id is None
    ):
        return _persist(
            store,
            operation,
            run,
            caller,
            config,
            enabled,
            forced=DecisionSpec(
                False,
                "MISSING_CORRELATION",
                "enforced work requires one bounded provider correlation id",
            ),
        )
    return _persist(store, operation, run, caller, config, enabled)


def _persist(
    store: Store,
    operation: NormalizedOperation,
    run: RunContext,
    caller: Caller,
    config: ConductorConfig,
    enabled: Sequence[int],
    *,
    forced: DecisionSpec | None = None,
) -> Decision:
    empty = ReservationSnapshot(active_by_tier={}, reserved_usd=0.0, spent_usd=0.0)
    preview = evaluate_policy(
        operation=operation,
        run=run,
        config=config,
        enabled_tiers=enabled,
        snapshot=empty,
        caller_model=caller.model,
        caller_depth=caller.depth,
    )
    caller_tier = config.tier_for_model(caller.model)
    tier = preview.tier or caller_tier or config.tiers[0]
    envelope = operation.envelope
    task_id = (
        envelope.task_name if envelope is not None else _derived_id("task", operation)
    )
    idempotency_key = operation.correlation_id or _derived_id("request", operation)
    request = ReservationRequest(
        run_id=run.run_id,
        task_id=task_id,
        correlation_id=operation.correlation_id,
        idempotency_key=idempotency_key,
        operation=operation.operation.value,
        tier=tier.name,
        model=tier.model,
        estimated_usd=preview.estimate_usd,
        ttl_seconds=config.policy.reservation_ttl_seconds,
        generation=run.generation,
        mode=run.mode.value,
    )

    def evaluator(snapshot: ReservationSnapshot) -> DecisionSpec:
        if forced is not None:
            return forced
        return evaluate_policy(
            operation=operation,
            run=run,
            config=config,
            enabled_tiers=enabled,
            snapshot=snapshot,
            caller_model=caller.model,
            caller_depth=caller.depth,
        ).spec

    return store.decide_and_reserve(request, evaluator)


def _identity_decision(
    posture: str,
    reason: str,
    run: RunContext,
    operation: NormalizedOperation,
) -> Decision:
    if posture == "observe":
        return _ephemeral(
            allowed=True,
            rule="IDENTITY_OBSERVE_ONLY",
            message=reason,
            mode=OperatingMode.OBSERVE,
            operation=operation,
        )
    rule = "IDENTITY_UNKNOWN" if posture == "deny" else "IDENTITY_DEGRADED"
    return _ephemeral(
        allowed=False,
        rule=rule,
        message=reason,
        mode=run.mode,
        operation=operation,
    )


def _ephemeral(
    *,
    allowed: bool,
    rule: str,
    message: str,
    mode: OperatingMode,
    operation: NormalizedOperation | None,
) -> Decision:
    return Decision(
        decision_id=_derived_id("decision", operation),
        allowed=allowed,
        rule=rule,
        message=message,
        mode=mode,
        operation=(
            operation.operation if operation is not None else OperationName.OTHER
        ),
        selected_model=None,
        reservation_estimate_usd=0.0,
        savings_eligible=False,
        reservation_id=None,
        created_at=datetime.now(UTC),
    )


def _derived_id(prefix: str, operation: NormalizedOperation | None) -> str:
    payload = (
        operation.model_dump(mode="json") if operation is not None else {"none": True}
    )
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return f"{prefix}-{hashlib.sha256(encoded).hexdigest()[:48]}"


def _effective_run_context(
    run: RunContext,
    payload: dict,
) -> RunContext:
    contract = load_contract(run.provider_contract)
    if contract_digest(contract) != run.contract_digest:
        raise StateError("active run provider contract digest drift")
    tool_input = payload.get("tool_input") or payload.get("input") or {}
    capability = negotiate(contract, tool_input)
    return run.model_copy(update={"mode": capability.mode})


def _is_governed(payload: dict) -> bool:
    name = str(payload.get("tool_name") or payload.get("name") or "")
    operation = canonical_operation(name)
    if operation in {"spawn", "assign"}:
        return True
    result = normalize_governed_payload(payload)
    return bool(result.operation and result.operation.is_new_work)


def main(argv: list[str] | None = None) -> int:
    from conductor.providers import get_provider

    args = _parse_args(argv)
    payload: dict = {}
    provider = get_provider(args.provider)
    try:
        payload = read_payload()
        if not _is_governed(payload):
            write_json(provider.emit_decision("approve", "not new governed work"))
            return 0

        config = load_config()
        caller = provider.resolve_caller(payload, config)
        if caller.run_id is None:
            decision = _ephemeral(
                allowed=False,
                rule="IDENTITY_UNKNOWN",
                message="cannot resolve active run id",
                mode=OperatingMode.UNSUPPORTED,
                operation=normalize_governed_payload(
                    {**payload, "provider": provider.name}
                ).operation,
            )
        else:
            store = Store(store_path(), busy_timeout_ms=config.policy.busy_timeout_ms)
            store.heartbeat_run(
                caller.run_id,
                lease_seconds=max(300, config.policy.reservation_ttl_seconds * 2),
            )
            run = _effective_run_context(store.run_context(caller.run_id), payload)
            decision = decide(
                payload,
                config,
                store,
                run,
                caller,
                enabled_tiers(config, models_cache_path()),
                provider_name=provider.name,
            )
        write_json(
            provider.emit_decision(
                "approve" if decision.allowed else "block",
                f"{decision.rule}: {decision.message}",
            )
        )
    except (ConductorError, OSError, ValueError, json.JSONDecodeError) as exc:
        log_error("pre_tool_use", exc)
        governed = _is_governed(payload)
        write_json(
            provider.emit_decision(
                "block" if governed else "approve",
                "CONDUCTOR_DEGRADED: governed work denied safely"
                if governed
                else "conductor unavailable for an ungoverned operation",
            )
        )
    except BaseException as exc:
        log_error("pre_tool_use", exc)
        governed = _is_governed(payload)
        write_json(
            provider.emit_decision(
                "block" if governed else "approve",
                "CONDUCTOR_INTERNAL_ERROR: governed work denied safely"
                if governed
                else "conductor internal error on an ungoverned operation",
            )
        )
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
