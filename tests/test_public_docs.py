from __future__ import annotations

from pathlib import Path

from toolbelt.cli import build_parser

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = (
    "README.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SUPPORT.md",
    "RELEASING.md",
    "CHANGELOG.md",
    "docs/architecture.md",
    "docs/cli.md",
    "docs/catalog-authoring.md",
    "docs/migrating-from-v1.md",
)


def test_public_docs_are_portable_and_truthful() -> None:
    text = "\n".join((ROOT / path).read_text(encoding="utf-8") for path in PUBLIC_DOCS)

    assert "/home/neil" not in text
    assert "guarantees cost savings" not in text.lower()
    assert "standard library only" not in text.lower()
    assert "catalog-v1.toml" not in text
    assert (
        "latest"
        not in (ROOT / "src/toolbelt/data/catalog.toml").read_text(encoding="utf-8").lower()
    )


def test_every_cli_command_is_documented() -> None:
    parser = build_parser()
    root_choices = next(
        action.choices
        for action in parser._actions
        if isinstance(getattr(action, "choices", None), dict)
    )
    commands = set(root_choices)
    commands.remove("catalog")
    commands.add("catalog validate")
    reference = (ROOT / "docs/cli.md").read_text(encoding="utf-8")

    assert commands == {
        "scan",
        "discover",
        "plan",
        "apply",
        "status",
        "doctor",
        "verify",
        "adopt",
        "remove",
        "reconcile",
        "recover",
        "catalog validate",
        "migrate-v1",
    }
    for command in commands:
        assert f"`toolbelt {command}`" in reference


def test_public_governance_and_release_files_exist() -> None:
    for path in PUBLIC_DOCS:
        assert (ROOT / path).is_file(), path
    release = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    assert "id-token: write" in release
    assert "gh-action-pypi-publish" in release
    assert "PYPI_API_TOKEN" not in release
