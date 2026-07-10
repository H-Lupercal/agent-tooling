from __future__ import annotations

import sys
from pathlib import Path

import pytest

from toolbelt.adapters.base import (
    InventoryCommand,
    InventoryExecution,
    run_inventory_command,
)
from toolbelt.adapters.claude import ClaudeAdapter
from toolbelt.adapters.codex import CodexAdapter
from toolbelt.capabilities import combine_capabilities
from toolbelt.schemas import CapabilityStatus, Provider

FIXTURES = Path(__file__).parent / "fixtures/providers"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_codex_parses_current_bounded_inventory_fixture():
    snapshot = CodexAdapter().parse_output(_fixture("codex_inventory_v1.json"))

    assert snapshot.provider is Provider.CODEX
    assert snapshot.provider_version is None
    assert snapshot.status is CapabilityStatus.KNOWN
    assert snapshot.native == ("codex", "filesystem", "git")
    assert snapshot.installed == ("mcp-playwright",)
    assert snapshot.managed == ()
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
    unknown_version = adapter.parse_output(b'{"schema_version":99,"provider":"codex","tools":[]}')
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


@pytest.mark.parametrize(
    "arguments",
    [
        {"argv": ()},
        {"argv": ("codex",), "timeout_seconds": 0},
        {"argv": ("codex",), "max_output_bytes": 0},
    ],
)
def test_inventory_command_rejects_invalid_bounds(arguments: dict) -> None:
    with pytest.raises(ValueError):
        InventoryCommand(**arguments)


def test_real_inventory_runner_bounds_missing_timeout_and_output() -> None:
    missing = run_inventory_command(InventoryCommand(("definitely-missing-toolbelt-binary",)))
    timed_out = run_inventory_command(
        InventoryCommand(
            (sys.executable, "-c", "import time; time.sleep(1)"),
            timeout_seconds=0.01,
        )
    )
    bounded = run_inventory_command(
        InventoryCommand(
            (
                sys.executable,
                "-c",
                "import sys; sys.stdout.write('a'*10); sys.stderr.write('b'*10)",
            ),
            max_output_bytes=12,
        )
    )

    assert missing.returncode == 127
    assert timed_out.returncode == 124
    assert bounded.truncated is True
    assert len(bounded.stdout) + len(bounded.stderr) == 12


@pytest.mark.parametrize(
    "execution",
    [
        InventoryExecution(0, b"", b"", True),
        InventoryExecution(9, b"", b"failure", False),
    ],
)
def test_adapter_inventory_failures_are_unknown(execution: InventoryExecution) -> None:
    snapshot = CodexAdapter().inventory(runner=lambda _command: execution)

    assert snapshot.status is CapabilityStatus.UNKNOWN
    assert snapshot.errors


@pytest.mark.parametrize(
    "payload",
    [
        b"[]",
        b'{"schema_version":1}',
        b'{"schema_version":1,"provider":"wrong","provider_version":"1","native":[],"tools":[]}',
        b'{"schema_version":1,"provider":"claude","provider_version":1,"native":[],"tools":[]}',
        b'{"schema_version":1,"provider":"claude","provider_version":"1","native":[],"tools":{}}',
        b'{"schema_version":1,"provider":"claude","provider_version":"1",'
        b'"native":[],"tools":[{"id":1,"managed":"yes"}]}',
    ],
)
def test_versioned_adapter_rejects_wrong_shapes(payload: bytes) -> None:
    snapshot = ClaudeAdapter().parse_output(payload)

    assert snapshot.status is CapabilityStatus.UNKNOWN


def test_combined_snapshot_preserves_unknown_instead_of_assuming_absence():
    known = ClaudeAdapter().parse_output(_fixture("claude_inventory_v1.json"))
    unknown = CodexAdapter().parse_output(b"not-json")

    combined = combine_capabilities((known, unknown))

    assert combined.provider is Provider.COMBINED
    assert combined.status is CapabilityStatus.UNKNOWN
    assert combined.native == ("browser",)
    assert combined.installed == ("plugin-superpowers",)
    assert combined.errors
