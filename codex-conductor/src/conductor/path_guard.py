from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

_FILE_ATTRIBUTE_REPARSE_POINT = 0x400


def is_unsafe_path_redirect(path: Path, metadata: Any) -> bool:
    """Reject mutable redirects while permitting trusted POSIX system aliases."""

    if bool(getattr(metadata, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT):
        return True
    if not path.is_symlink():
        return False
    if os.name == "nt" or getattr(metadata, "st_uid", None) != 0:
        return True
    try:
        parent_metadata = path.parent.stat()
    except OSError:
        return True
    writable_by_non_root = bool(parent_metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH))
    return getattr(parent_metadata, "st_uid", None) != 0 or writable_by_non_root
