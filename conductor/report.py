from __future__ import annotations

import argparse
import json
from collections import defaultdict

from conductor.config import default_config_path, load_ladder
from conductor.ledger import latest_run_id, read_events, spent_usd
from conductor.pricing import TokenUsage, cost_usd, pricing_verified, token_usage_from_dict


def build_report(run_id: str | None = None) -> dict:
    config_path = default_config_path()
    ladder = load_ladder()
    run_id = run_id or latest_run_id() or "none"
    events = [] if run_id == "none" else read_events(run_id)
    rows: dict[str, dict] = defaultdict(lambda: {"spawns": 0, "completed": 0, "failed": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "usd": 0.0})
    for event in events:
        tier = str(event.get("tier") or "unknown")
        if event.get("event") == "spawn_approved":
            rows[tier]["spawns"] += 1
        elif event.get("event") == "subagent_stop":
            if event.get("status") in {"failed", "error"}:
                rows[tier]["failed"] += 1
            else:
                rows[tier]["completed"] += 1
        elif event.get("event") == "cost_recorded":
            usage = token_usage_from_dict(event.get("tokens"))
            if usage:
                rows[tier]["input_tokens"] += usage.input_tokens
                rows[tier]["cached_input_tokens"] += usage.cached_input_tokens
                rows[tier]["output_tokens"] += usage.output_tokens
                rows[tier]["total_tokens"] += usage.total_tokens
            rows[tier]["usd"] += float(event.get("usd") or 0.0)
    total_usd = spent_usd(events)
    frontier = ladder.tiers[0]
    total_usage = TokenUsage(
        input_tokens=sum(row["input_tokens"] for row in rows.values()),
        cached_input_tokens=sum(row["cached_input_tokens"] for row in rows.values()),
        output_tokens=sum(row["output_tokens"] for row in rows.values()),
        reasoning_output_tokens=0,
        total_tokens=sum(row["total_tokens"] for row in rows.values()),
    )
    baseline = cost_usd(total_usage, frontier) if pricing_verified(ladder) else total_usage.total_tokens / 1_000_000 * frontier.relative_cost_weight * 0.05
    savings = baseline - total_usd
    return {
        "run_id": run_id,
        "config_path": str(config_path),
        "pricing_verified": pricing_verified(ladder),
        "tiers": dict(rows),
        "total_usd": total_usd,
        "baseline_usd": baseline,
        "savings_usd": savings,
        "savings_pct": (savings / baseline * 100.0) if baseline else 0.0,
    }


def render_human(report: dict) -> str:
    lines: list[str] = []
    if not report["pricing_verified"]:
        lines.append(f"PRICING UNVERIFIED - edit {report.get('config_path', '~/.codex/conductor/conductor.toml')}")
    lines.append(f"run_id: {report['run_id']}")
    lines.append("tier        spawns  done  fail  input  cached  output  usd")
    for tier, row in sorted(report["tiers"].items()):
        lines.append(
            f"{tier:<11} {row['spawns']:>6} {row['completed']:>5} {row['failed']:>5} "
            f"{row['input_tokens']:>6} {row['cached_input_tokens']:>7} {row['output_tokens']:>7} {row['usd']:.6f}"
        )
    lines.append(f"TOTAL usd={report['total_usd']:.6f} baseline_usd={report['baseline_usd']:.6f} savings_usd={report['savings_usd']:.6f} savings_pct={report['savings_pct']:.2f}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run")
    parser.add_argument("--last", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--sessions-root")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.run if not args.last else None)
    except Exception as exc:
        print(repr(exc))
        return 1
    print(json.dumps(report, indent=2, sort_keys=True) if args.json else render_human(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
