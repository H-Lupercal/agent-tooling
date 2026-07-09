from __future__ import annotations

import os
import re
import tomllib
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from hashlib import sha256
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import overload
from urllib.parse import urlsplit

from pydantic import ValidationError as PydanticValidationError

from toolbelt.errors import ValidationError as ToolbeltValidationError
from toolbelt.models import APPLY_VIA, INSTALL_SCOPE, PERMISSION, TOOL_KIND, CatalogStep, MatchGroup, Tool
from toolbelt.schemas import CatalogToolV2, Permission, Platform


class CatalogError(Exception):
    pass


PROVENANCE_SCHEMES = (
    "npm:",
    "pypi:",
    "pip:",
    "uv:",
    "uvx:",
    "go:",
    "cargo:",
    "gem:",
    "composer:",
    "docker:",
    "claude-plugin:",
    "toolbelt:",
    "https://",
    "http://",
)
TOOL_KEYS = {
    "id",
    "kind",
    "name",
    "summary",
    "provenance",
    "homepage",
    "approved",
    "foundational",
    "permissions",
    "install_scope",
    "secrets",
    "artifacts",
    "mcp_name",
    "verify_argv",
    "catalog_version",
    "match",
    "apply",
}
MATCH_KEYS = {"any_files", "manifest_file", "manifest_deps", "langs", "infra", "brief_keywords", "weight"}
STEP_KEYS = {
    "apply_via",
    "harness",
    "mcp_command",
    "mcp_args",
    "plugin_ref",
    "command_argv",
    "rollback_argv",
    "scaffold_path",
    "scaffold_body",
    "block_path",
    "block_body",
}


def default_catalog_path() -> Traversable:
    override = os.environ.get("TOOLBELT_CATALOG")
    if override:
        return Path(override)
    return files("toolbelt").joinpath("data", "catalog-v1.toml")


def default_catalog_v2_path() -> Traversable:
    override = os.environ.get("TOOLBELT_CATALOG")
    if override:
        return Path(override)
    return files("toolbelt").joinpath("data", "catalog.toml")


def _tuple(value) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, tuple):
        return tuple(str(v) for v in value)
    return (str(value),)


def _unknown_keys(tool_id: str, obj: dict, allowed: set[str]) -> None:
    for key in obj:
        if key not in allowed:
            raise CatalogError(f"tool {tool_id}: unknown key {key}")


def _looks_like_secret(token: str, secret_names: tuple[str, ...]) -> bool:
    if token in secret_names:
        return True
    if re.match(r"^[A-Z][A-Z0-9_]{2,}=", token):
        return True
    if "://" in token:
        authority = token.split("://", 1)[1].split("/", 1)[0]
        if "@" in authority:
            return True
    return False


def safety_lint(
    tools: list[Tool],
    *,
    existing_ids: frozenset[str] = frozenset(),
    existing_mcp: frozenset[tuple[str, str]] = frozenset(),
) -> list[str]:
    issues: list[str] = []
    for tool in tools:
        if tool.approved:
            issues.append(f"{tool.id}: proposals must set approved = false")
        if not tool.provenance or not tool.provenance.startswith(PROVENANCE_SCHEMES):
            issues.append(f"{tool.id}: provenance must be present and use a known scheme")
        if not tool.homepage:
            issues.append(f"{tool.id}: homepage required for human review")
        if not tool.permissions:
            issues.append(f"{tool.id}: permissions must be declared (use [\"none\"] if truly none)")
        if not tool.catalog_version:
            issues.append(f"{tool.id}: catalog_version required")
        if tool.id in existing_ids:
            issues.append(f"{tool.id}: id already exists in the live catalog")
        for step in tool.apply:
            for token in (*step.mcp_args, *step.command_argv):
                if _looks_like_secret(token, tool.secrets):
                    issues.append(
                        f"{tool.id}: possible secret value in args: {token!r} - put the env var name in `secrets`"
                    )
            if step.apply_via in {"claude_mcp", "codex_mcp"} and (step.apply_via, tool.mcp_name) in existing_mcp:
                issues.append(f"{tool.id}: mcp_name {tool.mcp_name!r} already claimed for {step.apply_via}")
    return issues


def load_catalog(path: Path | None = None) -> list[Tool]:
    source: Traversable = path if path is not None else default_catalog_path()
    try:
        raw = tomllib.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"catalog not found: {source}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CatalogError(str(exc)) from exc

    seen: set[str] = set()
    mcp_claims: set[tuple[str, str]] = set()
    tools: list[Tool] = []
    for raw_tool in raw.get("tool", []):
        tool_id = str(raw_tool.get("id", ""))
        if tool_id in seen:
            raise CatalogError(f"tool {tool_id}: duplicate id")
        seen.add(tool_id)
        _unknown_keys(tool_id, raw_tool, TOOL_KEYS)
        kind = str(raw_tool.get("kind", ""))
        if kind not in TOOL_KIND:
            raise CatalogError(f"tool {tool_id}: kind must be one of {sorted(TOOL_KIND)}")
        for perm in _tuple(raw_tool.get("permissions")):
            if perm not in PERMISSION:
                raise CatalogError(f"tool {tool_id}: unknown permission {perm}")
        scope = str(raw_tool.get("install_scope", ""))
        if scope not in INSTALL_SCOPE:
            raise CatalogError(f"tool {tool_id}: install_scope must be one of {sorted(INSTALL_SCOPE)}")

        matches = raw_tool.get("match") or []
        if not matches:
            raise CatalogError(f"tool {tool_id}: at least one match group required")
        match_groups: list[MatchGroup] = []
        for group in matches:
            _unknown_keys(tool_id, group, MATCH_KEYS)
            declared = [
                bool(group.get("any_files")),
                bool(group.get("manifest_file")),
                bool(group.get("langs")),
                bool(group.get("infra")),
                bool(group.get("brief_keywords")),
            ]
            if not any(declared):
                raise CatalogError(f"tool {tool_id}: match group must declare at least one predicate")
            match_groups.append(
                MatchGroup(
                    any_files=_tuple(group.get("any_files")),
                    manifest_file=str(group.get("manifest_file", "")),
                    manifest_deps=_tuple(group.get("manifest_deps")),
                    langs=_tuple(group.get("langs")),
                    infra=_tuple(group.get("infra")),
                    brief_keywords=_tuple(group.get("brief_keywords")),
                    weight=int(group.get("weight", 1)),
                )
            )

        steps = raw_tool.get("apply") or []
        if not steps:
            raise CatalogError(f"tool {tool_id}: at least one apply step required")
        catalog_steps: list[CatalogStep] = []
        for step in steps:
            _unknown_keys(tool_id, step, STEP_KEYS)
            apply_via = str(step.get("apply_via", ""))
            allowed_apply = APPLY_VIA - {"scaffold_remove", "managed_block_remove"}
            if apply_via not in allowed_apply:
                raise CatalogError(f"tool {tool_id}: apply_via must be one of {sorted(allowed_apply)}")
            if apply_via in {"claude_mcp", "codex_mcp"} and not step.get("mcp_command"):
                raise CatalogError(f"tool {tool_id}: claude_mcp/codex_mcp step needs mcp_command")
            if kind in {"mcp_server", "connector"} and not raw_tool.get("mcp_name"):
                raise CatalogError(f"tool {tool_id}: mcp_name required for mcp_server/connector")
            if apply_via == "claude_plugin" and not step.get("plugin_ref"):
                raise CatalogError(f"tool {tool_id}: claude_plugin step needs plugin_ref")
            if apply_via == "command" and not step.get("command_argv"):
                raise CatalogError(f"tool {tool_id}: command step needs command_argv")
            if apply_via == "scaffold" and (not step.get("scaffold_path") or not step.get("scaffold_body")):
                raise CatalogError(f"tool {tool_id}: scaffold step needs scaffold_path and scaffold_body")
            if apply_via == "managed_block" and (not step.get("block_path") or not step.get("block_body")):
                raise CatalogError(f"tool {tool_id}: managed_block step needs block_path and block_body")
            if apply_via in {"claude_mcp", "codex_mcp"}:
                claim = (apply_via, str(raw_tool.get("mcp_name", "")))
                if claim in mcp_claims:
                    raise CatalogError(f"tool {tool_id}: duplicate mcp_name {claim[1]} for harness {apply_via}")
                mcp_claims.add(claim)
            catalog_steps.append(
                CatalogStep(
                    apply_via=apply_via,
                    harness=str(step.get("harness", "")),
                    mcp_command=str(step.get("mcp_command", "")),
                    mcp_args=_tuple(step.get("mcp_args")),
                    plugin_ref=str(step.get("plugin_ref", "")),
                    command_argv=_tuple(step.get("command_argv")),
                    rollback_argv=_tuple(step.get("rollback_argv")),
                    scaffold_path=str(step.get("scaffold_path", "")),
                    scaffold_body=str(step.get("scaffold_body", "")),
                    block_path=str(step.get("block_path", "")),
                    block_body=str(step.get("block_body", "")),
                )
            )

        tools.append(
            Tool(
                id=tool_id,
                kind=kind,
                name=str(raw_tool.get("name", "")),
                summary=str(raw_tool.get("summary", "")),
                provenance=str(raw_tool.get("provenance", "")),
                homepage=str(raw_tool.get("homepage", "")),
                approved=bool(raw_tool.get("approved", False)),
                foundational=bool(raw_tool.get("foundational", False)),
                permissions=_tuple(raw_tool.get("permissions")),
                install_scope=scope,
                secrets=_tuple(raw_tool.get("secrets")),
                artifacts=_tuple(raw_tool.get("artifacts")),
                mcp_name=str(raw_tool.get("mcp_name", "")),
                match=tuple(match_groups),
                apply=tuple(catalog_steps),
                verify_argv=_tuple(raw_tool.get("verify_argv")),
                catalog_version=str(raw_tool.get("catalog_version", "")),
            )
        )
    return sorted(tools, key=lambda t: t.id)


class CatalogV2Error(ToolbeltValidationError):
    """A strict v2 catalog could not be trusted."""


@dataclass(frozen=True, slots=True)
class CatalogV2(Sequence[CatalogToolV2]):
    schema_version: int
    tools: tuple[CatalogToolV2, ...]
    digest: str
    source: str
    raw_bytes: bytes = field(repr=False)

    def __iter__(self) -> Iterator[CatalogToolV2]:
        return iter(self.tools)

    def __len__(self) -> int:
        return len(self.tools)

    @overload
    def __getitem__(self, index: int) -> CatalogToolV2: ...

    @overload
    def __getitem__(self, index: slice) -> tuple[CatalogToolV2, ...]: ...

    def __getitem__(
        self, index: int | slice
    ) -> CatalogToolV2 | tuple[CatalogToolV2, ...]:
        return self.tools[index]


_CATALOG_V2_MAX_BYTES = 1024 * 1024
_SUPPORTED_PROVENANCE = frozenset(
    {"cargo", "claude-plugin", "go", "npm", "pypi", "toolbelt", "uv", "uvx"}
)
_NETWORK_PACKAGE_PROVENANCE = frozenset({"cargo", "go", "npm", "pypi", "uv", "uvx"})
_SHELL_METACHARACTERS = frozenset({"&&", "||", ";", "|", ">", ">>", "<", "<<"})
_SECRET_PREFIXES = ("akia", "ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-")


def load_catalog_v2(path: Path | None = None) -> CatalogV2:
    source: Traversable = path if path is not None else default_catalog_v2_path()
    source_name = (
        str(Path(path).resolve())
        if path is not None
        else (
            str(Path(source).resolve())
            if os.environ.get("TOOLBELT_CATALOG") and isinstance(source, Path)
            else "package:toolbelt/data/catalog.toml"
        )
    )
    try:
        raw_bytes = source.read_bytes()
    except OSError as exc:
        raise CatalogV2Error(f"catalog not found: {source_name}") from exc
    if len(raw_bytes) > _CATALOG_V2_MAX_BYTES:
        raise CatalogV2Error("catalog exceeds the one MiB size limit")
    try:
        decoded = raw_bytes.decode("utf-8")
        raw = tomllib.loads(decoded)
    except UnicodeDecodeError as exc:
        raise CatalogV2Error("catalog must be valid UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CatalogV2Error(f"invalid catalog TOML: {exc}") from exc
    if set(raw) != {"schema_version", "tool"}:
        raise CatalogV2Error("catalog root accepts only schema_version and tool")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 2:
        raise CatalogV2Error("catalog schema_version must be integer 2")
    raw_tools = raw.get("tool")
    if not isinstance(raw_tools, list):
        raise CatalogV2Error("catalog tool must be an array of tables")

    tools: list[CatalogToolV2] = []
    ids: set[str] = set()
    live_names: set[str] = set()
    for raw_tool in raw_tools:
        if not isinstance(raw_tool, dict):
            raise CatalogV2Error("catalog entries must be tables")
        try:
            tool = CatalogToolV2.model_validate(raw_tool)
        except PydanticValidationError as exc:
            raise CatalogV2Error(f"invalid catalog entry: {exc}") from exc
        if tool.id in ids:
            raise CatalogV2Error(f"duplicate tool id: {tool.id}")
        ids.add(tool.id)
        if tool.live_name is not None:
            if tool.live_name in live_names:
                raise CatalogV2Error(f"duplicate live name: {tool.live_name}")
            live_names.add(tool.live_name)
        _validate_v2_tool(tool)
        tools.append(tool)

    return CatalogV2(
        schema_version=2,
        tools=tuple(sorted(tools, key=lambda item: item.id)),
        digest=sha256(raw_bytes).hexdigest(),
        source=source_name,
        raw_bytes=raw_bytes,
    )


def _validate_v2_tool(tool: CatalogToolV2) -> None:
    scheme, separator, specification = tool.provenance.partition(":")
    if not separator or scheme not in _SUPPORTED_PROVENANCE:
        raise CatalogV2Error(f"tool {tool.id}: unsupported provenance")
    requires_network = any(
        step.requires_network for step in (tool.install, tool.verify, tool.rollback)
    )
    if requires_network and Permission.NETWORK not in tool.permissions:
        raise CatalogV2Error(f"tool {tool.id}: network operation lacks network permission")
    if scheme in _NETWORK_PACKAGE_PROVENANCE and not tool.install.requires_network:
        raise CatalogV2Error(
            f"tool {tool.id}: package installation must declare network use"
        )
    if scheme in _NETWORK_PACKAGE_PROVENANCE:
        _validate_pinned_provenance(tool, scheme, specification)
    for step in (tool.install, tool.verify, tool.rollback):
        _validate_safe_argv(tool, step.argv)
    executable = tool.install.argv[0].replace("\\", "/")
    if Platform.WINDOWS in tool.platforms and executable.startswith("/"):
        raise CatalogV2Error(f"tool {tool.id}: inconsistent platform executable")


def _validate_pinned_provenance(
    tool: CatalogToolV2,
    scheme: str,
    specification: str,
) -> None:
    pinned_version = ""
    if scheme in {"pypi", "uv", "uvx"}:
        _, separator, pinned_version = specification.partition("==")
        if not separator or any(marker in pinned_version for marker in ("*", ",", ";")):
            pinned_version = ""
    elif scheme == "npm":
        package, separator, pinned_version = specification.rpartition("@")
        if not separator or not package or pinned_version.lower() == "latest":
            pinned_version = ""
    else:
        _, separator, pinned_version = specification.rpartition("@")
        if not separator:
            pinned_version = ""
    if pinned_version != tool.version:
        raise CatalogV2Error(
            f"tool {tool.id}: network package provenance must be pinned to {tool.version}"
        )


def _validate_safe_argv(tool: CatalogToolV2, argv: tuple[str, ...]) -> None:
    for token in argv:
        lowered = token.lower()
        if token in _SHELL_METACHARACTERS or "$(" in token or "`" in token:
            raise CatalogV2Error(f"tool {tool.id}: shell metacharacter in argv")
        if (
            re.match(r"^[A-Z][A-Z0-9_]{2,}=", token)
            or re.search(
                r"(?i)(?:api[-_]?key|password|secret|token)=",
                token,
            )
            or token in tool.required_env
            or lowered.startswith(_SECRET_PREFIXES)
        ):
            raise CatalogV2Error(f"tool {tool.id}: secret-shaped argv is forbidden")
        if "://" in token:
            parsed = urlsplit(token)
            if parsed.username is not None or parsed.password is not None:
                raise CatalogV2Error(f"tool {tool.id}: secret-shaped argv is forbidden")
