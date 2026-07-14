"""Versioned, deterministic receipt schema."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import PurePosixPath
import re
from typing import Literal, Mapping, cast

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
        if self.duration_seconds < 0:
            raise ValueError("duration cannot be negative")
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


def _file_state(value: object) -> FileState | None:
    if value is None:
        return None
    item = cast(Mapping[str, object], value)
    return FileState(
        kind=cast(FileKind, item["kind"]),
        size=int(cast(int, item["size"])),
        sha256=cast(str | None, item["sha256"]),
        mode=cast(int | None, item["mode"]),
        symlink_target=cast(str | None, item["symlink_target"]),
    )


def receipt_from_dict(value: Mapping[str, object]) -> Receipt:
    run_value = cast(Mapping[str, object], value["run"])
    coverage_value = cast(Mapping[str, object], value["coverage"])
    delta_values = cast(list[Mapping[str, object]], value["filesystem_delta"])
    return Receipt(
        schema_version=cast(Literal[1], value["schema_version"]),
        run_id=str(value["run_id"]),
        trust_label=cast(Literal["REHEARSAL_NOT_SANDBOXED"], value["trust_label"]),
        started_at=str(value["started_at"]),
        platform=str(value["platform"]),
        tool_version=str(value["tool_version"]),
        argv=tuple(cast(list[str], value["argv"])),
        executable_path=cast(str | None, value["executable_path"]),
        executable_sha256=cast(str | None, value["executable_sha256"]),
        inherited_environment_keys=tuple(cast(list[str], value["inherited_environment_keys"])),
        run=RunResult(
            exit_code=cast(int | None, run_value["exit_code"]),
            termination_reason=cast(TerminationReason, run_value["termination_reason"]),
            duration_seconds=float(cast(float, run_value["duration_seconds"])),
            stdout_sha256=str(run_value["stdout_sha256"]),
            stderr_sha256=str(run_value["stderr_sha256"]),
            stdout_excerpt=str(run_value["stdout_excerpt"]),
            stderr_excerpt=str(run_value["stderr_excerpt"]),
            stdout_truncated=bool(run_value["stdout_truncated"]),
            stderr_truncated=bool(run_value["stderr_truncated"]),
        ),
        coverage=Coverage(
            profile_root=str(coverage_value["profile_root"]),
            covered_paths=tuple(cast(list[str], coverage_value["covered_paths"])),
            limitations=tuple(cast(list[str], coverage_value["limitations"])),
        ),
        filesystem_delta=tuple(
            FileDelta(
                path=str(item["path"]),
                change=cast(ChangeKind, item["change"]),
                before=_file_state(item["before"]),
                after=_file_state(item["after"]),
            )
            for item in delta_values
        ),
        warnings=tuple(cast(list[str], value["warnings"])),
    )

