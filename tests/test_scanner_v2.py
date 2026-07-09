from __future__ import annotations

import os
import shutil
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace

import pytest

from toolbelt.evidence import scan_v2
from toolbelt.ignore import IgnoreRules
from toolbelt.scanner import ScanLimits, scan_repository


def _write(path: Path, content: str = "") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _snapshot_tree(root: Path) -> tuple[tuple[str, str, bytes | str | None], ...]:
    entries: list[tuple[str, str, bytes | str | None]] = []
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            entries.append((relative, "symlink", os.readlink(path)))
        elif path.is_file():
            entries.append((relative, "file", path.read_bytes()))
        else:
            entries.append((relative, "directory", None))
    return tuple(entries)


def _build_noisy_repo(root: Path) -> Path:
    _write(root / ".github/workflows/ci.yml", "name: ci\n")
    _write(root / "src/app.py", "print('safe')\n")
    _write(root / "tests/fixtures/noisy/Dockerfile", "FROM scratch\n")
    _write(root / "node_modules/pkg/Dockerfile", "FROM scratch\n")
    _write(root / "dist/Dockerfile", "FROM scratch\n")
    _write(root / "bundle.min.js", "generated()\n")
    _write(root / "ignored/Dockerfile", "FROM scratch\n")
    _write(root / "secret.tf", 'resource "x" "y" {}\n')
    _write(root / ".gitignore", "ignored/\n")
    _write(root / ".toolbeltignore", "secret.tf\n")
    return root


def test_scan_is_pure_and_ignores_fixtures_vendor_and_generated(tmp_path: Path):
    repo = _build_noisy_repo(tmp_path / "repo")
    before = _snapshot_tree(repo)
    result = scan_repository(repo)
    after = _snapshot_tree(repo)

    assert before == after
    assert {item.key for item in result if item.type == "infra"} == {"github_actions"}
    assert all("fixtures" not in item.source for item in result)
    assert all("node_modules" not in item.source for item in result)
    assert all("dist" not in item.source for item in result)
    assert not (repo / ".toolbelt").exists()


def test_scan_does_not_follow_symlink_outside_root(tmp_path: Path):
    repo = tmp_path / "repo"
    outside = tmp_path / "outside"
    _write(outside / "Dockerfile", "FROM scratch\n")
    repo.mkdir()
    try:
        (repo / "outside-link").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    result = scan_repository(repo)

    assert not [item for item in result if item.key == "dockerfile"]
    assert all("outside-link" not in item.source for item in result)
    assert any(warning.code == "symlink_skipped" for warning in result.warnings)


def test_nested_gitignore_and_toolbeltignore_rules_are_honored(tmp_path: Path):
    repo = tmp_path / "repo"
    _write(repo / ".gitignore", "ignored/\n")
    _write(repo / ".toolbeltignore", "secret.tf\n")
    _write(repo / "ignored/Dockerfile", "FROM scratch\n")
    _write(repo / "secret.tf", 'resource "x" "y" {}\n')
    _write(repo / "services/.gitignore", "*.tf\n!important.tf\n")
    _write(repo / "services/drop.tf", 'resource "x" "y" {}\n')
    _write(repo / "services/important.tf", 'resource "x" "y" {}\n')

    terraform_sources = {
        item.source
        for item in scan_repository(repo)
        if item.type == "infra" and item.key == "terraform"
    }

    assert terraform_sources == {"services/important.tf"}


def test_test_fixtures_can_be_opted_back_in(tmp_path: Path):
    fixture = Path(__file__).parent / "fixtures/repos/ignored_noise"
    repo = tmp_path / "repo"
    shutil.copytree(fixture, repo)
    _write(repo / "ignored/Dockerfile", "FROM scratch\n")
    _write(repo / "tests/fixtures/demo/Dockerfile", "FROM scratch\n")

    default = scan_repository(repo)
    included = scan_repository(repo, include_fixtures=True)

    assert not [item for item in default if item.key == "dockerfile"]
    assert {item.source for item in included if item.key == "dockerfile"} == {
        "tests/fixtures/demo/Dockerfile"
    }


def test_malformed_manifests_produce_bounded_relative_warnings(tmp_path: Path):
    repo = tmp_path / "repo"
    _write(repo / "package.json", "{not json")
    repo.mkdir(exist_ok=True)
    (repo / "pyproject.toml").write_bytes(b"\xff\xfe")

    result = scan_repository(repo, limits=ScanLimits(max_warnings=2))

    assert {item.source for item in result if item.type == "manifest"} == {
        "package.json",
        "pyproject.toml",
    }
    assert len(result.warnings) == 2
    assert {warning.source for warning in result.warnings} == {
        "package.json",
        "pyproject.toml",
    }
    assert all(not warning.source.startswith("/") for warning in result.warnings)


def test_scan_result_is_sorted_immutable_and_v1_bridge_is_pure(tmp_path: Path):
    repo = tmp_path / "repo"
    _write(repo / "z.py", "")
    _write(repo / "Dockerfile", "FROM scratch\n")
    _write(repo / "a.py", "")

    result = scan_repository(repo)

    assert result == scan_repository(repo)
    assert result == scan_v2(repo)
    assert isinstance(result.evidence, tuple)
    assert result.evidence == tuple(
        sorted(
            result.evidence,
            key=lambda item: (item.type, item.key, item.source, item.detail),
        )
    )
    with pytest.raises(AttributeError):
        result.evidence = ()


def test_depth_and_byte_limits_stop_before_unbounded_reads(tmp_path: Path):
    repo = tmp_path / "repo"
    _write(repo / "deep/nested/app.py", "print('too deep')\n")
    depth_limited = scan_repository(repo, limits=ScanLimits(max_depth=1))
    assert any(warning.code == "depth_limit" for warning in depth_limited.warnings)
    assert not list(depth_limited)

    _write(repo / "Dockerfile", "FROM scratch\n")
    byte_limited = scan_repository(repo, limits=ScanLimits(max_bytes=1))
    assert any(warning.code == "byte_limit" for warning in byte_limited.warnings)
    assert byte_limited.bytes_scanned <= 1


def test_fixed_cache_and_generated_exclusions_are_fail_closed(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    rules = IgnoreRules.from_root(repo)

    for source in (".cache/Dockerfile", "public/app.js.map", "coverage.xml"):
        assert rules.is_ignored(PurePosixPath(source), is_directory=False)


@pytest.mark.parametrize(
    "field",
    ["max_files", "max_depth", "max_bytes", "max_warnings"],
)
def test_scan_limits_reject_negative_bounds(field: str):
    values = {
        "max_files": 1,
        "max_depth": 1,
        "max_bytes": 1,
        "max_warnings": 1,
    }
    values[field] = -1
    with pytest.raises(ValueError, match=field):
        ScanLimits(**values)


def test_100k_entry_scan_respects_limits(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    repo = tmp_path / "repo"
    repo.mkdir()
    consumed = 0

    class FakeEntry:
        def __init__(self, number: int):
            self.name = f"file-{number:06d}.py"
            self.path = str(repo / self.name)

        def is_symlink(self) -> bool:
            return False

        def is_dir(self, *, follow_symlinks: bool = True) -> bool:
            return False

        def is_file(self, *, follow_symlinks: bool = True) -> bool:
            return True

        def stat(self, *, follow_symlinks: bool = True) -> SimpleNamespace:
            return SimpleNamespace(st_size=1)

    class FakeScandir:
        def __iter__(self):
            nonlocal consumed
            for number in range(100_000):
                consumed += 1
                yield FakeEntry(number)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr("toolbelt.scanner.os.scandir", lambda _path: FakeScandir())

    started = time.perf_counter()
    result = scan_repository(repo, limits=ScanLimits(max_files=50, max_bytes=1000))
    elapsed = time.perf_counter() - started

    assert result.files_scanned == 50
    assert consumed <= 51
    assert any(warning.code == "file_limit" for warning in result.warnings)
    assert elapsed < 5
