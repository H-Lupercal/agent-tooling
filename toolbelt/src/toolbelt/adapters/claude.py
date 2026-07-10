from __future__ import annotations

from toolbelt.adapters.base import JsonInventoryAdapter
from toolbelt.schemas import Provider


class ClaudeAdapter(JsonInventoryAdapter):
    provider = Provider.CLAUDE
    inventory_arguments = ("mcp", "list", "--json")

    def __init__(self, *, binary: str = "claude"):
        super().__init__(binary=binary)


__all__ = ["ClaudeAdapter"]
