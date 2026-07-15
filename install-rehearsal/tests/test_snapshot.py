import os
from collections.abc import Iterator
from pathlib import Path

import pytest

import install_rehearsal.snapshot as snapshot_module
from install_rehearsal.snapshot import (
    SnapshotLimitError,
    SnapshotLimits,
    diff_snapshots,
    take_snapshot,
)


def test_path_snapshot_does_not_trust_identityless_directory_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_text("content", encoding="utf-8")

    class IdentitylessEntry:
        name = target.name
        path = str(target)

        def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            raise AssertionError("path snapshot must obtain fresh identity metadata")

    class ScandirResult:
        def __enter__(self) -> Iterator[IdentitylessEntry]:
            return iter((IdentitylessEntry(),))

        def __exit__(self, *_args: object) -> None:
            return None

    def identityless_scandir(_path: object) -> ScandirResult:
        return ScandirResult()

    monkeypatch.setattr(snapshot_module, "_SUPPORTS_DESCRIPTOR_WALK", False)
    monkeypatch.setattr(snapshot_module.os, "scandir", identityless_scandir)

    snapshot = take_snapshot(tmp_path, SnapshotLimits())

    assert snapshot["target"].kind == "file"
    assert snapshot["target"].size == len("content")


def test_delta_classifies_created_modified_and_deleted(tmp_path: Path) -> None:
    deleted = tmp_path / "deleted.txt"
    modified = tmp_path / "modified.txt"
    deleted.write_text("old", encoding="utf-8")
    modified.write_text("old", encoding="utf-8")
    before = take_snapshot(tmp_path, SnapshotLimits())
    deleted.unlink()
    modified.write_text("new", encoding="utf-8")
    (tmp_path / "created.txt").write_text("new", encoding="utf-8")
    after = take_snapshot(tmp_path, SnapshotLimits())

    assert [(item.path, item.change) for item in diff_snapshots(before, after)] == [
        ("created.txt", "created"),
        ("deleted.txt", "deleted"),
        ("modified.txt", "modified"),
    ]


def test_external_symlink_is_recorded_but_not_followed(tmp_path: Path) -> None:
    link = tmp_path / "outside"
    try:
        link.symlink_to(tmp_path.parent)
    except OSError:
        pytest.skip("symlink creation is not available")

    snapshot = take_snapshot(tmp_path, SnapshotLimits())

    assert snapshot["outside"].kind == "symlink"
    assert len(snapshot) == 1


def test_entry_limit_stops_unbounded_walk(tmp_path: Path) -> None:
    (tmp_path / "one").write_text("1", encoding="utf-8")
    (tmp_path / "two").write_text("2", encoding="utf-8")

    with pytest.raises(SnapshotLimitError, match="entry limit"):
        take_snapshot(tmp_path, SnapshotLimits(max_entries=1))


def test_file_and_total_byte_limits_are_enforced(tmp_path: Path) -> None:
    (tmp_path / "large").write_bytes(b"1234")
    with pytest.raises(SnapshotLimitError, match="file size"):
        take_snapshot(tmp_path, SnapshotLimits(max_file_bytes=3))
    with pytest.raises(SnapshotLimitError, match="total byte"):
        take_snapshot(tmp_path, SnapshotLimits(max_total_bytes=3))


def test_snapshot_limits_reject_zero_entries() -> None:
    with pytest.raises(ValueError, match="snapshot limits"):
        SnapshotLimits(max_entries=0)


def test_delta_reports_type_changes(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.write_text("file", encoding="utf-8")
    before = take_snapshot(tmp_path, SnapshotLimits())
    target.unlink()
    target.mkdir()
    after = take_snapshot(tmp_path, SnapshotLimits())

    assert diff_snapshots(before, after)[0].change == "type_changed"


def test_file_swap_to_symlink_is_never_followed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    if os.open not in os.supports_dir_fd or os.scandir not in os.supports_fd:
        pytest.skip("descriptor-relative traversal is not available")
    root = tmp_path / "profile"
    root.mkdir()
    target = root / "target"
    outside = tmp_path / "outside"
    target.write_text("inside", encoding="utf-8")
    outside.write_text("outside-secret", encoding="utf-8")
    original_open = os.open
    swapped = False

    def swapping_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        nonlocal swapped
        if path == "target" and dir_fd is not None and not swapped:
            swapped = True
            target.unlink()
            target.symlink_to(outside)
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", swapping_open)

    with pytest.raises(OSError):
        take_snapshot(root, SnapshotLimits())


def test_growing_file_cannot_exceed_byte_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    target.write_bytes(b"x")
    original_read = os.read
    supplied_growth = False

    def growing_read(descriptor: int, size: int) -> bytes:
        nonlocal supplied_growth
        if not supplied_growth:
            supplied_growth = True
            return b"x" * 10
        return original_read(descriptor, size)

    monkeypatch.setattr(os, "read", growing_read)

    with pytest.raises(SnapshotLimitError, match="total byte"):
        take_snapshot(tmp_path, SnapshotLimits(max_file_bytes=20, max_total_bytes=5))
