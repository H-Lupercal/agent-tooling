from __future__ import annotations

import argparse
from typing import Any

from conductor.config import load_config
from conductor.errors import ConductorError, StateError
from conductor.hooks.common import log_error, read_payload, write_json
from conductor.ledger import store_path
from conductor.schemas import Reservation
from conductor.store import Store
from conductor.tool_adapter import normalize_governed_payload


def handle(
    payload: dict[str, Any],
    *,
    provider_name: str = "codex",
    store: Store | None = None,
) -> tuple[Reservation, ...]:
    """Record one provider lifecycle hook with exact correlation and costing."""

    from conductor.providers import get_provider

    provider = get_provider(provider_name)
    event_name = str(payload.get("hook_event_name") or payload.get("event") or "")
    if event_name in {"PostToolUse", "post_tool_use"}:
        raw_tool_name = payload.get("tool_name") or payload.get("name")
        if isinstance(raw_tool_name, str) and raw_tool_name:
            operation = normalize_governed_payload(payload).operation
            if operation is None or not operation.is_new_work:
                return ()
    config = load_config()
    database = store or Store(
        store_path(), busy_timeout_ms=config.policy.busy_timeout_ms
    )
    if event_name in {"PostToolUse", "post_tool_use"}:
        link = provider.correlation_link(payload)
        if link is None:
            raise StateError(
                "PostToolUse did not expose an exact tool-call to child-id mapping"
            )
        linked = database.link_correlation(
            link.run_id,
            source_correlation=link.source_correlation,
            alias=link.child_alias,
            source_event_id=link.source_event_id,
        )
        database.heartbeat_run(
            link.run_id,
            lease_seconds=max(300, config.policy.reservation_ttl_seconds * 2),
        )
        return (linked,)
    run_id = _first_string(payload, ("root_thread_id", "run_id", "session_id"))
    if run_id is None:
        raise StateError("lifecycle payload has no run id")
    correlation = _first_string(
        payload,
        (
            "correlation_id",
            "tool_call_id",
            "lifecycle_id",
            "task_id",
            "thread_id",
            "agent_id",
        ),
    )
    reservation_model: str | None = None
    reservation_estimate = 0.0
    reservation: Reservation | None = None
    if correlation is not None:
        try:
            reservation = database.reservation(correlation, run_id=run_id)
        except StateError:
            reservation = None
        if reservation is not None:
            reservation_model = reservation.model
            reservation_estimate = reservation.estimated_usd

    normalized_payload = dict(payload)
    if reservation is not None and reservation.correlation_id is not None:
        normalized_payload["correlation_id"] = reservation.correlation_id
    events = provider.normalize_lifecycle_events(
        normalized_payload,
        config,
        reservation_model=reservation_model,
        reservation_estimate_usd=reservation_estimate,
    )
    recorded = tuple(database.record_lifecycle(event) for event in events)
    database.heartbeat_run(
        run_id,
        lease_seconds=max(300, config.policy.reservation_ttl_seconds * 2),
    )
    return recorded


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        handle(read_payload(), provider_name=args.provider)
        write_json({})
    except (ConductorError, OSError, ValueError) as exc:
        log_error("lifecycle", exc)
        write_json({"conductor": {"recorded": False, "error": type(exc).__name__}})
    except BaseException as exc:
        log_error("lifecycle", exc)
        write_json({"conductor": {"recorded": False, "error": "InternalError"}})
    return 0


def _first_string(payload: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
