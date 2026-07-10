from __future__ import annotations

from contextlib import suppress

from conductor.config import ConductorConfig, Ladder
from conductor.errors import StateError
from conductor.identifiers import bounded_identifier, derived_identifier
from conductor.identity import Caller
from conductor.ledger import store_path
from conductor.providers.base import CorrelationLink, Provider
from conductor.schemas import LifecycleEvent
from conductor.schemas import Provider as ProviderName
from conductor.store import Store
from conductor.tool_adapter import ToolRequest, extract_envelope

MODEL_ALIASES = {
    "opus": "claude-opus-4-8",
    "sonnet": "claude-sonnet-5",
    "haiku": "claude-haiku-4-5",
    "fable": "claude-fable-5",
}


class ClaudeProvider(Provider):
    name = "claude"

    def normalize_request(self, payload: dict) -> ToolRequest:
        tool_name = str(payload.get("tool_name") or payload.get("name") or "")
        tool_input = payload.get("tool_input") or payload.get("input") or {}
        if not isinstance(tool_input, dict) or tool_name not in {"Task", "claude.Task"}:
            return ToolRequest(
                kind="other",
                tool_name=tool_name,
                requested_model=None,
                task_name=None,
                envelope=None,
            )
        prompt = "\n".join(
            str(tool_input[key])
            for key in ("description", "prompt")
            if isinstance(tool_input.get(key), str)
        )
        envelope = extract_envelope(prompt)
        requested_model = _resolve_model(tool_input.get("model"))
        subagent_type = tool_input.get("subagent_type")
        task_name = (
            envelope.task_name
            if envelope is not None
            else str(subagent_type)
            if isinstance(subagent_type, str)
            else None
        )
        return ToolRequest(
            kind="spawn",
            tool_name=tool_name,
            requested_model=requested_model,
            task_name=task_name,
            envelope=envelope,
        )

    def resolve_caller(self, payload: dict, ladder: Ladder) -> Caller:
        run_id = _first_string(payload, ("session_id", "root_thread_id", "run_id"))
        agent_id = _first_string(payload, ("agent_id", "thread_id"))
        model = _resolve_model(payload.get("root_model") or payload.get("model"))
        depth = 1 if agent_id is not None and agent_id != run_id else 0

        if run_id is not None and store_path().exists():
            database = Store(
                store_path(), busy_timeout_ms=ladder.policy.busy_timeout_ms
            )
            if depth:
                correlation = _first_string(
                    payload,
                    ("correlation_id", "tool_call_id", "agent_id", "thread_id"),
                )
                if correlation is not None:
                    with suppress(StateError):
                        model = database.reservation(correlation, run_id=run_id).model
            if model is None:
                with suppress(StateError):
                    model = database.run_context(run_id).root_model

        resolved_model = model or ""
        return Caller(
            run_id=run_id,
            thread_id=agent_id or run_id,
            depth=depth,
            tier_index=ladder.tier_index_for_model(resolved_model),
            model=resolved_model,
        )

    def emit_decision(self, decision: str, reason: str) -> dict:
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow" if decision == "approve" else "deny",
                "permissionDecisionReason": reason,
            }
        }

    def handle_lifecycle(self, payload: dict) -> None:
        from conductor.hooks.lifecycle import handle

        handle(payload, provider_name=self.name)

    def normalize_lifecycle_events(
        self,
        payload: dict,
        config: ConductorConfig,
        *,
        reservation_model: str | None = None,
        reservation_estimate_usd: float = 0.0,
    ) -> tuple[LifecycleEvent, ...]:
        from conductor.accounting import normalize_lifecycle_events

        normalized = dict(payload)
        model = _resolve_model(normalized.get("model"))
        if model is not None:
            normalized["model"] = model
        return normalize_lifecycle_events(
            provider=ProviderName.CLAUDE,
            payload=normalized,
            config=config,
            reservation_model=reservation_model,
            reservation_estimate_usd=reservation_estimate_usd,
        )

    def correlation_link(self, payload: dict) -> CorrelationLink | None:
        run_id = _first_string(payload, ("session_id", "root_thread_id", "run_id"))
        source = _first_string(
            payload, ("tool_use_id", "tool_call_id", "correlation_id")
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
        return _first_string(payload, ("session_id", "root_thread_id", "run_id"))


def _resolve_model(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    stripped = value.strip()
    return MODEL_ALIASES.get(stripped, stripped)


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
    for name in ("tool_response", "tool_result", "toolUseResult", "result"):
        value = payload.get(name)
        if isinstance(value, dict):
            candidates.append(value)
    for candidate in candidates:
        value = _first_string(
            candidate, ("agentId", "agent_id", "child_id", "thread_id")
        )
        if value is not None:
            return value
    return None


PROVIDER = ClaudeProvider()
