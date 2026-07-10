from __future__ import annotations

import math
from enum import StrEnum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Annotated, Any, Self
from urllib.parse import urlsplit

from pydantic import (
    AwareDatetime,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

SCHEMA_VERSION = 2
_MAX_PATH_LENGTH = 1024
_SHELL_EXECUTABLES = frozenset(
    {
        "bash",
        "cmd",
        "cmd.exe",
        "dash",
        "fish",
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "sh",
        "zsh",
    }
)


class Permission(StrEnum):
    NETWORK = "network"
    FILESYSTEM_READ = "filesystem-read"
    FILESYSTEM_WRITE = "filesystem-write"
    PROCESS_SPAWN = "process-spawn"
    BROWSER_CONTROL = "browser-control"
    SHELL_EXEC = "shell-exec"
    CREDENTIALS_READ = "credentials-read"
    NONE = "none"


class InstallScope(StrEnum):
    PROJECT = "project"
    USER = "user"
    REPO_COMMITTED = "repo-committed"


class ActionOperation(StrEnum):
    INSTALL = "install"
    UPDATE = "update"
    VERIFY = "verify"
    REMOVE = "remove"
    ADOPT = "adopt"
    LEAVE_UNMANAGED = "leave_unmanaged"
    REPLACE = "replace"


class VerificationState(StrEnum):
    NOT_RUN = "not_run"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class TransactionState(StrEnum):
    PLANNED = "planned"
    PREFLIGHT = "preflight"
    APPLYING = "applying"
    VERIFYING = "verifying"
    SUCCEEDED = "succeeded"
    ROLLING_BACK = "rolling_back"
    ROLLED_BACK = "rolled_back"
    ROLLBACK_FAILED = "rollback_failed"
    INTERRUPTED = "interrupted"


class EvidenceStrength(StrEnum):
    WEAK = "weak"
    STRONG = "strong"
    REQUIRED = "required"


class CapabilityStatus(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"


class Provider(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"
    COMBINED = "combined"
    UNKNOWN = "unknown"


class Platform(StrEnum):
    LINUX = "linux"
    MACOS = "macos"
    WINDOWS = "windows"


class Harness(StrEnum):
    CLAUDE = "claude"
    CODEX = "codex"


Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[a-z0-9][a-z0-9._-]*$",
    ),
]
CapabilityName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    ),
]
NonEmptyText = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2048)
]
Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
EnvironmentName = Annotated[str, StringConstraints(pattern=r"^[A-Z][A-Z0-9_]{0,127}$")]
VersionText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=128)]
Argument = Annotated[str, StringConstraints(min_length=1, max_length=4096)]
MatchKey = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=160,
        pattern=r"^[a-z][a-z0-9_-]{0,31}:[a-z0-9][a-z0-9._/-]{0,127}$",
    ),
]


def _normalize_relative_path(value: Any, *, allow_dot: bool = False) -> str:
    if not isinstance(value, (str, PurePosixPath)):
        raise ValueError("path must be a string")
    text = str(value)
    if not text or len(text) > _MAX_PATH_LENGTH or "\0" in text:
        raise ValueError("path must be nonempty, bounded, and contain no NUL")
    windows = PureWindowsPath(text)
    if windows.is_absolute() or windows.drive or text.startswith(("/", "\\")):
        raise ValueError("path must be repository-relative")
    normalized = text.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("path must not escape the repository")
    collapsed = path.as_posix()
    if collapsed == "." and not allow_dot:
        raise ValueError("path must identify a repository entry")
    return collapsed


def _relative_path(value: Any) -> str:
    return _normalize_relative_path(value)


RelativePath = Annotated[str, BeforeValidator(_relative_path)]


def relative_path_or_none(value: Any) -> PurePosixPath | None:
    """Return a normalized safe path, or ``None`` for any invalid input."""

    try:
        return PurePosixPath(_normalize_relative_path(value, allow_dot=True))
    except (TypeError, ValueError):
        return None


class StrictFrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SchemaV2Model(StrictFrozenModel):
    schema_version: int = SCHEMA_VERSION

    @field_validator("schema_version", mode="before")
    @classmethod
    def _schema_version_is_exactly_two(cls, value: Any) -> int:
        if type(value) is not int or value != SCHEMA_VERSION:
            raise ValueError(f"schema_version must be integer {SCHEMA_VERSION}")
        return value


def _unique(values: tuple[Any, ...], field_name: str) -> tuple[Any, ...]:
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return values


class EvidenceV2(StrictFrozenModel):
    type: Identifier
    key: Identifier
    detail: Annotated[str, StringConstraints(max_length=2048)] = ""
    source: RelativePath
    strength: EvidenceStrength


class CapabilitySnapshot(SchemaV2Model):
    provider: Provider
    provider_version: Annotated[str, StringConstraints(max_length=128)] | None = None
    status: CapabilityStatus
    native: tuple[CapabilityName, ...] = ()
    installed: tuple[CapabilityName, ...] = ()
    managed: tuple[CapabilityName, ...] = ()
    errors: tuple[Annotated[str, StringConstraints(min_length=1, max_length=2048)], ...] = ()

    @model_validator(mode="after")
    def _capabilities_are_consistent(self) -> Self:
        _unique(self.native, "native")
        _unique(self.installed, "installed")
        _unique(self.managed, "managed")
        if not set(self.managed).issubset(self.installed):
            raise ValueError("managed capabilities must also be installed")
        if self.status is CapabilityStatus.UNKNOWN and not self.errors:
            raise ValueError("unknown capability snapshots require an error")
        return self


class ActionStepV2(StrictFrozenModel):
    argv: Annotated[tuple[Argument, ...], Field(min_length=1, max_length=64)]
    cwd: RelativePath | None = None
    timeout_seconds: Annotated[float, Field(gt=0, le=3600, allow_inf_nan=False)] = 180.0
    requires_network: bool = False
    requires_elevation: bool = False

    @field_validator("argv")
    @classmethod
    def _argv_is_direct_and_bounded(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        for argument in value:
            if "\0" in argument or "\n" in argument or "\r" in argument:
                raise ValueError("argv entries must not contain control characters")
        executable = value[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
        if executable in _SHELL_EXECUTABLES:
            raise ValueError("shell wrappers are not valid action executables")
        return value


class CatalogToolV2(SchemaV2Model):
    id: Identifier
    name: NonEmptyText
    summary: NonEmptyText
    kind: Identifier
    provenance: NonEmptyText
    version: VersionText
    homepage: NonEmptyText
    license: NonEmptyText
    platforms: Annotated[tuple[Platform, ...], Field(min_length=1)]
    harnesses: Annotated[tuple[Harness, ...], Field(min_length=1)]
    permissions: Annotated[tuple[Permission, ...], Field(min_length=1)]
    install_scope: InstallScope
    artifacts: tuple[RelativePath, ...] = ()
    required_env: tuple[EnvironmentName, ...] = ()
    strong_evidence: tuple[MatchKey, ...] = ()
    weak_evidence: tuple[MatchKey, ...] = ()
    required_capabilities: tuple[Identifier, ...] = ()
    suppressed_by_capabilities: tuple[Identifier, ...] = ()
    live_name: Identifier | None = None
    install: ActionStepV2
    verify: ActionStepV2
    rollback: ActionStepV2
    enabled: bool = True

    @field_validator("homepage")
    @classmethod
    def _homepage_is_public_http_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
        ):
            raise ValueError("homepage must be an http(s) URL without credentials")
        return value

    @model_validator(mode="after")
    def _catalog_collections_are_consistent(self) -> Self:
        for field_name in (
            "platforms",
            "harnesses",
            "permissions",
            "artifacts",
            "required_env",
            "strong_evidence",
            "weak_evidence",
            "required_capabilities",
            "suppressed_by_capabilities",
        ):
            _unique(getattr(self, field_name), field_name)
        if Permission.NONE in self.permissions and self.permissions != (Permission.NONE,):
            raise ValueError("permission 'none' must be declared alone")
        if set(self.strong_evidence) & set(self.weak_evidence):
            raise ValueError("evidence cannot be both strong and weak")
        return self


class ActionV2(StrictFrozenModel):
    id: Identifier
    operation: ActionOperation
    tool_id: Identifier
    tool_version: VersionText
    install_scope: InstallScope
    permissions: tuple[Permission, ...] = ()
    evidence: tuple[EvidenceV2, ...] = ()
    confidence: Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
    why: NonEmptyText
    steps: tuple[ActionStepV2, ...] = ()
    verify: tuple[ActionStepV2, ...] = ()
    rollback: tuple[ActionStepV2, ...] = ()
    required_env: tuple[EnvironmentName, ...] = ()

    @model_validator(mode="after")
    def _action_is_consistent(self) -> Self:
        for field_name in ("permissions", "required_env"):
            _unique(getattr(self, field_name), field_name)
        if not math.isfinite(self.confidence):
            raise ValueError("confidence must be finite")
        if self.operation in {
            ActionOperation.INSTALL,
            ActionOperation.UPDATE,
            ActionOperation.REPLACE,
        }:
            if not self.steps or not self.verify or not self.rollback:
                raise ValueError("mutating actions require steps, verification, and rollback")
        return self


class RepositoryBinding(StrictFrozenModel):
    root: str = "."
    identity: Digest
    content_digest: Digest
    git_head: Annotated[str, StringConstraints(min_length=1, max_length=128)] | None = None
    dirty_digest: Digest | None = None

    @field_validator("root", mode="before")
    @classmethod
    def _root_is_portable(cls, value: Any) -> str:
        return _normalize_relative_path(value, allow_dot=True)


class PlanV2(SchemaV2Model):
    plan_id: Digest
    repository: RepositoryBinding
    catalog_digest: Digest
    capability_digest: Digest
    catalog_tools: Annotated[dict[Identifier, VersionText], Field(min_length=1)]
    actions: tuple[ActionV2, ...] = ()
    created_at: AwareDatetime
    expires_at: AwareDatetime

    @model_validator(mode="after")
    def _plan_references_are_exact(self) -> Self:
        action_ids = tuple(action.id for action in self.actions)
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("action IDs must be unique")
        for action in self.actions:
            if self.catalog_tools.get(action.tool_id) != action.tool_version:
                raise ValueError(f"action {action.id} has an inexact catalog reference")
        if self.expires_at <= self.created_at:
            raise ValueError("expires_at must be after created_at")
        return self


class DeclaredToolV2(StrictFrozenModel):
    tool_id: Identifier
    version: VersionText
    provenance: NonEmptyText
    install_scope: InstallScope
    permissions: tuple[Permission, ...] = ()
    required_env: tuple[EnvironmentName, ...] = ()
    artifacts: tuple[RelativePath, ...] = ()


class DeclarationV2(SchemaV2Model):
    repository_identity: Digest
    catalog_digest: Digest
    tools: tuple[DeclaredToolV2, ...] = ()

    @model_validator(mode="after")
    def _tool_ids_are_unique(self) -> Self:
        tool_ids = tuple(tool.tool_id for tool in self.tools)
        if len(tool_ids) != len(set(tool_ids)):
            raise ValueError("declared tool IDs must be unique")
        return self


class CommandResultV2(SchemaV2Model):
    argv: Annotated[tuple[Argument, ...], Field(min_length=1, max_length=64)]
    returncode: int | None
    stdout: Annotated[str, StringConstraints(max_length=65536)] = ""
    stderr: Annotated[str, StringConstraints(max_length=65536)] = ""
    duration_seconds: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    timed_out: bool = False
    redacted: bool = False
    verification: VerificationState = VerificationState.NOT_RUN


__all__ = [
    "ActionOperation",
    "ActionStepV2",
    "ActionV2",
    "CapabilitySnapshot",
    "CapabilityStatus",
    "CatalogToolV2",
    "CommandResultV2",
    "DeclarationV2",
    "DeclaredToolV2",
    "EvidenceStrength",
    "EvidenceV2",
    "Harness",
    "InstallScope",
    "Permission",
    "PlanV2",
    "Platform",
    "Provider",
    "RelativePath",
    "RepositoryBinding",
    "SCHEMA_VERSION",
    "TransactionState",
    "VerificationState",
    "relative_path_or_none",
]
