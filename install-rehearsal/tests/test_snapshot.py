from pathlib import Path

import pytest

from install_rehearsal.snapshot import SnapshotLimitError, SnapshotLimits, diff_snapshots, take_snapshot


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

