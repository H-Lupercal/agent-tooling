from __future__ import annotations

import argparse
import json
import os
import sys

from conductor.capabilities import load_contract, selectable_models
from conductor.config import (
    enabled_tiers,
    load_config,
    models_cache_path,
    provider_home,
)
from conductor.errors import ConductorError, ExitCode, StateError
from conductor.ledger import store_path
from conductor.pricing import pricing_verified
from conductor.store import Store


def build_status(
    run_id: str | None = None,
    *,
    store: Store | None = None,
) -> dict:
    config = load_config()
    database = store or _existing_store()
    selected = run_id or database.latest_run_id()
    if selected is None:
        raise StateError("no conductor runs exist")
    snapshot = database.run_snapshot(selected)
    try:
        context = database.run_context(selected)
    except (AttributeError, StateError):
        selector_models = None
    else:
        selector_models = (
            selectable_models(load_contract(context.provider_contract))
            if context.provider.value == "codex"
            else None
        )
    enabled = enabled_tiers(
        config,
        models_cache_path(),
        selector_models,
    )
    warnings: list[str] = []
    committed = snapshot["costs"]["total_usd"] + snapshot["reserved_usd"]
    if committed >= config.budget.run_usd_cap * config.budget.warn_at_fraction:
        warnings.append("budget warning threshold reached")
    if not pricing_verified(config):
        warnings.append("pricing is unverified; dollar costs may use task estimates")
    if snapshot["lease"] is None or not snapshot["lease"]["active"]:
        warnings.append("run lease is inactive")
    if snapshot["recoverable"]:
        warnings.append(
            f"{snapshot['recoverable']} lifecycle record(s) require recovery"
        )
    active: dict[str, int] = {}
    for row in snapshot["reservations"]:
        if row["state"] in {"approved", "started"}:
            active[row["tier"]] = active.get(row["tier"], 0) + row["count"]
    return {
        "schema_version": 1,
        **snapshot,
        "cap_usd": config.budget.run_usd_cap,
        "remaining_usd": max(config.budget.run_usd_cap - committed, 0.0),
        "enforce": config.budget.enforce,
        "active": active,
        "enabled_tiers": [
            {
                "name": config.tiers[index].name,
                "model": config.tiers[index].model,
                "reasoning_effort": config.tiers[index].reasoning_effort,
                "max_concurrent": config.tiers[index].max_concurrent,
                "task_classes": list(config.tiers[index].task_classes),
            }
            for index in enabled
        ],
        "pricing_verified": pricing_verified(config),
        "warnings": warnings,
    }


def _existing_store() -> Store:
    path = store_path()
    if not path.exists():
        raise StateError(f"conductor store does not exist: {path}")
    return Store(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--run")
    selection.add_argument("--last", action="store_true")
    parser.add_argument("--pretty", action="store_true")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    try:
        status = build_status(args.run)
    except ConductorError as exc:
        print(f"conductor status: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except (OSError, ValueError) as exc:
        print(f"conductor status: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL)
    print(json.dumps(status, indent=2 if args.pretty else None, sort_keys=True))
    return int(ExitCode.SUCCESS)


if __name__ == "__main__":
    raise SystemExit(main())
