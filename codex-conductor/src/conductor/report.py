from __future__ import annotations

import argparse
import json
import os
import sys

from conductor.config import default_config_path, load_config, provider_home
from conductor.errors import ConductorError, ExitCode, StateError
from conductor.ledger import store_path
from conductor.pricing import pricing_verified
from conductor.store import Store


def build_report(
    run_id: str | None = None,
    *,
    store: Store | None = None,
) -> dict:
    config = load_config()
    database = store or _existing_store()
    selected = run_id or database.latest_run_id()
    if selected is None:
        raise StateError("no conductor runs exist")
    snapshot = database.report_snapshot(selected)
    rows: dict[str, dict] = {}
    for raw in snapshot["tiers"]:
        tier = str(raw["tier"])
        rows[tier] = {
            "reservations": int(raw["reservations"]),
            "completed": int(raw["completed"]),
            "failed": int(raw["failed"]),
            "input_tokens": 0,
            "cache_read_tokens": 0,
            "cache_write_tokens": 0,
            "output_tokens": 0,
            "reasoning_tokens": 0,
            "measured_usd": float(raw["measured_usd"]),
            "estimated_usd": float(raw["estimated_usd"]),
            "savings_eligible": int(raw["savings_eligible"]),
            "routed_estimate_usd": float(raw["routed_estimate_usd"]),
        }
    for usage_row in snapshot["usage"]:
        model = usage_row["model"]
        tier_config = config.tier_for_model(model)
        tier = tier_config.name if tier_config is not None else "unknown"
        row = rows.setdefault(
            tier,
            {
                "reservations": 0,
                "completed": 0,
                "failed": 0,
                "input_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "measured_usd": 0.0,
                "estimated_usd": 0.0,
                "savings_eligible": 0,
                "routed_estimate_usd": 0.0,
            },
        )
        usage = usage_row["payload"]
        for field in (
            "input_tokens",
            "cache_read_tokens",
            "cache_write_tokens",
            "output_tokens",
            "reasoning_tokens",
        ):
            row[field] += int(usage.get(field, 0))

    measured = sum(row["measured_usd"] for row in rows.values())
    estimated = sum(row["estimated_usd"] for row in rows.values())
    savings_eligible = sum(row["savings_eligible"] for row in rows.values())
    if snapshot["mode"] == "routing":
        frontier_estimate = float(config.tiers[0].est_task_usd)
        baseline = savings_eligible * frontier_estimate
        routed = sum(row["routed_estimate_usd"] for row in rows.values())
        projected_savings: float | None = max(baseline - routed, 0.0)
        savings_basis = "configured task estimates for routing-eligible decisions"
    else:
        projected_savings = None
        savings_basis = "unavailable outside routing mode"
    return {
        "schema_version": 1,
        "run_id": selected,
        "provider": snapshot["provider"],
        "mode": snapshot["mode"],
        "config_path": str(default_config_path()),
        "pricing_verified": pricing_verified(config),
        "tiers": rows,
        "measured_usd": measured,
        "estimated_usd": estimated,
        "total_usd": measured + estimated,
        "projected_savings_usd": projected_savings,
        "savings_basis": savings_basis,
    }


def render_human(report: dict) -> str:
    lines: list[str] = []
    if not report["pricing_verified"]:
        lines.append(f"PRICING UNVERIFIED - edit {report['config_path']}")
    lines.append(
        f"run_id: {report['run_id']}  provider: {report['provider']}  mode: {report['mode']}"
    )
    lines.append(
        "tier        reserve  done  fail     input   cached  output  measured$ estimated$"
    )
    for tier, row in sorted(report["tiers"].items()):
        lines.append(
            f"{tier:<11} {row['reservations']:>7} {row['completed']:>5} {row['failed']:>5} "
            f"{row['input_tokens']:>9} {row['cache_read_tokens']:>8} {row['output_tokens']:>7} "
            f"{row['measured_usd']:>9.6f} {row['estimated_usd']:>10.6f}"
        )
    savings = (
        "n/a"
        if report["projected_savings_usd"] is None
        else f"${report['projected_savings_usd']:.6f}"
    )
    lines.append(
        f"TOTAL measured=${report['measured_usd']:.6f} "
        f"estimated=${report['estimated_usd']:.6f} total=${report['total_usd']:.6f} "
        f"projected_savings={savings}"
    )
    lines.append(f"savings_basis: {report['savings_basis']}")
    return "\n".join(lines)


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
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    try:
        report = build_report(args.run)
    except ConductorError as exc:
        print(f"conductor report: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except (OSError, ValueError) as exc:
        print(f"conductor report: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL)
    print(
        json.dumps(report, indent=2, sort_keys=True)
        if args.json
        else render_human(report)
    )
    return int(ExitCode.SUCCESS)


if __name__ == "__main__":
    raise SystemExit(main())
