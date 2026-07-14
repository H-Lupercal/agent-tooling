"""Cross-platform disposable user-profile environment overlays."""

from __future__ import annotations

import ntpath
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Profile:
    root: Path
    environment: Mapping[str, str]
    covered_paths: tuple[str, ...]
    coverage_label: str = "redirected-user-profile"


def windows_home_parts(path: str) -> tuple[str, str]:
    drive, tail = ntpath.splitdrive(path)
    return drive or "C:", tail or "\\"


def build_profile(platform: str, root: Path) -> Profile:
    resolved = root.absolute()
    if platform == "linux":
        environment = {
            "HOME": str(resolved),
            "XDG_CACHE_HOME": str(resolved / ".cache"),
            "XDG_CONFIG_HOME": str(resolved / ".config"),
            "XDG_DATA_HOME": str(resolved / ".local" / "share"),
            "XDG_STATE_HOME": str(resolved / ".local" / "state"),
            "TMPDIR": str(resolved / "tmp"),
        }
    elif platform == "darwin":
        environment = {
            "HOME": str(resolved),
            "TMPDIR": str(resolved / "tmp"),
        }
    elif platform == "win32":
        home_drive, home_path = windows_home_parts(str(resolved))
        environment = {
            "APPDATA": str(resolved / "AppData" / "Roaming"),
            "HOME": str(resolved),
            "HOMEDRIVE": home_drive,
            "HOMEPATH": home_path,
            "LOCALAPPDATA": str(resolved / "AppData" / "Local"),
            "TEMP": str(resolved / "AppData" / "Local" / "Temp"),
            "TMP": str(resolved / "AppData" / "Local" / "Temp"),
            "USERPROFILE": str(resolved),
        }
    else:
        raise ValueError(f"UNSUPPORTED_PLATFORM: {platform}")

    covered_paths = tuple(sorted(set(environment.values())))
    return Profile(root=resolved, environment=environment, covered_paths=covered_paths)
