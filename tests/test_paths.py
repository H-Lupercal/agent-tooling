from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from hypothesis import given, strategies as st

from toolbelt.paths import PathViolation, repository_identity, resolve_owned_path


@given(value=st.text(max_size=260))
def test_resolve_owned_path_never_escapes(value: str) -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        try:
            result = resolve_owned_path(root, value)
        except PathViolation:
            return
        assert result.is_relative_to(root.resolve())


@pytest.mark.parametrize(
    "value",
    [
        "",
        ".",
        "..",
        "../victim",
        "/tmp/victim",
        "C:\\victim",
        "nested/../../victim",
        "bad\0name",
        "CON",
        "nested/NUL.txt",
        "nested/trailing. ",
    ],
)
def test_unsafe_owned_paths_are_rejected(tmp_path: Path, value: str) -> None:
    with pytest.raises(PathViolation):
        resolve_owned_path(tmp_path, value)


def test_existing_symlink_component_is_rejected(tmp_path: Path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    link = tmp_path / "link"
    try:
        link.symlink_to(victim, target_is_directory=True)
    except (NotImplementedError, OSError):
        pytest.skip("symbolic links are unavailable")

    with pytest.raises(PathViolation, match="symbolic link"):
        resolve_owned_path(tmp_path, "link/file.txt")


def test_root_identity_change_is_rejected(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    identity = repository_identity(root)
    original = tmp_path / "original"
    os.replace(root, original)
    root.mkdir()

    with pytest.raises(PathViolation, match="identity"):
        resolve_owned_path(root, "file.txt", expected_root_identity=identity)
