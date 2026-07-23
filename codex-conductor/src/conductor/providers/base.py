from __future__ import annotations

from dataclasses import dataclass

from conductor.config import ConductorConfig, Ladder
from conductor.identity import Caller
from conductor.schemas import LifecycleEvent
from conductor.tool_adapter import ToolRequest


@dataclass(frozen=True)
class CorrelationLink:
    run_id: str
    source_correlation: str
    child_alias: str
    source_event_id: str


class Provider:
    """Provider-specific glue between a coding agent's hook payloads and the
    provider-neutral conductor engine (config ladder, decision rules, ledger,
    pricing, status, report).

    Concrete providers translate the raw hook payload of one agent runtime
    (Codex, Claude Code) into the neutral ``ToolRequest``/``Caller`` shapes the
    engine understands, and serialize decisions back into that runtime's
    expected hook-output format.
    """

    name: str = "base"

    def normalize_request(self, payload: dict) -> ToolRequest:
        """Turn a PreToolUse payload into a neutral ToolRequest."""
        raise NotImplementedError

    def resolve_caller(self, payload: dict, ladder: Ladder) -> Caller:
        """Resolve the spawning agent's run id, thread id, depth and tier."""
        raise NotImplementedError

    def emit_decision(self, decision: str, reason: str) -> dict:
        """Serialize an approve/block decision into the runtime's hook output."""
        raise NotImplementedError

    def decorate_spawn_notice(self, response: dict, notice: str) -> dict:
        """Return an approved allow response enriched with an informational
        spawn notice. Default no-op: providers that can surface a cross-client
        message override this. Must not mutate ``response`` or alter the
        permission decision."""
        return response

    def post_approve_events(
        self, request: ToolRequest, caller: Caller, ladder: Ladder
    ) -> list[dict]:
        """Extra ledger events to append after a spawn is approved.

        Codex records subagent starts from its own ``SubagentStart`` hook, so it
        returns nothing here. Claude records a pending spawn here and completes
        it when Claude's ``SubagentStart`` hook supplies the real agent id.
        """
        return []

    def handle_lifecycle(self, payload: dict) -> None:
        """Record subagent start/stop and cost from a lifecycle hook payload."""
        raise NotImplementedError

    def normalize_lifecycle_events(
        self,
        payload: dict,
        config: ConductorConfig,
        *,
        reservation_model: str | None = None,
        reservation_estimate_usd: float = 0.0,
    ) -> tuple[LifecycleEvent, ...]:
        """Normalize provider lifecycle data into immutable v2 events."""
        raise NotImplementedError

    def correlation_link(self, payload: dict) -> CorrelationLink | None:
        """Extract an exact PostToolUse tool-call → child-id mapping."""
        raise NotImplementedError

    def session_run_id(self, payload: dict) -> str | None:
        """Extract the root run id from a SessionStart payload."""
        raise NotImplementedError
