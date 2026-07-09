from __future__ import annotations

import json
from pathlib import Path

import pytest

from toolbelt.catalog import CatalogV2Error, load_catalog_v2


def _tool_block(
    *,
    tool_id: str = "ruff",
    live_name: str = "ruff",
    provenance: str = "pypi:ruff==0.8.6",
    version: str = "0.8.6",
    install_argv: tuple[str, ...] = ("python", "-m", "pip", "install", "ruff==0.8.6"),
    platforms: tuple[str, ...] = ("linux", "macos", "windows"),
    include_rollback: bool = True,
    requires_network: bool = True,
) -> str:
    rollback = (
        'rollback = { argv = ["python", "-m", "pip", "uninstall", "-y", "ruff"] }'
        if include_rollback
        else ""
    )
    return f"""
[[tool]]
schema_version = 2
id = {json.dumps(tool_id)}
name = "Ruff"
summary = "Python linting"
kind = "dev_tool"
provenance = {json.dumps(provenance)}
version = {json.dumps(version)}
homepage = "https://example.com/ruff"
license = "MIT"
platforms = {json.dumps(platforms)}
harnesses = ["claude", "codex"]
permissions = ["network", "process-spawn"]
install_scope = "project"
artifacts = ["pyproject.toml"]
required_env = []
strong_evidence = ["test:pytest"]
weak_evidence = ["lang:python"]
required_capabilities = []
suppressed_by_capabilities = []
live_name = {json.dumps(live_name)}
install = {{ argv = {json.dumps(install_argv)}, requires_network = {str(requires_network).lower()} }}
verify = {{ argv = ["ruff", "--version"] }}
{rollback}
enabled = true
"""


def _write_catalog(path: Path, *blocks: str, extra: str = "") -> Path:
    path.write_text(
        "schema_version = 2\n" + extra + "\n".join(blocks),
        encoding="utf-8",
    )
    return path


def test_packaged_catalog_is_strict_v2_with_contract_coverage():
    catalog = load_catalog_v2()

    assert catalog.schema_version == 2
    assert len(catalog.digest) == 64
    assert catalog.source == "package:toolbelt/data/catalog.toml"
    assert {tool.id for tool in catalog} >= {
        "mcp-filesystem",
        "mcp-git",
        "pyright",
        "ruff",
    }
    for tool in catalog:
        if tool.enabled:
            assert tool.install.argv
            assert tool.verify.argv
            assert tool.rollback.argv


def test_catalog_rejects_duplicate_ids_and_live_names(tmp_path: Path):
    duplicate_id = _write_catalog(
        tmp_path / "duplicate-id.toml",
        _tool_block(),
        _tool_block(live_name="ruff-other"),
    )
    duplicate_live = _write_catalog(
        tmp_path / "duplicate-live.toml",
        _tool_block(),
        _tool_block(tool_id="ruff-two"),
    )

    with pytest.raises(CatalogV2Error, match="duplicate tool id"):
        load_catalog_v2(duplicate_id)
    with pytest.raises(CatalogV2Error, match="duplicate live name"):
        load_catalog_v2(duplicate_live)


@pytest.mark.parametrize(
    ("provenance", "install_argv", "message"),
    [
        ("https://example.com/tool.py", ("tool", "install"), "unsupported provenance"),
        ("pypi:ruff>=0.8", ("tool", "install"), "pinned"),
        ("pypi:ruff==0.8.6", ("tool", "API_TOKEN=secret"), "secret-shaped"),
        ("pypi:ruff==0.8.6", ("tool", "--api-key=sk-test"), "secret-shaped"),
        ("pypi:ruff==0.8.6", ("tool", "&&", "evil"), "shell metacharacter"),
    ],
)
def test_catalog_rejects_unsafe_provenance_and_argv(
    tmp_path: Path,
    provenance: str,
    install_argv: tuple[str, ...],
    message: str,
):
    path = _write_catalog(
        tmp_path / "invalid.toml",
        _tool_block(provenance=provenance, install_argv=install_argv),
    )

    with pytest.raises(CatalogV2Error, match=message):
        load_catalog_v2(path)


def test_catalog_rejects_missing_rollback_and_inconsistent_platform(tmp_path: Path):
    missing_rollback = _write_catalog(
        tmp_path / "missing-rollback.toml",
        _tool_block(include_rollback=False),
    )
    windows_with_posix_binary = _write_catalog(
        tmp_path / "platform.toml",
        _tool_block(platforms=("windows",), install_argv=("/usr/bin/ruff", "install")),
    )

    with pytest.raises(CatalogV2Error, match="rollback"):
        load_catalog_v2(missing_rollback)
    with pytest.raises(CatalogV2Error, match="platform"):
        load_catalog_v2(windows_with_posix_binary)


def test_package_provenance_must_declare_network_use(tmp_path: Path):
    path = _write_catalog(
        tmp_path / "network.toml",
        _tool_block(requires_network=False),
    )

    with pytest.raises(CatalogV2Error, match="declare network"):
        load_catalog_v2(path)


def test_local_override_digest_changes_with_exact_bytes(tmp_path: Path):
    first = _write_catalog(tmp_path / "first.toml", _tool_block())
    second = _write_catalog(
        tmp_path / "second.toml",
        _tool_block().replace("Python linting", "Python linting and formatting"),
    )

    first_catalog = load_catalog_v2(first)
    second_catalog = load_catalog_v2(second)

    assert first_catalog.digest != second_catalog.digest
    assert first_catalog.source == str(first.resolve())
