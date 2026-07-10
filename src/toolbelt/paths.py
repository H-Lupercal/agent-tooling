from __future__ import annotations

import os
import stat
from hashlib import sha256
from pathlib import Path, PurePosixPath, PureWindowsPath

from toolbelt.errors import ValidationError

_WINDOWS_DEVICES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{index}" for index in range(1, 10)),
        *(f"LPT{index}" for index in range(1, 10)),
    }
)
_REPARSE_POINT = 0x400


class PathViolation(ValidationError):
    """An owned path was ambiguous or escaped its declared repository root."""


def repository_identity(root: str | Path) -> str:
    path = Path(root)
    if path.is_symlink():
        raise PathViolation("repository root must not be a symbolic link")
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
    except OSError as exc:
        raise PathViolation("repository root is unavailable") from exc
    if not stat.S_ISDIR(metadata.st_mode):
        raise PathViolation("repository root must be a directory")
    material = "\0".join(
        (
            os.path.normcase(str(resolved)),
            str(int(getattr(metadata, "st_dev", 0))),
            str(int(getattr(metadata, "st_ino", 0))),
        )
    )
    return sha256(material.encode("utf-8", errors="surrogateescape")).hexdigest()


def resolve_owned_path(
    root: str | Path,
    value: str | os.PathLike[str],
    *,
    expected_root_identity: str | None = None,
) -> Path:
    """Resolve a repository-owned path without following links or reparses."""

    resolved_root = Path(root).resolve(strict=True)
    actual_identity = repository_identity(root)
    if expected_root_identity is not None and actual_identity != expected_root_identity:
        raise PathViolation("repository root identity changed")
    if not isinstance(value, (str, os.PathLike)):
        raise PathViolation("owned path must be text")
    text = os.fspath(value)
    if not isinstance(text, str) or not text or len(text) > 1024 or "\0" in text:
        raise PathViolation("owned path must be nonempty, bounded text without NUL")
    windows = PureWindowsPath(text)
    if windows.is_absolute() or windows.drive or text.startswith(("/", "\\")):
        raise PathViolation("owned path must be repository-relative")
    normalized = text.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or relative == PurePosixPath(".") or ".." in relative.parts:
        raise PathViolation("owned path must not escape the repository")
    for part in relative.parts:
        _validate_component(part)

    current = resolved_root
    for part in relative.parts:
        current = current / part
        try:
            metadata = current.lstat()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise PathViolation(f"cannot inspect owned path component: {part}") from exc
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        if stat.S_ISLNK(metadata.st_mode) or attributes & _REPARSE_POINT:
            raise PathViolation(f"owned path contains a symbolic link or reparse point: {part}")
    try:
        if os.path.commonpath((str(resolved_root), str(current))) != str(resolved_root):
            raise PathViolation("owned path escapes the repository")
    except ValueError as exc:
        raise PathViolation("owned path is on a different volume") from exc
    if repository_identity(root) != actual_identity:
        raise PathViolation("repository root identity changed during path resolution")
    return current


def _validate_component(part: str) -> None:
    if not part or part in {".", ".."}:
        raise PathViolation("owned path contains an empty or relative component")
    if part.endswith((" ", ".")) or ":" in part:
        raise PathViolation("owned path contains a platform-ambiguous component")
    if part.split(".", 1)[0].upper() in _WINDOWS_DEVICES:
        raise PathViolation("owned path contains a reserved device name")
    if any(ord(character) < 32 for character in part):
        raise PathViolation("owned path contains a control character")


__all__ = ["PathViolation", "repository_identity", "resolve_owned_path"]
