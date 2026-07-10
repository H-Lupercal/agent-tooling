from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from conductor.config import ConductorConfig
from conductor.identifiers import derived_identifier
from conductor.pricing import raw_usage_cost_usd, tier_pricing_available
from conductor.rollout import claude_transcript_usage, latest_usage
from conductor.schemas import (
    LifecycleEvent,
    LifecycleKind,
    Provider,
    RawUsage,
)

PARSER_VERSION = "conductor-usage-v1"


def normalize_lifecycle_events(
    *,
    provider: Provider,
    payload: dict[str, Any],
    config: ConductorConfig,
    reservation_model: str | None = None,
    reservation_estimate_usd: float = 0.0,
) -> tuple[LifecycleEvent, ...]:
    """Normalize a provider hook into stable, exactly-once lifecycle events."""

    run_id = _required_identifier(
        payload, ("root_thread_id", "run_id", "session_id"), "run id"
    )
    correlation_id = _required_identifier(
        payload,
        (
            "correlation_id",
            "tool_call_id",
            "lifecycle_id",
            "task_id",
            "thread_id",
            "agent_id",
        ),
        "lifecycle correlation id",
    )
    event_name = str(payload.get("hook_event_name") or payload.get("event") or "")
    occurred_at = _timestamp(payload.get("occurred_at") or payload.get("timestamp"))
    status = _optional_string(payload.get("status"))
    model = _optional_string(payload.get("model")) or reservation_model

    if event_name in {"SubagentStart", "subagent_start"}:
        return (
            LifecycleEvent(
                event_id=derived_identifier("start", correlation_id),
                provider=provider,
                run_id=run_id,
                correlation_id=correlation_id,
                kind=LifecycleKind.START,
                occurred_at=occurred_at,
                status=status or "running",
            ),
        )

    if event_name not in {
        "SubagentStop",
        "subagent_stop",
        "SubagentFailure",
        "subagent_failure",
        "SubagentCancel",
        "subagent_cancel",
    }:
        raise ValueError(f"unsupported lifecycle event: {event_name!r}")

    terminal_kind = _terminal_kind(event_name, status)
    terminal = LifecycleEvent(
        event_id=derived_identifier("terminal", correlation_id),
        provider=provider,
        run_id=run_id,
        correlation_id=correlation_id,
        kind=terminal_kind,
        occurred_at=occurred_at,
        status=status or terminal_kind.value,
    )
    usage = _raw_usage(provider, payload, model, correlation_id, occurred_at)
    effective_model = usage.model if usage is not None else model
    tier = config.tier_for_model(effective_model or "")
    if usage is not None and tier is not None and tier_pricing_available(tier):
        cost = raw_usage_cost_usd(usage, tier)
        estimated = False
    else:
        cost = float(reservation_estimate_usd)
        estimated = True
    cost_event = LifecycleEvent(
        event_id=derived_identifier("cost", correlation_id),
        provider=provider,
        run_id=run_id,
        correlation_id=correlation_id,
        kind=LifecycleKind.COST,
        occurred_at=occurred_at,
        status="costed",
        usage=usage,
        cost_usd=cost,
        estimated=estimated,
    )
    return terminal, cost_event


def _raw_usage(
    provider: Provider,
    payload: dict[str, Any],
    model: str | None,
    correlation_id: str,
    occurred_at: datetime,
) -> RawUsage | None:
    direct = payload.get("usage")
    if isinstance(direct, dict):
        values = _usage_fields(provider, direct)
    else:
        transcript = payload.get("agent_transcript_path")
        if provider is Provider.CLAUDE:
            parsed_claude = (
                claude_transcript_usage(Path(transcript))
                if isinstance(transcript, str)
                else None
            )
            if parsed_claude is None:
                return None
            parsed_model, raw = parsed_claude
            model = model or parsed_model
            values = _usage_fields(provider, raw)
        else:
            transcript = transcript or payload.get("transcript_path")
            parsed = (
                latest_usage(Path(transcript)) if isinstance(transcript, str) else None
            )
            if parsed is None:
                return None
            values = {
                "input": parsed.input_tokens,
                "cache_read": parsed.cached_input_tokens,
                "cache_write": 0,
                "output": parsed.output_tokens,
                "reasoning": parsed.reasoning_output_tokens,
            }
    if model is None:
        return None
    return RawUsage(
        source_event_id=derived_identifier("usage", correlation_id),
        provider=provider,
        parser_version=PARSER_VERSION,
        model=model,
        input_tokens=values["input"],
        cache_read_tokens=values["cache_read"],
        cache_write_tokens=values["cache_write"],
        output_tokens=values["output"],
        reasoning_tokens=values["reasoning"],
        measured=True,
        occurred_at=occurred_at,
    )


def _usage_fields(provider: Provider, raw: dict[str, Any]) -> dict[str, int]:
    cache_read = _nonnegative_int(
        raw.get(
            "cache_read_tokens",
            raw.get("cached_input_tokens", raw.get("cache_read_input_tokens", 0)),
        )
    )
    cache_write = _nonnegative_int(
        raw.get("cache_write_tokens", raw.get("cache_creation_input_tokens", 0))
    )
    base_input = _nonnegative_int(raw.get("input_tokens", 0))
    # Claude reports uncached input separately; Codex reports total input.
    total_input = (
        base_input + cache_read + cache_write
        if provider is Provider.CLAUDE
        else max(base_input, cache_read + cache_write)
    )
    return {
        "input": total_input,
        "cache_read": cache_read,
        "cache_write": cache_write,
        "output": _nonnegative_int(raw.get("output_tokens", 0)),
        "reasoning": _nonnegative_int(
            raw.get("reasoning_tokens", raw.get("reasoning_output_tokens", 0))
        ),
    }


def _terminal_kind(event_name: str, status: str | None) -> LifecycleKind:
    lowered = (status or "").lower()
    if "fail" in event_name.lower() or lowered in {"failed", "error"}:
        return LifecycleKind.FAIL
    if "cancel" in event_name.lower() or lowered in {"cancelled", "canceled"}:
        return LifecycleKind.CANCEL
    return LifecycleKind.STOP


def _required_identifier(
    payload: dict[str, Any], names: tuple[str, ...], label: str
) -> str:
    value = next(
        (
            item
            for name in names
            if isinstance((item := payload.get(name)), str) and item
        ),
        None,
    )
    if value is None:
        raise ValueError(f"{label} is missing")
    # Let the strict LifecycleEvent schema enforce the exact identifier grammar.
    return value


def _timestamp(value: object) -> datetime:
    if value is None:
        return datetime.now(UTC)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return datetime.fromtimestamp(float(value), UTC)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError("lifecycle timestamp must be timezone-aware")
        return parsed
    raise ValueError("invalid lifecycle timestamp")


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _nonnegative_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("token counts must be nonnegative integers")
    if value < 0:
        raise ValueError("token counts must be nonnegative integers")
    return value
