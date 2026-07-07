from __future__ import annotations

import json
import uuid
from pathlib import Path

from conductor.config import Ladder, load_ladder
from conductor.identity import Caller
from conductor.ledger import active_spawns, append_event, read_events
from conductor.pricing import TokenUsage, estimate_usd, pricing_verified
from conductor.providers.base import Provider
from conductor.tool_adapter import ToolRequest, extract_envelope

# Claude Code exposes model choices as short aliases; the ladder is keyed on the
# full model ids. Full ids (anything not an alias) pass through unchanged.
MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}

_RAW_FIELDS = ("input", "cache_read", "cache_creation", "output")


class ClaudeProvider(Provider):
    name = "claude"

    def normalize_request(self, payload: dict) -> ToolRequest:
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        tool_input = payload.get("tool_input") or payload.get("input") or {}
        if not isinstance(tool_input, dict):
            tool_input = {}
        if tool_name != "Task":
            return ToolRequest(kind="other", tool_name=tool_name, requested_model=None, task_name=None, envelope=None)
        prompt = "\n".join(str(tool_input[key]) for key in ("description", "prompt") if isinstance(tool_input.get(key), str))
        envelope = extract_envelope(prompt)
        requested_model = _resolve_model(tool_input.get("model"))
        subagent_type = tool_input.get("subagent_type")
        task_name = envelope.task_name if envelope else (str(subagent_type) if isinstance(subagent_type, str) else None)
        return ToolRequest(kind="spawn", tool_name=tool_name, requested_model=requested_model, task_name=task_name, envelope=envelope)

    def resolve_caller(self, payload: dict, ladder: Ladder) -> Caller:
        run_id = payload.get("session_id") or payload.get("root_thread_id") or payload.get("run_id")
        run_id_str = str(run_id) if run_id else None
        agent_id = payload.get("agent_id")
        if run_id_str and agent_id:
            active = [event for items in active_spawns(read_events(run_id_str)).values() for event in items]
            current = next((event for event in active if str(event.get("thread_id")) == str(agent_id)), None)
            if current:
                model = str(current.get("model") or "")
                return Caller(run_id=run_id_str, thread_id=str(agent_id), depth=1, tier_index=ladder.tier_index_for_model(model), model=model)
        model = ""
        transcript = payload.get("transcript_path")
        if transcript:
            found = _latest_main_model(Path(transcript))
            if found:
                model = found
        if not model and ladder.tiers:
            # SessionStart usually supplies the root model, but PreToolUse does
            # not guarantee it. Fall back to the frontier tier for root calls.
            model = ladder.tiers[0].model
        return Caller(run_id=run_id_str, thread_id=run_id_str, depth=0, tier_index=ladder.tier_index_for_model(model), model=model)

    def emit_decision(self, decision: str, reason: str) -> dict:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if decision == "approve" else "deny",
                "permissionDecisionReason": reason,
            }
        }

    def post_approve_events(self, request: ToolRequest, caller: Caller, ladder: Ladder) -> list[dict]:
        # PreToolUse knows the requested model/tier. SubagentStart supplies the
        # real agent id. Link them with a pending record instead of inventing a
        # synthetic subagent_start.
        if request.kind not in {"spawn", "new_task"}:
            return []
        model = request.requested_model or caller.model
        tier = ladder.tier_for_model(model)
        return [
            {
                "event": "claude_spawn_pending",
                "pending_id": f"claude-{uuid.uuid4().hex}",
                "parent_thread_id": caller.thread_id,
                "model": model,
                "tier": tier.name if tier else "unknown",
                "task_name": request.task_name,
            }
        ]

    def handle_lifecycle(self, payload: dict) -> None:
        event_name = str(payload.get("hook_event_name") or payload.get("event") or "")
        run_id = payload.get("session_id") or payload.get("root_thread_id") or payload.get("run_id")
        if not run_id:
            return
        run_id = str(run_id)
        ladder = load_ladder()
        events = read_events(run_id)
        if event_name in {"SubagentStart", "subagent_start"}:
            _record_subagent_start(run_id, ladder, events, payload)
            return
        if event_name not in {"SubagentStop", "subagent_stop"}:
            return
        # SubagentStop supplies agent_transcript_path: the finished subagent's own
        # transcript, keyed by agent_id. Prefer it for accurate per-subagent cost.
        # Fall back to sidechain rows in the main transcript for builds that inline
        # subagent usage there and omit a separate agent transcript.
        recorded = _record_agent_transcript_cost(run_id, ladder, events, payload)
        if not recorded:
            transcript = payload.get("transcript_path")
            current = _sidechain_usage(Path(transcript)) if transcript else {}
            recorded = _record_cost_delta(run_id, ladder, events, current)
        if not recorded:
            # No usage was parseable from either transcript; charge the tier's
            # reserved estimate so spend still reflects the completed subagent.
            _record_estimated_cost(run_id, ladder, events, payload)
        _close_subagent(run_id, events, payload)

    def session_run_id(self, payload: dict) -> str | None:
        value = payload.get("session_id") or payload.get("root_thread_id") or payload.get("run_id")
        return str(value) if value else None


def _resolve_model(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    stripped = value.strip()
    return MODEL_ALIASES.get(stripped, stripped)


def _record_cost_delta(run_id: str, ladder: Ladder, events: list[dict], current: dict[str, dict]) -> bool:
    snapshot = _latest_snapshot(events)
    verified = pricing_verified(ladder)
    recorded = False
    for model, totals in current.items():
        prev = snapshot.get(model, {})
        delta = {field: max(int(totals.get(field, 0)) - int(prev.get(field, 0) or 0), 0) for field in _RAW_FIELDS}
        usage = _to_token_usage(delta)
        if usage.total_tokens <= 0:
            continue
        tier = ladder.tier_for_model(model) or ladder.tiers[0]
        append_event(
            run_id,
            {
                "event": "cost_recorded",
                "thread_id": None,
                "model": model,
                "tier": tier.name,
                "tokens": usage.as_dict(),
                "usd": estimate_usd(usage, tier, ladder),
                "estimated": not verified,
            },
        )
        recorded = True
    if recorded:
        append_event(run_id, {"event": "sidechain_snapshot", "by_model": current})
    return recorded


def _record_estimated_cost(run_id: str, ladder: Ladder, events: list[dict], payload: dict) -> None:
    if not ladder.tiers:
        return
    agent_id = payload.get("agent_id") or payload.get("thread_id")
    thread_id = str(agent_id) if agent_id else None
    start = _matching_start(events, thread_id)
    tier = _start_tier(ladder, start) or ladder.tiers[0]
    append_event(
        run_id,
        {
            "event": "cost_recorded",
            "thread_id": thread_id,
            "model": (start or {}).get("model"),
            "tier": tier.name,
            "tokens": None,
            "usd": tier.est_task_usd,
            "estimated": True,
        },
    )


def _record_agent_transcript_cost(run_id: str, ladder: Ladder, events: list[dict], payload: dict) -> bool:
    agent_transcript = payload.get("agent_transcript_path")
    main_transcript = payload.get("transcript_path")
    # A distinct per-agent transcript holds only this subagent's turns, so sum all
    # of its assistant usage. If it points at the shared main transcript, we cannot
    # tell it apart from the parent's turns here; let the sidechain fallback handle it.
    if not agent_transcript or agent_transcript == main_transcript:
        return False
    usage_by_model = _transcript_usage(Path(agent_transcript))
    if not usage_by_model:
        return False
    agent_id = payload.get("agent_id") or payload.get("thread_id")
    thread_id = str(agent_id) if agent_id else None
    start = _matching_start(events, thread_id)
    verified = pricing_verified(ladder)
    for model, raw in usage_by_model.items():
        usage = _to_token_usage(raw)
        tier = ladder.tier_for_model(model) or _start_tier(ladder, start) or ladder.tiers[0]
        append_event(
            run_id,
            {
                "event": "cost_recorded",
                "thread_id": thread_id,
                "model": model,
                "tier": tier.name,
                "tokens": usage.as_dict(),
                "usd": estimate_usd(usage, tier, ladder),
                "estimated": not verified,
            },
        )
    return True


def _matching_start(events: list[dict], thread_id: str | None) -> dict | None:
    if not thread_id:
        return None
    match = None
    for event in events:
        if event.get("event") == "subagent_start" and str(event.get("thread_id")) == thread_id:
            match = event
    return match


def _start_tier(ladder: Ladder, start: dict | None):
    if not start:
        return None
    name = start.get("tier")
    for tier in ladder.tiers:
        if tier.name == name:
            return tier
    model = start.get("model")
    return ladder.tier_for_model(str(model or "")) if model else None


def _record_subagent_start(run_id: str, ladder: Ladder, events: list[dict], payload: dict) -> None:
    pending = _oldest_pending_spawn(events)
    thread_id = payload.get("agent_id") or payload.get("thread_id") or f"claude-{uuid.uuid4().hex}"
    model = (pending or {}).get("model") or payload.get("model")
    tier = (pending or {}).get("tier")
    if not tier:
        tier_obj = ladder.tier_for_model(str(model or ""))
        tier = tier_obj.name if tier_obj else "unknown"
    append_event(
        run_id,
        {
            "event": "subagent_start",
            "thread_id": str(thread_id),
            "parent_thread_id": (pending or {}).get("parent_thread_id") or run_id,
            "model": model,
            "tier": tier,
            "agent_type": payload.get("agent_type"),
            "task_name": (pending or {}).get("task_name"),
        },
    )
    if pending:
        append_event(run_id, {"event": "claude_spawn_pending_consumed", "pending_id": pending.get("pending_id"), "thread_id": str(thread_id)})


def _close_subagent(run_id: str, events: list[dict], payload: dict) -> None:
    requested_thread_id = payload.get("agent_id") or payload.get("thread_id")
    open_starts = [event for items in active_spawns(events).values() for event in items]
    if not open_starts:
        return
    if requested_thread_id is not None:
        requested = str(requested_thread_id)
        match = next((event for event in open_starts if str(event.get("thread_id")) == requested), None)
    else:
        match = None
    oldest = match or min(open_starts, key=lambda event: event.get("ts", 0))
    append_event(
        run_id,
        {
            "event": "subagent_stop",
            "thread_id": oldest.get("thread_id"),
            "tier": oldest.get("tier"),
            "model": oldest.get("model"),
            "status": str(payload.get("status")) if payload.get("status") else "completed",
        },
    )


def _oldest_pending_spawn(events: list[dict]) -> dict | None:
    pending: dict[str, dict] = {}
    for event in events:
        if event.get("event") == "claude_spawn_pending":
            pending[str(event.get("pending_id"))] = event
        elif event.get("event") == "claude_spawn_pending_consumed":
            pending.pop(str(event.get("pending_id")), None)
    if not pending:
        return None
    return min(pending.values(), key=lambda event: event.get("ts", 0))


def _latest_snapshot(events: list[dict]) -> dict[str, dict]:
    snapshot: dict[str, dict] = {}
    for event in events:
        if event.get("event") == "sidechain_snapshot" and isinstance(event.get("by_model"), dict):
            snapshot = event["by_model"]
    return snapshot


def _to_token_usage(delta: dict) -> TokenUsage:
    input_total = delta["input"] + delta["cache_read"] + delta["cache_creation"]
    return TokenUsage(
        input_tokens=input_total,
        cached_input_tokens=delta["cache_read"],
        output_tokens=delta["output"],
        reasoning_output_tokens=0,
        total_tokens=input_total + delta["output"],
    )


def _sidechain_usage(transcript_path: Path) -> dict[str, dict]:
    """Usage of subagent (sidechain) turns inlined in the main transcript."""
    return _accumulate_usage(transcript_path, only_sidechain=True)


def _transcript_usage(transcript_path: Path) -> dict[str, dict]:
    """Usage of every assistant turn in a dedicated per-subagent transcript."""
    return _accumulate_usage(transcript_path, only_sidechain=False)


def _accumulate_usage(transcript_path: Path, only_sidechain: bool) -> dict[str, dict]:
    totals: dict[str, dict] = {}
    try:
        with Path(transcript_path).open("r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                event = _loads(line)
                if event is None or event.get("type") != "assistant":
                    continue
                if only_sidechain and not event.get("isSidechain"):
                    continue
                message = event.get("message")
                if not isinstance(message, dict):
                    continue
                usage = message.get("usage")
                model = message.get("model")
                if not isinstance(usage, dict) or not isinstance(model, str):
                    continue
                acc = totals.setdefault(model, {field: 0 for field in _RAW_FIELDS})
                acc["input"] += _int(usage.get("input_tokens"))
                acc["cache_read"] += _int(usage.get("cache_read_input_tokens"))
                acc["cache_creation"] += _int(usage.get("cache_creation_input_tokens"))
                acc["output"] += _int(usage.get("output_tokens"))
    except OSError:
        return {}
    return totals


def _latest_main_model(transcript_path: Path) -> str | None:
    for line in reversed(_tail_lines(transcript_path)):
        event = _loads(line)
        if event is None or event.get("isSidechain") or event.get("type") != "assistant":
            continue
        model = (event.get("message") or {}).get("model")
        if isinstance(model, str) and model:
            return model
    return None


def _tail_lines(path: Path, max_bytes: int = 262_144) -> list[str]:
    try:
        size = Path(path).stat().st_size
        with Path(path).open("rb") as handle:
            handle.seek(max(0, size - max_bytes))
            data = handle.read()
    except OSError:
        return []
    return data.decode("utf-8", errors="replace").splitlines()


def _loads(line: str) -> dict | None:
    try:
        value = json.loads(line)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _int(value: object) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


PROVIDER = ClaudeProvider()
