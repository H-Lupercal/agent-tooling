"""Cross-platform disposable user-profile environment overlays."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True)
class Profile:
    root: Path
    environment: Mapping[str, str]
    covered_paths: tuple[str, ...]
    coverage_label: str = "redirected-user-profile"


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
        environment = {
            "APPDATA": str(resolved / "AppData" / "Roaming"),
            "HOME": str(resolved),
            "HOMEDRIVE": resolved.drive or "C:",
            "HOMEPATH": str(resolved),
            "LOCALAPPDATA": str(resolved / "AppData" / "Local"),
            "TEMP": str(resolved / "AppData" / "Local" / "Temp"),
            "TMP": str(resolved / "AppData" / "Local" / "Temp"),
            "USERPROFILE": str(resolved),
        }
    else:
        raise ValueError(f"UNSUPPORTED_PLATFORM: {platform}")

    covered_paths = tuple(sorted(set(environment.values())))
    return Profile(root=resolved, environment=environment, covered_paths=covered_paths)

