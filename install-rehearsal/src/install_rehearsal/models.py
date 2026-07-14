"""Versioned, deterministic receipt schema."""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import Literal, cast

FileKind = Literal["file", "directory", "symlink", "other"]
ChangeKind = Literal["created", "modified", "deleted", "type_changed"]
TerminationReason = Literal["exited", "timeout", "launch_error"]

_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")


def validate_run_id(run_id: str) -> None:
    if not _RUN_ID.fullmatch(run_id):
        raise ValueError("run ID must be 1-128 safe identifier characters")


def _validate_hash(value: str | None, field_name: str) -> None:
    if value is not None and not _SHA256.fullmatch(value):
        raise ValueError(f"{field_name} must be a lowercase SHA-256 digest")


def _validate_relative_path(path: str) -> None:
    parsed = PurePosixPath(path)
    if (
        not path
        or "\\" in path
        or parsed.is_absolute()
        or path in {".", ".."}
        or ".." in parsed.parts
    ):
        raise ValueError("file delta path must be a relative POSIX path")


@dataclass(frozen=True)
class FileState:
    kind: FileKind
    size: int
    sha256: str | None
    mode: int | None
    symlink_target: str | None

    def __post_init__(self) -> None:
        if self.kind not in {"file", "directory", "symlink", "other"}:
            raise ValueError("unknown file kind")
        if self.size < 0:
            raise ValueError("file size cannot be negative")
        _validate_hash(self.sha256, "file state hash")


@dataclass(frozen=True)
class FileDelta:
    path: str
    change: ChangeKind
    before: FileState | None
    after: FileState | None

    def __post_init__(self) -> None:
        _validate_relative_path(self.path)
        if self.change not in {"created", "modified", "deleted", "type_changed"}:
            raise ValueError("unknown change kind")


@dataclass(frozen=True)
class RunResult:
    exit_code: int | None
    termination_reason: TerminationReason
    duration_seconds: float
    stdout_sha256: str
    stderr_sha256: str
    stdout_excerpt: str
    stderr_excerpt: str
    stdout_truncated: bool
    stderr_truncated: bool

    def __post_init__(self) -> None:
        if self.termination_reason not in {"exited", "timeout", "launch_error"}:
            raise ValueError("unknown termination reason")
        if not math.isfinite(self.duration_seconds) or self.duration_seconds < 0:
            raise ValueError("duration must be finite and non-negative")
        _validate_hash(self.stdout_sha256, "stdout hash")
        _validate_hash(self.stderr_sha256, "stderr hash")


@dataclass(frozen=True)
class Coverage:
    profile_root: str
    covered_paths: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True)
class Receipt:
    schema_version: Literal[1]
    run_id: str
    trust_label: Literal["REHEARSAL_NOT_SANDBOXED"]
    started_at: str
    platform: str
    tool_version: str
    argv: tuple[str, ...]
    executable_path: str | None
    executable_sha256: str | None
    inherited_environment_keys: tuple[str, ...]
    run: RunResult
    coverage: Coverage
    filesystem_delta: tuple[FileDelta, ...]
    warnings: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported receipt schema version")
        if self.trust_label != "REHEARSAL_NOT_SANDBOXED":
            raise ValueError("receipt trust label must be REHEARSAL_NOT_SANDBOXED")
        validate_run_id(self.run_id)
        _validate_hash(self.executable_sha256, "executable hash")

    @classmethod
    def example(cls, run_id: str) -> Receipt:
        """Return deterministic fixture data for store and schema tests."""
        empty_hash = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        return cls(
            schema_version=1,
            run_id=run_id,
            trust_label="REHEARSAL_NOT_SANDBOXED",
            started_at="2026-07-12T00:00:00Z",
            platform="linux",
            tool_version="0.1.0",
            argv=("example-installer",),
            executable_path=None,
            executable_sha256=None,
            inherited_environment_keys=("PATH",),
            run=RunResult(
                exit_code=0,
                termination_reason="exited",
                duration_seconds=0.0,
                stdout_sha256=empty_hash,
                stderr_sha256=empty_hash,
                stdout_excerpt="",
                stderr_excerpt="",
                stdout_truncated=False,
                stderr_truncated=False,
            ),
            coverage=Coverage(
                profile_root="<DISPOSABLE_PROFILE>",
                covered_paths=("<DISPOSABLE_PROFILE>",),
                limitations=("not a security sandbox",),
            ),
            filesystem_delta=(),
            warnings=(),
        )


def receipt_to_dict(receipt: Receipt) -> dict[str, object]:
    return cast(dict[str, object], asdict(receipt))


def receipt_to_json(receipt: Receipt) -> str:
    return json.dumps(receipt_to_dict(receipt), sort_keys=True, separators=(",", ":")) + "\n"


def _object(value: object, field: str, keys: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    mapping = cast(Mapping[object, object], value)
    if not all(isinstance(key, str) for key in mapping):
        raise ValueError(f"{field} keys must be strings")
    typed_mapping = cast(Mapping[str, object], value)
    actual_keys = set(typed_mapping)
    if actual_keys != keys:
        raise ValueError(f"{field} has missing or unexpected fields")
    return typed_mapping


def _string(value: object, field: str) -> str:
    if type(value) is not str:
        raise ValueError(f"{field} must be a string")
    return value


def _optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None
    return _string(value, field)


def _integer(value: object, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"{field} must be an integer")
    return value


def _optional_integer(value: object, field: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field)


def _number(value: object, field: str) -> float:
    if type(value) not in {int, float}:
        raise ValueError(f"{field} must be a number")
    result = float(cast(int | float, value))
    if not math.isfinite(result):
        raise ValueError(f"{field} must be finite")
    return result


def _boolean(value: object, field: str) -> bool:
    if type(value) is not bool:
        raise ValueError(f"{field} must be a boolean")
    return value


def _strings(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field} must be an array")
    items = cast(list[object] | tuple[object, ...], value)
    return tuple(_string(item, f"{field} item") for item in items)


_FILE_STATE_KEYS = {"kind", "size", "sha256", "mode", "symlink_target"}
_DELTA_KEYS = {"path", "change", "before", "after"}
_RUN_KEYS = {
    "exit_code",
    "termination_reason",
    "duration_seconds",
    "stdout_sha256",
    "stderr_sha256",
    "stdout_excerpt",
    "stderr_excerpt",
    "stdout_truncated",
    "stderr_truncated",
}
_COVERAGE_KEYS = {"profile_root", "covered_paths", "limitations"}
_RECEIPT_KEYS = {
    "schema_version",
    "run_id",
    "trust_label",
    "started_at",
    "platform",
    "tool_version",
    "argv",
    "executable_path",
    "executable_sha256",
    "inherited_environment_keys",
    "run",
    "coverage",
    "filesystem_delta",
    "warnings",
}


def _file_state(value: object, field: str) -> FileState | None:
    if value is None:
        return None
    item = _object(value, field, _FILE_STATE_KEYS)
    return FileState(
        kind=cast(FileKind, _string(item["kind"], f"{field}.kind")),
        size=_integer(item["size"], f"{field}.size"),
        sha256=_optional_string(item["sha256"], f"{field}.sha256"),
        mode=_optional_integer(item["mode"], f"{field}.mode"),
        symlink_target=_optional_string(item["symlink_target"], f"{field}.symlink_target"),
    )


def receipt_from_dict(value: object) -> Receipt:
    receipt_value = _object(value, "receipt", _RECEIPT_KEYS)
    run_value = _object(receipt_value["run"], "run", _RUN_KEYS)
    coverage_value = _object(receipt_value["coverage"], "coverage", _COVERAGE_KEYS)
    delta_value = receipt_value["filesystem_delta"]
    if not isinstance(delta_value, (list, tuple)):
        raise ValueError("filesystem_delta must be an array")
    delta_items = cast(list[object] | tuple[object, ...], delta_value)
    delta_values = [
        _object(item, f"filesystem_delta[{index}]", _DELTA_KEYS)
        for index, item in enumerate(delta_items)
    ]
    return Receipt(
        schema_version=cast(
            Literal[1], _integer(receipt_value["schema_version"], "schema_version")
        ),
        run_id=_string(receipt_value["run_id"], "run_id"),
        trust_label=cast(
            Literal["REHEARSAL_NOT_SANDBOXED"],
            _string(receipt_value["trust_label"], "trust_label"),
        ),
        started_at=_string(receipt_value["started_at"], "started_at"),
        platform=_string(receipt_value["platform"], "platform"),
        tool_version=_string(receipt_value["tool_version"], "tool_version"),
        argv=_strings(receipt_value["argv"], "argv"),
        executable_path=_optional_string(receipt_value["executable_path"], "executable_path"),
        executable_sha256=_optional_string(receipt_value["executable_sha256"], "executable_sha256"),
        inherited_environment_keys=_strings(
            receipt_value["inherited_environment_keys"], "inherited_environment_keys"
        ),
        run=RunResult(
            exit_code=_optional_integer(run_value["exit_code"], "run.exit_code"),
            termination_reason=cast(
                TerminationReason,
                _string(run_value["termination_reason"], "run.termination_reason"),
            ),
            duration_seconds=_number(run_value["duration_seconds"], "run.duration_seconds"),
            stdout_sha256=_string(run_value["stdout_sha256"], "run.stdout_sha256"),
            stderr_sha256=_string(run_value["stderr_sha256"], "run.stderr_sha256"),
            stdout_excerpt=_string(run_value["stdout_excerpt"], "run.stdout_excerpt"),
            stderr_excerpt=_string(run_value["stderr_excerpt"], "run.stderr_excerpt"),
            stdout_truncated=_boolean(run_value["stdout_truncated"], "run.stdout_truncated"),
            stderr_truncated=_boolean(run_value["stderr_truncated"], "run.stderr_truncated"),
        ),
        coverage=Coverage(
            profile_root=_string(coverage_value["profile_root"], "coverage.profile_root"),
            covered_paths=_strings(coverage_value["covered_paths"], "coverage.covered_paths"),
            limitations=_strings(coverage_value["limitations"], "coverage.limitations"),
        ),
        filesystem_delta=tuple(
            FileDelta(
                path=_string(item["path"], f"filesystem_delta[{index}].path"),
                change=cast(
                    ChangeKind,
                    _string(item["change"], f"filesystem_delta[{index}].change"),
                ),
                before=_file_state(item["before"], f"filesystem_delta[{index}].before"),
                after=_file_state(item["after"], f"filesystem_delta[{index}].after"),
            )
            for index, item in enumerate(delta_values)
        ),
        warnings=_strings(receipt_value["warnings"], "warnings"),
    )
