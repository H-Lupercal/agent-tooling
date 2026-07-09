from __future__ import annotations

import os
from pathlib import Path

from conductor.config import Ladder
from conductor.identity import Caller, resolve_caller
from conductor.providers.base import Provider
from conductor.tool_adapter import ToolRequest, normalize_tool_request


def _sessions_root() -> Path:
    return Path(os.environ.get("CODEX_CONDUCTOR_SESSIONS_ROOT", Path.home() / ".codex" / "sessions"))


class CodexProvider(Provider):
    name = "codex"

    def normalize_request(self, payload: dict) -> ToolRequest:
        return normalize_tool_request(payload, {})

    def resolve_caller(self, payload: dict, ladder: Ladder) -> Caller:
        return resolve_caller(payload, ladder, _sessions_root())

    def emit_decision(self, decision: str, reason: str) -> dict:
        return {"decision": decision, "reason": reason}

    def handle_lifecycle(self, payload: dict) -> None:
        # Codex records both SubagentStart and SubagentStop natively.
        from conductor.hooks.lifecycle import handle

        handle(payload)

    def session_run_id(self, payload: dict) -> str | None:
        value = payload.get("root_thread_id") or payload.get("thread_id") or payload.get("run_id")
        return str(value) if value else None


PROVIDER = CodexProvider()
