from __future__ import annotations

from toolbelt.adapters.base import JsonInventoryAdapter
from toolbelt.schemas import Provider


class CodexAdapter(JsonInventoryAdapter):
    provider = Provider.CODEX
    inventory_arguments = ("mcp", "list", "--json")

    def __init__(self, *, binary: str = "codex"):
        super().__init__(binary=binary)


__all__ = ["CodexAdapter"]
