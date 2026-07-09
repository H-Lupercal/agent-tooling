from __future__ import annotations

from conductor.providers.base import Provider

PROVIDERS = ("codex", "claude")


def get_provider(name: str | None) -> Provider:
    key = (name or "codex").lower()
    if key == "codex":
        from conductor.providers import codex

        return codex.PROVIDER
    if key == "claude":
        from conductor.providers import claude

        return claude.PROVIDER
    raise ValueError(f"unknown provider: {name!r}; expected one of {PROVIDERS}")
