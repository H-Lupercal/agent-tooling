from __future__ import annotations

import argparse
import os
import shutil
import time
from pathlib import Path

from conductor.config import conductor_home, provider_home


def prune(state_root: Path, keep: int | None, older_than_days: float | None) -> tuple[list[str], list[str]]:
    if not state_root.exists():
        return ([], [])
    run_dirs = sorted(
        (path for path in state_root.iterdir() if path.is_dir()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if older_than_days is not None:
        cutoff = time.time() - older_than_days * 86400
        to_remove = [path for path in run_dirs if path.stat().st_mtime < cutoff]
    else:
        limit = keep if keep is not None else 20
        to_remove = run_dirs[limit:]
    remove_names = {path.name for path in to_remove}
    kept = [path.name for path in run_dirs if path.name not in remove_names]
    return ([path.name for path in to_remove], kept)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor gc")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    parser.add_argument("--keep", type=int, default=20)
    parser.add_argument("--older-than-days", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    state_root = conductor_home() / "state"
    removed, kept = prune(state_root, args.keep, args.older_than_days)
    for name in removed:
        if args.dry_run:
            print(f"would remove {name}")
        else:
            shutil.rmtree(state_root / name, ignore_errors=True)
            print(f"removed {name}")
    print(f"gc: removed {len(removed)}, kept {len(kept)} (state: {state_root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
