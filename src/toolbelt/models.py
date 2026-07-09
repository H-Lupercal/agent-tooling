from __future__ import annotations

from dataclasses import dataclass

from toolbelt.schemas import (
    ActionOperation,
    InstallScope,
    Permission,
    TransactionState,
    VerificationState,
)


TOOL_KIND = {"mcp_server", "connector", "plugin", "skill", "lsp", "dev_tool"}
PERMISSION = {
    "network",
    "filesystem-read",
    "filesystem-write",
    "process-spawn",
    "browser-control",
    "shell-exec",
    "credentials-read",
    "none",
}
INSTALL_SCOPE = {"project", "user", "repo-committed"}
EVIDENCE_TYPE = {
    "manifest_file",
    "manifest_dep",
    "lang_ext",
    "infra",
    "test_setup",
    "brief_keyword",
    "existing_tool",
    "file_glob",
}
ACTION_OP = {"install", "update", "verify", "remove"}
APPLY_VIA = {
    "claude_mcp",
    "codex_mcp",
    "claude_plugin",
    "scaffold",
    "scaffold_remove",
    "command",
    "managed_block",
    "managed_block_remove",
}
MANIFEST_STATE = {"planned", "installed", "verify_failed", "removed", "unknown"}
SKIP_DIRS = {
    ".git",
    ".toolbelt",
    "node_modules",
    "dist",
    "build",
    ".venv",
    "__pycache__",
}

# Public v2 contracts live in ``schemas``. These imports keep the legacy model
# module useful during the staged v2 replacement without adding compatibility
# aliases for the v1 wire format.
V2_ENUMS = (
    ActionOperation,
    InstallScope,
    Permission,
    TransactionState,
    VerificationState,
)


@dataclass(frozen=True)
class Evidence:
    type: str
    key: str
    detail: str
    weight: int
    source: str


@dataclass(frozen=True)
class CatalogStep:
    apply_via: str
    harness: str
    mcp_command: str = ""
    mcp_args: tuple[str, ...] = ()
    plugin_ref: str = ""
    command_argv: tuple[str, ...] = ()
    rollback_argv: tuple[str, ...] = ()
    scaffold_path: str = ""
    scaffold_body: str = ""
    block_path: str = ""
    block_body: str = ""


@dataclass(frozen=True)
class ApplyStep:
    apply_via: str
    harness: str
    argv: tuple[str, ...] = ()
    scaffold_path: str = ""
    scaffold_body: str = ""
    scaffold_sha256: str = ""
    rollback_argv: tuple[str, ...] = ()
    tolerate_failure: bool = False
    block_path: str = ""
    block_body: str = ""
    block_marker: str = ""


@dataclass(frozen=True)
class MatchGroup:
    any_files: tuple[str, ...] = ()
    manifest_file: str = ""
    manifest_deps: tuple[str, ...] = ()
    langs: tuple[str, ...] = ()
    infra: tuple[str, ...] = ()
    brief_keywords: tuple[str, ...] = ()
    weight: int = 1


@dataclass(frozen=True)
class Tool:
    id: str
    kind: str
    name: str
    summary: str
    provenance: str
    homepage: str
    approved: bool
    foundational: bool
    permissions: tuple[str, ...]
    install_scope: str
    secrets: tuple[str, ...]
    artifacts: tuple[str, ...]
    mcp_name: str
    match: tuple[MatchGroup, ...]
    apply: tuple[CatalogStep, ...]
    verify_argv: tuple[str, ...]
    catalog_version: str


@dataclass(frozen=True)
class Recommendation:
    tool_id: str
    confidence: int
    matched: tuple[Evidence, ...]
    provisional: bool


@dataclass(frozen=True)
class Action:
    id: str
    op: str
    tool_id: str
    kind: str
    harnesses: tuple[str, ...]
    purpose: str
    provenance: str
    permissions: tuple[str, ...]
    install_scope: str
    secrets_required: tuple[str, ...]
    evidence: tuple[Evidence, ...]
    steps: tuple[ApplyStep, ...]
    verify_argv: tuple[str, ...]
    rollback: str
    approved: bool | None


@dataclass(frozen=True)
class Plan:
    schema_version: int
    generated_at: str
    project_root: str
    mode: str
    actions: tuple[Action, ...]
