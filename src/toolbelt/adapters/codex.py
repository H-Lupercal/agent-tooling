from __future__ import annotations

import json
from typing import Any

from toolbelt.adapters.base import JsonInventoryAdapter
from toolbelt.schemas import CapabilitySnapshot, CapabilityStatus, Provider


class CodexAdapter(JsonInventoryAdapter):
    provider = Provider.CODEX
    inventory_arguments = ("mcp", "list", "--json")

    def __init__(self, *, binary: str = "codex"):
        super().__init__(binary=binary)

    def parse_output(
        self,
        output: bytes,
        *,
        max_output_bytes: int = 64 * 1024,
    ) -> CapabilitySnapshot:
        """Parse Codex's current `mcp list --json` array without trusting extras."""

        if len(output) > max_output_bytes:
            return self._unknown("inventory output exceeded the configured bound")
        try:
            raw: Any = json.loads(output.decode("utf-8"))
            if not isinstance(raw, list):
                raise ValueError("Codex MCP inventory root must be an array")
            installed: list[str] = []
            for item in raw:
                if not isinstance(item, dict):
                    raise ValueError("Codex MCP inventory entries must be objects")
                name = item.get("name")
                enabled = item.get("enabled")
                if not isinstance(name, str) or type(enabled) is not bool:
                    raise ValueError("Codex MCP inventory entry is missing name or enabled")
                if enabled:
                    installed.append(name)
            return CapabilitySnapshot(
                provider=Provider.CODEX,
                status=CapabilityStatus.KNOWN,
                native=("codex", "filesystem", "git"),
                installed=tuple(sorted(installed)),
            )
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError):
            return self._unknown("inventory output did not match the supported Codex schema")


__all__ = ["CodexAdapter"]
