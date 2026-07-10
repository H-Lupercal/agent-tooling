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

from toolbelt.errors import ValidationError
from toolbelt.schemas import CatalogToolV2, Permission, Platform


class CatalogV2Error(ValidationError):
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

    def __getitem__(self, index: int | slice) -> CatalogToolV2 | tuple[CatalogToolV2, ...]:
        return self.tools[index]


_CATALOG_MAX_BYTES = 1024 * 1024
_SUPPORTED_PROVENANCE = frozenset(
    {"cargo", "claude-plugin", "go", "npm", "pypi", "toolbelt", "uv", "uvx"}
)
_NETWORK_PACKAGE_PROVENANCE = frozenset({"cargo", "go", "npm", "pypi", "uv", "uvx"})
_SHELL_METACHARACTERS = frozenset({"&&", "||", ";", "|", ">", ">>", "<", "<<"})
_SECRET_PREFIXES = ("akia", "ghp_", "github_pat_", "sk-", "xoxb-", "xoxp-")


def default_catalog_path() -> Traversable:
    override = os.environ.get("TOOLBELT_CATALOG")
    if override:
        return Path(override)
    return files("toolbelt").joinpath("data", "catalog.toml")


def load_catalog_v2(path: Path | None = None) -> CatalogV2:
    source: Traversable = path if path is not None else default_catalog_path()
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
    if len(raw_bytes) > _CATALOG_MAX_BYTES:
        raise CatalogV2Error("catalog exceeds the one MiB size limit")
    try:
        raw = tomllib.loads(raw_bytes.decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise CatalogV2Error("catalog must be valid UTF-8") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CatalogV2Error(f"invalid catalog TOML: {exc}") from exc
    if set(raw) != {"schema_version", "tool"}:
        raise CatalogV2Error("catalog root accepts only schema_version and tool")
    if type(raw.get("schema_version")) is not int or raw["schema_version"] != 2:
        raise CatalogV2Error("catalog schema_version must be integer 2")
    raw_tools = raw.get("tool")
    if not isinstance(raw_tools, list) or not raw_tools:
        raise CatalogV2Error("catalog tool must be a nonempty array of tables")

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
        _validate_tool(tool)
        tools.append(tool)

    return CatalogV2(
        schema_version=2,
        tools=tuple(sorted(tools, key=lambda item: item.id)),
        digest=sha256(raw_bytes).hexdigest(),
        source=source_name,
        raw_bytes=raw_bytes,
    )


def _validate_tool(tool: CatalogToolV2) -> None:
    scheme, separator, specification = tool.provenance.partition(":")
    if not separator or scheme not in _SUPPORTED_PROVENANCE:
        raise CatalogV2Error(f"tool {tool.id}: unsupported provenance")
    steps = (tool.install, tool.verify, tool.rollback)
    requires_network = any(step.requires_network for step in steps)
    if requires_network and Permission.NETWORK not in tool.permissions:
        raise CatalogV2Error(f"tool {tool.id}: network operation lacks network permission")
    if tool.required_env and Permission.CREDENTIALS_READ not in tool.permissions:
        raise CatalogV2Error(
            f"tool {tool.id}: required environment variables need credentials-read permission"
        )
    if Permission.FILESYSTEM_WRITE not in tool.permissions:
        raise CatalogV2Error(f"tool {tool.id}: installation lacks filesystem-write permission")
    if scheme in _NETWORK_PACKAGE_PROVENANCE and not tool.install.requires_network:
        raise CatalogV2Error(f"tool {tool.id}: package installation must declare network use")
    if scheme in _NETWORK_PACKAGE_PROVENANCE:
        _validate_pinned_provenance(tool, scheme, specification)
    for step in steps:
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
            or re.search(r"(?i)(?:api[-_]?key|password|secret|token)=", token)
            or token in tool.required_env
            or lowered.startswith(_SECRET_PREFIXES)
        ):
            raise CatalogV2Error(f"tool {tool.id}: secret-shaped argv is forbidden")
        if "://" in token:
            parsed = urlsplit(token)
            if parsed.username is not None or parsed.password is not None:
                raise CatalogV2Error(f"tool {tool.id}: secret-shaped argv is forbidden")


__all__ = [
    "CatalogV2",
    "CatalogV2Error",
    "default_catalog_path",
    "load_catalog_v2",
]
