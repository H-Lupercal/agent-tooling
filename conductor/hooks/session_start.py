from __future__ import annotations

import json
from pathlib import Path

from conductor.config import enabled_tiers, load_ladder, models_cache_path
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.ledger import append_event, run_state_dir
from conductor.pricing import pricing_verified


def handle(payload: dict, run_id: str | None = None) -> None:
    thread_id = str(run_id or payload.get("root_thread_id") or payload.get("thread_id") or payload.get("run_id") or "")
    if not thread_id:
        return
    ladder = load_ladder()
    enabled = enabled_tiers(ladder, models_cache_path())
    state = run_state_dir(thread_id)
    state.mkdir(parents=True, exist_ok=True)
    status = {
        "run_id": thread_id,
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
        "cap_usd": ladder.budget.run_usd_cap,
        "pricing_verified": pricing_verified(ladder),
    }
    (state / "ladder_status.json").write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    append_event(thread_id, {"event": "run_started"})


def main(argv: list[str] | None = None) -> int:
    import argparse

    from conductor.providers import codex, get_provider

    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="codex")
    args = parser.parse_args(argv)
    try:
        provider = get_provider(args.provider)
    except ValueError:
        provider = codex.PROVIDER
    try:
        payload = read_payload()
        handle(payload, provider.session_run_id(payload))
        write_json({})
    except BaseException as exc:
        log_error("session_start", exc)
        write_json({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
