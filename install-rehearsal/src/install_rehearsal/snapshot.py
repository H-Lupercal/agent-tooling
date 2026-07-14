"""Bounded, symlink-safe snapshots of a disposable profile."""

from __future__ import annotations

import hashlib
import os
import stat
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from install_rehearsal.models import FileDelta, FileState

_SUPPORTS_DESCRIPTOR_WALK = os.open in os.supports_dir_fd and os.scandir in os.supports_fd
_WINDOWS_REPARSE_POINT = 0x00000400


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


@dataclass
class _Budget:
    limits: SnapshotLimits
    entries: int = 0
    total_bytes: int = 0

    def add_entry(self) -> None:
        if self.entries >= self.limits.max_entries:
            raise SnapshotLimitError("entry limit exceeded")
        self.entries += 1

    def check_file_size(self, size: int, name: str) -> None:
        if size > self.limits.max_file_bytes:
            raise SnapshotLimitError(f"file size limit exceeded: {name}")

    def add_file_bytes(self, size: int) -> None:
        if self.total_bytes + size > self.limits.max_total_bytes:
            raise SnapshotLimitError("total byte limit exceeded")
        self.total_bytes += size


def _redact_symlink_target(target: str) -> str:
    if os.path.isabs(target):
        return "<ABSOLUTE_TARGET>"
    return target


def _same_identity(first: os.stat_result, second: os.stat_result) -> bool:
    return first.st_dev == second.st_dev and first.st_ino == second.st_ino


def _is_reparse_point(metadata: os.stat_result) -> bool:
    return bool(getattr(metadata, "st_file_attributes", 0) & _WINDOWS_REPARSE_POINT)


def _hash_open_file(
    descriptor: int, expected: os.stat_result, relative: str, budget: _Budget
) -> FileState:
    actual = os.fstat(descriptor)
    if not stat.S_ISREG(actual.st_mode) or not _same_identity(expected, actual):
        raise OSError(f"profile entry changed while snapshotting: {relative}")
    budget.check_file_size(actual.st_size, relative)
    digest = hashlib.sha256()
    observed_size = 0
    while chunk := os.read(descriptor, 1024 * 1024):
        observed_size += len(chunk)
        budget.check_file_size(observed_size, relative)
        budget.add_file_bytes(len(chunk))
        digest.update(chunk)
    final = os.fstat(descriptor)
    if not _same_identity(actual, final) or final.st_size != observed_size:
        raise OSError(f"profile file changed while snapshotting: {relative}")
    return FileState(
        "file",
        observed_size,
        digest.hexdigest(),
        stat.S_IMODE(actual.st_mode),
        None,
    )


def _open_flags(*, directory: bool) -> int:
    flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    if directory:
        flags |= getattr(os, "O_DIRECTORY", 0)
    else:
        flags |= getattr(os, "O_NONBLOCK", 0)
    return flags


def _walk_descriptor(
    directory_descriptor: int,
    prefix: str,
    snapshot: dict[str, FileState],
    budget: _Budget,
) -> None:
    with os.scandir(directory_descriptor) as iterator:
        entries = sorted(iterator, key=lambda item: item.name)
        for entry in entries:
            relative = f"{prefix}/{entry.name}" if prefix else entry.name
            budget.add_entry()
            metadata = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            if stat.S_ISLNK(metadata.st_mode):
                target = _redact_symlink_target(
                    os.readlink(entry.name, dir_fd=directory_descriptor)
                )
                snapshot[relative] = FileState("symlink", len(target.encode()), None, mode, target)
            elif stat.S_ISDIR(metadata.st_mode):
                child_descriptor = os.open(
                    entry.name,
                    _open_flags(directory=True),
                    dir_fd=directory_descriptor,
                )
                try:
                    actual = os.fstat(child_descriptor)
                    if not stat.S_ISDIR(actual.st_mode) or not _same_identity(metadata, actual):
                        raise OSError(f"profile directory changed while snapshotting: {relative}")
                    snapshot[relative] = FileState("directory", 0, None, mode, None)
                    _walk_descriptor(child_descriptor, relative, snapshot, budget)
                finally:
                    os.close(child_descriptor)
            elif stat.S_ISREG(metadata.st_mode):
                descriptor = os.open(
                    entry.name,
                    _open_flags(directory=False),
                    dir_fd=directory_descriptor,
                )
                try:
                    snapshot[relative] = _hash_open_file(descriptor, metadata, relative, budget)
                finally:
                    os.close(descriptor)
            else:
                snapshot[relative] = FileState("other", 0, None, mode, None)


def _take_descriptor_snapshot(root: Path, limits: SnapshotLimits) -> dict[str, FileState]:
    root_descriptor = os.open(root, _open_flags(directory=True))
    snapshot: dict[str, FileState] = {}
    try:
        _walk_descriptor(root_descriptor, "", snapshot, _Budget(limits))
    finally:
        os.close(root_descriptor)
    return dict(sorted(snapshot.items()))


def _take_path_snapshot(
    root: Path, limits: SnapshotLimits
) -> dict[str, FileState]:  # pragma: no cover - executed by Windows CI
    """Windows fallback after the runner has quiesced its Job Object."""
    snapshot: dict[str, FileState] = {}
    budget = _Budget(limits)
    stack = [(root, os.stat(root, follow_symlinks=False))]
    while stack:
        directory, expected_directory = stack.pop()
        current_directory = os.stat(directory, follow_symlinks=False)
        if (
            _is_reparse_point(current_directory)
            or not stat.S_ISDIR(current_directory.st_mode)
            or not _same_identity(expected_directory, current_directory)
        ):
            raise OSError(f"profile directory changed while snapshotting: {directory.name}")
        with os.scandir(directory) as iterator:
            entries = sorted(iterator, key=lambda item: item.name, reverse=True)
        final_directory = os.stat(directory, follow_symlinks=False)
        if _is_reparse_point(final_directory) or not _same_identity(
            current_directory, final_directory
        ):
            raise OSError(f"profile directory changed while snapshotting: {directory.name}")
        for entry in entries:
            relative = Path(entry.path).relative_to(root).as_posix()
            budget.add_entry()
            metadata = entry.stat(follow_symlinks=False)
            mode = stat.S_IMODE(metadata.st_mode)
            path = Path(entry.path)
            if _is_reparse_point(metadata):
                target = "<REPARSE_POINT>"
                state = FileState("symlink", len(target), None, mode, target)
            elif stat.S_ISLNK(metadata.st_mode):
                target = _redact_symlink_target(os.readlink(path))
                state = FileState("symlink", len(target.encode()), None, mode, target)
            elif stat.S_ISDIR(metadata.st_mode):
                state = FileState("directory", 0, None, mode, None)
                stack.append((path, metadata))
            elif stat.S_ISREG(metadata.st_mode):
                descriptor = os.open(path, _open_flags(directory=False))
                try:
                    state = _hash_open_file(descriptor, metadata, relative, budget)
                finally:
                    os.close(descriptor)
            else:
                state = FileState("other", 0, None, mode, None)
            snapshot[relative] = state
    return dict(sorted(snapshot.items()))


def take_snapshot(root: Path, limits: SnapshotLimits) -> dict[str, FileState]:
    """Snapshot root without following symlinks or leaving configured bounds."""
    if _SUPPORTS_DESCRIPTOR_WALK:
        return _take_descriptor_snapshot(root, limits)
    return _take_path_snapshot(root, limits)  # pragma: no cover - executed by Windows CI


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
