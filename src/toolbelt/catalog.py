from __future__ import annotations

import os
import re
import tomllib
from importlib.resources import files
from importlib.resources.abc import Traversable
from pathlib import Path

from toolbelt.models import APPLY_VIA, INSTALL_SCOPE, PERMISSION, TOOL_KIND, CatalogStep, MatchGroup, Tool


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
    path = path or default_catalog_path()
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CatalogError(f"catalog not found: {path}") from exc
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
