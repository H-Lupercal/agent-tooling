from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any, Protocol

from pydantic import ValidationError as PydanticValidationError

from toolbelt.schemas import CapabilitySnapshot, CapabilityStatus, Provider


@dataclass(frozen=True, slots=True)
class InventoryCommand:
    argv: tuple[str, ...]
    timeout_seconds: float = 5.0
    max_output_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        if not self.argv or any(not value or "\0" in value for value in self.argv):
            raise ValueError("inventory argv must contain nonempty direct arguments")
        if self.timeout_seconds <= 0:
            raise ValueError("inventory timeout must be positive")
        if self.max_output_bytes <= 0:
            raise ValueError("inventory output bound must be positive")
        executable = self.argv[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if executable in {
            "bash",
            "cmd",
            "cmd.exe",
            "powershell",
            "powershell.exe",
            "pwsh",
            "pwsh.exe",
            "sh",
            "zsh",
        }:
            raise ValueError("inventory commands must not use a shell wrapper")


@dataclass(frozen=True, slots=True)
class InventoryExecution:
    returncode: int
    stdout: bytes
    stderr: bytes
    truncated: bool


class InventoryRunner(Protocol):
    def __call__(self, command: InventoryCommand) -> InventoryExecution: ...


def run_inventory_command(command: InventoryCommand) -> InventoryExecution:
    try:
        result = subprocess.run(
            list(command.argv),
            capture_output=True,
            timeout=command.timeout_seconds,
            check=False,
            shell=False,
        )
    except FileNotFoundError:
        return InventoryExecution(127, b"", b"inventory binary not found", False)
    except subprocess.TimeoutExpired:
        return InventoryExecution(124, b"", b"inventory command timed out", False)
    combined_size = len(result.stdout) + len(result.stderr)
    maximum = command.max_output_bytes
    stdout = result.stdout[:maximum]
    stderr = result.stderr[: max(0, maximum - len(stdout))]
    return InventoryExecution(
        result.returncode,
        stdout,
        stderr,
        combined_size > maximum,
    )


class JsonInventoryAdapter:
    provider: Provider
    inventory_arguments: tuple[str, ...]

    def __init__(self, *, binary: str):
        self._binary = binary

    @property
    def command(self) -> InventoryCommand:
        return InventoryCommand((self._binary, *self.inventory_arguments))

    def inventory(
        self,
        *,
        runner: InventoryRunner = run_inventory_command,
    ) -> CapabilitySnapshot:
        execution = runner(self.command)
        if execution.truncated:
            return self._unknown("inventory output exceeded the configured bound")
        if execution.returncode != 0:
            return self._unknown(f"inventory command failed with exit code {execution.returncode}")
        return self.parse_output(
            execution.stdout,
            max_output_bytes=self.command.max_output_bytes,
        )

    def parse_output(
        self,
        output: bytes,
        *,
        max_output_bytes: int = 64 * 1024,
    ) -> CapabilitySnapshot:
        if len(output) > max_output_bytes:
            return self._unknown("inventory output exceeded the configured bound")
        try:
            raw: Any = json.loads(output.decode("utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("inventory root must be an object")
            expected_keys = {
                "native",
                "provider",
                "provider_version",
                "schema_version",
                "tools",
            }
            if set(raw) != expected_keys:
                raise ValueError("inventory fields do not match schema v1")
            if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
                raise ValueError("unsupported inventory schema version")
            if raw["provider"] != self.provider.value:
                raise ValueError("inventory provider does not match adapter")
            provider_version = raw["provider_version"]
            native = raw["native"]
            tools = raw["tools"]
            if not isinstance(provider_version, str) or not isinstance(native, list):
                raise ValueError("inventory metadata has invalid types")
            if not isinstance(tools, list):
                raise ValueError("inventory tools must be an array")
            installed: list[str] = []
            managed: list[str] = []
            for tool in tools:
                if not isinstance(tool, dict) or set(tool) != {"id", "managed"}:
                    raise ValueError("inventory tool has invalid fields")
                if not isinstance(tool["id"], str) or type(tool["managed"]) is not bool:
                    raise ValueError("inventory tool has invalid types")
                installed.append(tool["id"])
                if tool["managed"]:
                    managed.append(tool["id"])
            return CapabilitySnapshot(
                schema_version=2,
                provider=self.provider,
                provider_version=provider_version,
                status=CapabilityStatus.KNOWN,
                native=tuple(sorted(native)),
                installed=tuple(sorted(installed)),
                managed=tuple(sorted(managed)),
                errors=(),
            )
        except (
            json.JSONDecodeError,
            UnicodeDecodeError,
            KeyError,
            PydanticValidationError,
            TypeError,
            ValueError,
        ):
            return self._unknown("inventory output did not match the supported schema")

    def _unknown(self, message: str) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            schema_version=2,
            provider=self.provider,
            status=CapabilityStatus.UNKNOWN,
            native=(),
            installed=(),
            managed=(),
            errors=(message,),
        )


__all__ = [
    "InventoryCommand",
    "InventoryExecution",
    "InventoryRunner",
    "JsonInventoryAdapter",
    "run_inventory_command",
]
