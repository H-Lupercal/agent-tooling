from __future__ import annotations

import argparse
from dataclasses import dataclass

from conductor.config import Ladder, enabled_tiers as load_enabled_tiers, load_ladder, models_cache_path
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.identity import Caller
from conductor.ledger import active_spawns, append_event, read_events, reserved_usd, same_tier_root_spawns, spent_usd
from conductor.tool_adapter import ToolRequest, normalize_tool_request


@dataclass(frozen=True)
class Decision:
    decision: str
    reason: str
    rule: str = "OK"


def decide(payload: dict, ladder: Ladder, events: list[dict], enabled: list[int], caller: Caller) -> Decision:
    return _decide(normalize_tool_request(payload, {}), ladder, events, enabled, caller)


def _decide(request: ToolRequest, ladder: Ladder, events: list[dict], enabled: list[int], caller: Caller) -> Decision:
    if request.kind not in {"spawn", "new_task"}:
        return Decision("approve", "not a governed agent task")
    if caller.run_id is None:
        return Decision("block", "cannot resolve root run id; cannot enforce conductor budget safely", "R1")
    if request.envelope is None:
        return Decision("block", "missing or invalid conductor_task envelope", "R2")
    if caller.depth + 1 > ladder.policy.max_depth:
        return Decision("block", f"depth limit {ladder.policy.max_depth} reached; do the task yourself", "R3")
    if caller.tier_index is None:
        _append(caller.run_id, {"event": "ungoverned_caller", "model": caller.model})
        return Decision("approve", "caller model is outside conductor ladder", "R4")
    caller_tier = ladder.tiers[caller.tier_index]
    if not caller_tier.may_spawn:
        return Decision("block", f"tier {caller_tier.name} may not spawn subagents; do the task yourself", "R5")
    requested_model = request.requested_model or caller.model
    child_index = ladder.tier_index_for_model(requested_model)
    if child_index is None or child_index not in enabled:
        names = ", ".join(f"{ladder.tiers[index].name}={ladder.tiers[index].model}" for index in enabled)
        return Decision("block", f"model {requested_model} not in the enabled ladder; enabled: {names}", "R6")
    child_tier = ladder.tiers[child_index]
    envelope = request.envelope
    if (envelope.task_class == "high_risk" or envelope.risk_triggers) and child_tier.name != "frontier":
        return Decision("block", "high_risk tasks require frontier tier", "R7")
    allowed_index = _allowed_tier_index_for_class(ladder, enabled, envelope.task_class)
    if allowed_index is None:
        return Decision("block", f"task class {envelope.task_class} has no enabled tier", "R6_CLASS")
    if child_index != allowed_index:
        allowed = ladder.tiers[allowed_index]
        return Decision("block", f"task class {envelope.task_class} must run on tier {allowed.name} ({allowed.model})", "R6_CLASS")
    if child_index < caller.tier_index:
        return Decision("block", "never spawn a stronger model", "R8")
    if ladder.policy.require_strictly_cheaper and child_index == caller.tier_index:
        allowed = caller.depth == 0 and same_tier_root_spawns(events) < ladder.policy.same_tier_spawns_from_root_max
        if not allowed:
            cheaper = ", ".join(tier.model for index, tier in enumerate(ladder.tiers) if index > caller.tier_index and index in enabled)
            return Decision("block", f"child must be strictly cheaper; pick one of: {cheaper}", "R8")
    active = active_spawns(events)
    if len(active.get(child_tier.name, [])) >= child_tier.max_concurrent:
        return Decision("block", f"tier {child_tier.name} at max_concurrent={child_tier.max_concurrent}; wait_agent on an existing agent first", "R9")
    tiers_by_name = {tier.name: tier for tier in ladder.tiers}
    spent = spent_usd(events)
    reserved = reserved_usd(events, tiers_by_name)
    if spent + reserved + child_tier.est_task_usd > ladder.budget.run_usd_cap:
        reason = (
            f"spawn budget cap ${ladder.budget.run_usd_cap:.2f} would be exceeded "
            f"(spent ${spent:.2f}, reserved ${reserved:.2f}); finish remaining work yourself and summarize"
        )
        if ladder.budget.enforce:
            return Decision("block", reason, "R10")
        _append(caller.run_id, {"event": "budget_warning", "reason": reason})
        return Decision("approve", reason, "R10_WARN")
    _append(
        caller.run_id,
        {
            "event": "spawn_approved",
            "task_name": envelope.task_name,
            "task_class": envelope.task_class,
            "risk_triggers": list(envelope.risk_triggers),
            "owned_paths": list(envelope.owned_paths),
            "model": child_tier.model,
            "tier": child_tier.name,
            "caller_tier": caller_tier.name,
            "caller_thread_id": caller.thread_id,
            "caller_depth": caller.depth,
        },
    )
    return Decision("approve", "spawn approved")


def _allowed_tier_index_for_class(ladder: Ladder, enabled: list[int], task_class: str) -> int | None:
    owner_index = None
    for index, tier in enumerate(ladder.tiers):
        if task_class in tier.task_classes:
            owner_index = index
            break
    if owner_index is None:
        return None
    candidates = [index for index in enabled if index <= owner_index]
    if not candidates:
        return None
    return max(candidates)


def _append(run_id: str | None, event: dict) -> None:
    if run_id:
        try:
            append_event(run_id, event)
        except OSError as exc:
            log_error("pre_tool_use", exc)


def main(argv: list[str] | None = None) -> int:
    from conductor.providers import codex, get_provider

    args = _parse_args(argv)
    try:
        provider = get_provider(args.provider)
    except ValueError:
        provider = codex.PROVIDER
    try:
        payload = read_payload()
        ladder = load_ladder()
        caller = provider.resolve_caller(payload, ladder)
        request = provider.normalize_request(payload)
        events = read_events(caller.run_id) if caller.run_id else []
        decision = _decide(request, ladder, events, load_enabled_tiers(ladder, models_cache_path()), caller)
        if decision.decision == "block":
            _append(caller.run_id, {"event": "spawn_blocked", "rule": decision.rule, "reason": decision.reason})
        elif request.kind in {"spawn", "new_task"}:
            for event in provider.post_approve_events(request, caller, ladder):
                _append(caller.run_id, event)
        write_json(provider.emit_decision(decision.decision, decision.reason))
    except BaseException as exc:
        log_error("pre_tool_use", exc)
        write_json(provider.emit_decision("approve", "codex-conductor failed open"))
    return 0


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="codex")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
