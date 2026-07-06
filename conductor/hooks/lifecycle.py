from __future__ import annotations

import os
import time
from pathlib import Path

from conductor.config import load_ladder
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.identity import resolve_caller
from conductor.ledger import append_event
from conductor.pricing import estimate_usd, pricing_verified
from conductor.rollout import latest_usage


def handle(payload: dict) -> None:
    event_name = str(payload.get("hook_event_name") or payload.get("event") or "")
    run_id = _run_id(payload)
    thread_id = str(payload.get("thread_id") or f"unknown-{int(__import__('time').time())}")
    model = payload.get("model")
    if event_name in {"SubagentStart", "subagent_start"}:
        append_event(
            run_id,
            {
                "event": "subagent_start",
                "thread_id": thread_id,
                "parent_thread_id": payload.get("parent_thread_id"),
                "model": model,
                "tier": _tier_name(model),
                "agent_type": payload.get("agent_type"),
            },
        )
    elif event_name in {"SubagentStop", "subagent_stop"}:
        append_event(run_id, {"event": "subagent_stop", "thread_id": thread_id, "status": payload.get("status"), "model": model, "tier": _tier_name(model)})
        _record_cost(run_id, thread_id, model, payload.get("agent_transcript_path") or payload.get("transcript_path"))


def _tier_name(model: str | None) -> str:
    try:
        ladder = load_ladder()
    except Exception:
        return "unknown"
    tier = ladder.tier_for_model(str(model or ""))
    return tier.name if tier else "unknown"


def _run_id(payload: dict) -> str:
    explicit = payload.get("root_thread_id") or payload.get("run_id")
    if explicit:
        return str(explicit)
    try:
        ladder = load_ladder()
        sessions_root = Path(os.environ.get("CODEX_CONDUCTOR_SESSIONS_ROOT", Path.home() / ".codex" / "sessions"))
        caller = resolve_caller(payload, ladder, sessions_root)
        if caller.run_id:
            return caller.run_id
    except Exception:
        pass
    return f"unknown-{int(time.time())}"


def _record_cost(run_id: str, thread_id: str, model: str | None, transcript_path: str | None) -> None:
    ladder = load_ladder()
    tier = ladder.tier_for_model(str(model or "")) or ladder.tiers[0]
    usage = latest_usage(Path(transcript_path)) if transcript_path else None
    if usage is None:
        append_event(
            run_id,
            {"event": "cost_recorded", "thread_id": thread_id, "model": model, "tier": tier.name, "tokens": None, "usd": tier.est_task_usd, "estimated": True},
        )
        return
    append_event(
        run_id,
        {
            "event": "cost_recorded",
            "thread_id": thread_id,
            "model": model,
            "tier": tier.name,
            "tokens": usage.as_dict(),
            "usd": estimate_usd(usage, tier, ladder),
            "estimated": not pricing_verified(ladder),
        },
    )


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
        provider.handle_lifecycle(read_payload())
        write_json({})
    except BaseException as exc:
        log_error("lifecycle", exc)
        write_json({})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
