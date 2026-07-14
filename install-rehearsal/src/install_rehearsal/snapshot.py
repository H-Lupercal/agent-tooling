"""Bounded, symlink-safe snapshots of a disposable profile."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import stat
from typing import Mapping

from install_rehearsal.models import FileDelta, FileState


class SnapshotLimitError(RuntimeError):
    """The profile exceeded an explicitly configured snapshot bound."""


@dataclass(frozen=True)
class SnapshotLimits:
    max_entries: int = 10_000
    max_file_bytes: int = 32 * 1024 * 1024
    max_total_bytes: int = 128 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.max_entries < 1 or self.max_file_bytes < 0 or self.max_total_bytes < 0:
            raise ValueError("snapshot limits must be non-negative and allow at least one entry")


def _hash_file(path: Path, limits: SnapshotLimits, total_bytes: int) -> tuple[str, int]:
    size = path.stat(follow_symlinks=False).st_size
    if size > limits.max_file_bytes:
        raise SnapshotLimitError(f"file size limit exceeded: {path.name}")
    if total_bytes + size > limits.max_total_bytes:
        raise SnapshotLimitError("total byte limit exceeded")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest(), total_bytes + size


def _redact_symlink_target(target: str) -> str:
    if os.path.isabs(target):
        return "<ABSOLUTE_TARGET>"
    return target


def take_snapshot(root: Path, limits: SnapshotLimits) -> dict[str, FileState]:
    """Snapshot root without following symlinks or leaving configured bounds."""
    snapshot: dict[str, FileState] = {}
    total_bytes = 0
    stack = [root]
    while stack:
        directory = stack.pop()
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name, reverse=True)
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            if len(snapshot) >= limits.max_entries:
                raise SnapshotLimitError("entry limit exceeded")
            metadata = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            path = Path(entry.path)
            if entry.is_symlink():
                target = _redact_symlink_target(os.readlink(path))
                state = FileState("symlink", len(target.encode()), None, mode, target)
            elif entry.is_dir(follow_symlinks=False):
                state = FileState("directory", 0, None, mode, None)
                stack.append(path)
            elif entry.is_file(follow_symlinks=False):
                digest, total_bytes = _hash_file(path, limits, total_bytes)
                state = FileState("file", metadata.st_size, digest, mode, None)
            else:
                state = FileState("other", 0, None, mode, None)
            snapshot[relative] = state
    return dict(sorted(snapshot.items()))


def diff_snapshots(
    before: Mapping[str, FileState], after: Mapping[str, FileState]
) -> tuple[FileDelta, ...]:
    deltas: list[FileDelta] = []
    for path in sorted(before.keys() | after.keys()):
        previous = before.get(path)
        current = after.get(path)
        if previous == current:
            continue
        if previous is None:
            change = "created"
        elif current is None:
            change = "deleted"
        elif previous.kind != current.kind:
            change = "type_changed"
        else:
            change = "modified"
        deltas.append(FileDelta(path, change, previous, current))  # type: ignore[arg-type]
    return tuple(deltas)

