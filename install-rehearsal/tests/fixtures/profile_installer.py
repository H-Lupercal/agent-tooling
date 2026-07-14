"""Deterministic trusted-installer fixture used by end-to-end tests."""

from __future__ import annotations

import os
from pathlib import Path


def main() -> int:
    home = Path(os.environ["HOME"])
    if "APPDATA" in os.environ:
        config_root = Path(os.environ["APPDATA"])
    else:
        config_root = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config"))
    target = config_root / "example" / "config.toml"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text('enabled = true\n', encoding="utf-8")
    print(f"configured {target.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

