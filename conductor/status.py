from __future__ import annotations

import argparse
import json
import os

from conductor.config import enabled_tiers, load_ladder, models_cache_path, provider_home
from conductor.ledger import active_spawns, latest_run_id, read_events, reserved_usd, spent_usd
from conductor.pricing import pricing_verified


def build_status(run_id: str | None = None) -> dict:
    warnings: list[str] = []
    ladder = load_ladder()
    run_id = run_id or latest_run_id() or "none"
    events = [] if run_id == "none" else read_events(run_id)
    enabled = enabled_tiers(ladder, models_cache_path())
    active = {tier: len(items) for tier, items in active_spawns(events).items()}
    tiers_by_name = {tier.name: tier for tier in ladder.tiers}
    spent = spent_usd(events)
    reserved = reserved_usd(events, tiers_by_name)
    blocked = sum(1 for event in events if event.get("event") == "spawn_blocked")
    if spent + reserved >= ladder.budget.run_usd_cap * ladder.budget.warn_at_fraction:
        warnings.append("delegated-spawn budget warning threshold reached")
    verified = pricing_verified(ladder)
    if not verified:
        warnings.append("PRICING UNVERIFIED - edit conductor.toml")
    return {
        "run_id": run_id,
        "spent_usd": spent,
        "reserved_usd": reserved,
        "cap_usd": ladder.budget.run_usd_cap,
        "remaining_usd": max(ladder.budget.run_usd_cap - spent - reserved, 0.0),
        "enforce": ladder.budget.enforce,
        "active": active,
        "enabled_tiers": [
            {
                "name": ladder.tiers[index].name,
                "model": ladder.tiers[index].model,
                "reasoning_effort": ladder.tiers[index].reasoning_effort,
                "max_concurrent": ladder.tiers[index].max_concurrent,
                "task_classes": list(ladder.tiers[index].task_classes),
            }
            for index in enabled
        ],
        "pricing_verified": verified,
        "blocked_spawn_count": blocked,
        "warnings": warnings,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    try:
        status = build_status(args.run)
    except Exception as exc:
        status = {"warnings": [repr(exc)], "run_id": args.run or "none"}
    print(json.dumps(status, indent=2 if args.pretty else None, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
