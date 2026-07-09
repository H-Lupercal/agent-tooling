from __future__ import annotations

from pathlib import Path

import pytest

from toolbelt.adapters.base import InventoryCommand, InventoryExecution
from toolbelt.adapters.claude import ClaudeAdapter
from toolbelt.adapters.codex import CodexAdapter
from toolbelt.capabilities import combine_capabilities
from toolbelt.schemas import CapabilityStatus, Provider


FIXTURES = Path(__file__).parent / "fixtures/providers"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_codex_parses_versioned_inventory_fixture():
    snapshot = CodexAdapter().parse_output(_fixture("codex_inventory_v1.json"))

    assert snapshot.provider is Provider.CODEX
    assert snapshot.provider_version == "0.42.0"
    assert snapshot.status is CapabilityStatus.KNOWN
    assert snapshot.native == ("filesystem", "git")
    assert snapshot.installed == ("mcp-playwright", "ruff")
    assert snapshot.managed == ("mcp-playwright",)
    assert snapshot.errors == ()


def test_claude_parses_versioned_inventory_fixture():
    snapshot = ClaudeAdapter().parse_output(_fixture("claude_inventory_v1.json"))

    assert snapshot.provider is Provider.CLAUDE
    assert snapshot.provider_version == "1.7.3"
    assert snapshot.status is CapabilityStatus.KNOWN
    assert snapshot.native == ("browser",)
    assert snapshot.installed == ("plugin-superpowers",)
    assert snapshot.managed == ("plugin-superpowers",)


def test_malformed_unknown_and_oversized_inventory_fail_closed():
    adapter = CodexAdapter()

    malformed = adapter.parse_output(b"not-json")
    unknown_version = adapter.parse_output(
        b'{"schema_version":99,"provider":"codex","tools":[]}'
    )
    oversized = adapter.parse_output(b"x" * 65, max_output_bytes=64)

    for snapshot in (malformed, unknown_version, oversized):
        assert snapshot.status is CapabilityStatus.UNKNOWN
        assert snapshot.native == ()
        assert snapshot.installed == ()
        assert snapshot.managed == ()
        assert snapshot.errors


def test_adapter_uses_bounded_read_only_inventory_command():
    observed: list[InventoryCommand] = []

    def runner(command: InventoryCommand) -> InventoryExecution:
        observed.append(command)
        return InventoryExecution(
            returncode=0,
            stdout=_fixture("codex_inventory_v1.json"),
            stderr=b"",
            truncated=False,
        )

    snapshot = CodexAdapter(binary="codex-test").inventory(runner=runner)

    assert snapshot.status is CapabilityStatus.KNOWN
    assert observed == [
        InventoryCommand(
            argv=("codex-test", "mcp", "list", "--json"),
            timeout_seconds=5.0,
            max_output_bytes=64 * 1024,
        )
    ]


def test_inventory_command_rejects_shell_wrappers():
    with pytest.raises(ValueError, match="shell"):
        InventoryCommand(argv=("sh", "-c", "codex mcp list --json"))


def test_combined_snapshot_preserves_unknown_instead_of_assuming_absence():
    known = ClaudeAdapter().parse_output(_fixture("claude_inventory_v1.json"))
    unknown = CodexAdapter().parse_output(b"not-json")

    combined = combine_capabilities((known, unknown))

    assert combined.provider is Provider.COMBINED
    assert combined.status is CapabilityStatus.UNKNOWN
    assert combined.native == ("browser",)
    assert combined.installed == ("plugin-superpowers",)
    assert combined.errors
