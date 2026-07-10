from __future__ import annotations

import importlib.metadata
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
PROJECTS = ("toolbelt", "codex-conductor")
REPOSITORY_URL = "https://github.com/H-Lupercal/agent-tooling"
SHA_PIN = re.compile(r"^[0-9a-f]{40}$")
MARKDOWN_LINK = re.compile(r"\[[^]]+\]\((?P<target><[^>]+>|[^\s)]+)")


def _tracked_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / item.decode() for item in result.stdout.split(b"\0") if item]


def _workflow_action_refs(path: Path) -> list[str]:
    refs: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("- uses:"):
            refs.append(stripped.split("@", 1)[1] if "@" in stripped else "")
    return refs


def test_root_release_and_governance_files_exist() -> None:
    required = {
        ".github/CODEOWNERS",
        ".github/dependabot.yml",
        ".github/workflows/ci.yml",
        ".github/workflows/codeql.yml",
        ".github/workflows/release-toolbelt.yml",
        ".github/workflows/release-codex-conductor.yml",
        "AGENTS.md",
        "CODE_OF_CONDUCT.md",
        "CONTRIBUTING.md",
        "LICENSE",
        "README.md",
        "SECURITY.md",
        "SUPPORT.md",
    }
    missing = sorted(path for path in required if not (ROOT / path).is_file())
    assert not missing, f"missing root release files: {missing}"


def test_github_metadata_is_owned_only_by_monorepo_root() -> None:
    nested = [
        path.relative_to(ROOT).as_posix()
        for project in PROJECTS
        for path in (ROOT / project / ".github").rglob("*")
        if path.is_file()
    ]
    assert not nested, f"nested GitHub metadata is inactive in a monorepo: {nested}"


def test_package_urls_target_the_monorepo() -> None:
    for project in PROJECTS:
        with (ROOT / project / "pyproject.toml").open("rb") as handle:
            metadata = tomllib.load(handle)["project"]
        urls = metadata["urls"]
        assert urls
        for label, url in urls.items():
            assert REPOSITORY_URL in url, (
                f"{project} {label} points outside monorepo: {url}"
            )
            assert f"H-Lupercal/{project}" not in url


def test_deleted_repository_urls_are_absent_from_tracked_public_files() -> None:
    stale = ("github.com/H-Lupercal/toolbelt", "github.com/H-Lupercal/codex-conductor")
    findings: list[str] = []
    for path in _tracked_files():
        if not path.is_file():
            continue
        if path.suffix not in {".md", ".toml", ".yml", ".yaml"}:
            continue
        text = path.read_text(encoding="utf-8")
        if any(value in text for value in stale):
            findings.append(path.relative_to(ROOT).as_posix())
    assert not findings, f"deleted repository URLs remain in: {findings}"


def test_release_tags_are_namespaced_and_versions_are_verified() -> None:
    expectations = {
        "release-toolbelt.yml": ("toolbelt-v*", "toolbelt-v"),
        "release-codex-conductor.yml": ("codex-conductor-v*", "codex-conductor-v"),
    }
    workflow_root = ROOT / ".github" / "workflows"
    for filename, (tag_glob, tag_prefix) in expectations.items():
        text = (workflow_root / filename).read_text(encoding="utf-8")
        assert tag_glob in text
        assert tag_prefix in text
        assert "Verify tag matches package version" in text


def test_workflow_actions_are_pinned_to_immutable_commits() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    assert workflows
    unpinned = {
        path.name: [
            ref for ref in _workflow_action_refs(path) if not SHA_PIN.fullmatch(ref)
        ]
        for path in workflows
    }
    unpinned = {name: refs for name, refs in unpinned.items() if refs}
    assert not unpinned, f"workflow actions are not SHA-pinned: {unpinned}"


def test_workflows_apply_release_security_hardening() -> None:
    workflows = sorted((ROOT / ".github" / "workflows").glob("*.yml"))
    for path in workflows:
        text = path.read_text(encoding="utf-8")
        assert "concurrency:" in text, f"{path.name} has no concurrency control"
        assert text.count("persist-credentials: false") == text.count(
            "actions/checkout@"
        ), f"{path.name} persists checkout credentials"

    ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for unsafe in (
        "--check ${{ matrix.",
        "--python ${{ matrix.",
        "--cov=${{ matrix.",
    ):
        assert unsafe not in ci, f"matrix value is interpolated into a shell: {unsafe}"

    dependabot = (ROOT / ".github" / "dependabot.yml").read_text(encoding="utf-8")
    assert dependabot.count("cooldown:") == 3


def test_release_workflows_isolate_pypi_distributions_from_metadata() -> None:
    expectations = {
        "release-toolbelt.yml": "toolbelt",
        "release-codex-conductor.yml": "codex-conductor",
    }
    root = ROOT / ".github" / "workflows"
    for filename, package in expectations.items():
        text = (root / filename).read_text(encoding="utf-8")
        assert "enable-cache: true" not in text
        assert "enable-cache: false" in text
        assert f"name: {package}-pypi-distributions" in text
        assert f"packages-dir: {package}-pypi-dist/" in text
        assert f"name: {package}-release-assets" in text
        assert "skip-existing: true" in text
        assert "gh release view" in text
        assert "gh release upload" in text
        assert "--clobber" in text
        assert "environment build/sbom-venv" in text
        assert "scripts/finalize_sbom.py" in text


def test_ci_targets_both_project_directories_and_unique_artifacts() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for project in PROJECTS:
        assert project in text
    assert "${{ matrix.project }}/uv.lock" in text
    assert "codex-conductor/uv.lock" in text
    assert "${{ matrix.project }}-coverage" in text
    assert "${{ matrix.project }}-distributions" in text
    assert "${{ matrix.project }}-sbom" in text
    assert "--cov-fail-under=90" in text
    assert text.count("environment build/sbom-venv") == 1
    assert text.count("scripts/finalize_sbom.py") == 1


def test_local_coverage_release_floor_is_ninety_percent() -> None:
    for project in PROJECTS:
        with (ROOT / project / "pyproject.toml").open("rb") as handle:
            config = tomllib.load(handle)
        assert config["tool"]["coverage"]["report"]["fail_under"] == 90
        makefile = (ROOT / project / "Makefile").read_text(encoding="utf-8")
        assert "--cov-fail-under=90" in makefile


def test_local_release_gates_cover_artifacts_e2e_audit_and_sbom() -> None:
    required = (
        "twine check dist/*.whl dist/*.tar.gz",
        "pytest -m distribution",
        "e2e_smoke.sh",
        "pip_audit",
        "cyclonedx_py",
    )
    for project in PROJECTS:
        makefile = (ROOT / project / "Makefile").read_text(encoding="utf-8")
        for command in required:
            assert command in makefile, f"{project} release gate is missing {command}"
        assert "environment build/sbom-venv" in makefile
        assert "scripts/finalize_sbom.py" in makefile
        release_target = next(
            line for line in makefile.splitlines() if line.startswith("release-check:")
        )
        assert "sbom" in release_target


def test_sbom_finalizers_stamp_the_installed_distribution_version(
    tmp_path: Path,
) -> None:
    expected = importlib.metadata.version("codex-conductor")
    for project in PROJECTS:
        sbom = tmp_path / f"{project}.cdx.json"
        sbom.write_text(
            json.dumps(
                {
                    "bomFormat": "CycloneDX",
                    "metadata": {"component": {"name": "codex-conductor"}},
                }
            ),
            encoding="utf-8",
        )
        result = subprocess.run(
            [
                sys.executable,
                str(ROOT / project / "scripts" / "finalize_sbom.py"),
                "--input",
                str(sbom),
                "--distribution",
                "codex-conductor",
            ],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(sbom.read_text(encoding="utf-8"))
        assert payload["metadata"]["component"]["version"] == expected


def test_lockfiles_are_tracked_for_both_projects() -> None:
    tracked = {path.relative_to(ROOT).as_posix() for path in _tracked_files()}
    assert {f"{project}/uv.lock" for project in PROJECTS} <= tracked


def test_relative_links_in_public_markdown_resolve() -> None:
    broken: list[str] = []
    for path in _tracked_files():
        if path.suffix.lower() != ".md" or not path.is_file():
            continue
        for match in MARKDOWN_LINK.finditer(path.read_text(encoding="utf-8")):
            raw = match.group("target").strip("<>")
            parsed = urlsplit(raw)
            if raw.startswith("#") or parsed.scheme or parsed.netloc:
                continue
            target = unquote(parsed.path)
            if not target:
                continue
            resolved = (
                (ROOT / target.lstrip("/"))
                if target.startswith("/")
                else (path.parent / target)
            )
            if not resolved.exists():
                broken.append(f"{path.relative_to(ROOT)} -> {raw}")
    assert not broken, "broken relative Markdown links: " + ", ".join(broken)
