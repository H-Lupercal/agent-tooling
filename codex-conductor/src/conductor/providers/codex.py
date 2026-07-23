from __future__ import annotations

import os
from copy import deepcopy
from pathlib import Path

from conductor.config import Ladder
from conductor.identifiers import bounded_identifier, derived_identifier
from conductor.identity import Caller, resolve_caller
from conductor.providers.base import CorrelationLink, Provider
from conductor.schemas import LifecycleEvent
from conductor.schemas import Provider as ProviderName
from conductor.tool_adapter import ToolRequest, normalize_tool_request


def _sessions_root() -> Path:
    return Path(
        os.environ.get(
            "CODEX_CONDUCTOR_SESSIONS_ROOT", Path.home() / ".codex" / "sessions"
        )
    )


class CodexProvider(Provider):
    name = "codex"

    def normalize_request(self, payload: dict) -> ToolRequest:
        return normalize_tool_request(payload, {})

    def resolve_caller(self, payload: dict, ladder: Ladder) -> Caller:
        normalized = dict(payload)
        session_id = _first_string(payload, ("session_id",))
        if session_id is not None:
            normalized.setdefault("root_thread_id", session_id)
            if not (
                payload.get("transcript_path") or payload.get("agent_transcript_path")
            ):
                normalized.setdefault(
                    "thread_id",
                    _first_string(payload, ("agent_id",)) or session_id,
                )
        return resolve_caller(normalized, ladder, _sessions_root())

    def emit_decision(self, decision: str, reason: str) -> dict:
        output = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if decision == "approve" else "deny",
            }
        }
        if decision != "approve":
            output["hookSpecificOutput"]["permissionDecisionReason"] = reason
        return output

    def decorate_updated_input(
        self,
        response: dict,
        tool_input: dict,
        *,
        reasoning_effort: str,
    ) -> dict:
        decorated = deepcopy(response)
        decorated["hookSpecificOutput"]["updatedInput"] = {
            **tool_input,
            "reasoning_effort": reasoning_effort,
        }
        return decorated

    def handle_lifecycle(self, payload: dict) -> None:
        # Codex records both SubagentStart and SubagentStop natively.
        from conductor.hooks.lifecycle import handle

        handle(payload, provider_name=self.name)

    def normalize_lifecycle_events(
        self,
        payload: dict,
        config,
        *,
        reservation_model: str | None = None,
        reservation_estimate_usd: float = 0.0,
    ) -> tuple[LifecycleEvent, ...]:
        from conductor.accounting import normalize_lifecycle_events

        return normalize_lifecycle_events(
            provider=ProviderName.CODEX,
            payload=payload,
            config=config,
            reservation_model=reservation_model,
            reservation_estimate_usd=reservation_estimate_usd,
        )

    def correlation_link(self, payload: dict) -> CorrelationLink | None:
        run_id = _first_string(
            payload, ("session_id", "root_thread_id", "run_id", "thread_id")
        )
        source = _first_string(
            payload,
            ("tool_use_id", "tool_call_id", "correlation_id", "event_id"),
        )
        child = _child_id(payload)
        if run_id is None or source is None or child is None:
            return None
        raw_event = _first_string(payload, ("event_id",))
        event = (
            bounded_identifier(raw_event, prefix="event")
            if raw_event is not None
            else derived_identifier("post", source)
        )
        return CorrelationLink(run_id, source, child, event)

    def session_run_id(self, payload: dict) -> str | None:
        return _first_string(
            payload,
            ("session_id", "root_thread_id", "thread_id", "run_id"),
        )


PROVIDER = CodexProvider()


def _first_string(payload: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        value = payload.get(name)
        if isinstance(value, str) and value:
            return value
    return None


def _child_id(payload: dict) -> str | None:
    direct = _first_string(payload, ("child_id", "childId"))
    if direct is not None:
        return direct
    candidates = []
    for name in ("tool_response", "tool_result", "result", "output"):
        value = payload.get(name)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        value = _first_string(
            candidate, ("child_id", "agent_id", "thread_id", "agentId")
        )
        if value is not None:
            return value
    return None
