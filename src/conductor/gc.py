from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from conductor.config import conductor_home, provider_home
from conductor.errors import ConductorError, ExitCode, StateError
from conductor.ledger import store_path
from conductor.store import Store, validate_identifier


def plan_gc(
    store: Store,
    *,
    keep: int | None,
    older_than_days: float | None,
    now: float | None = None,
) -> tuple[list[str], list[str]]:
    if keep is not None and keep < 0:
        raise ValueError("keep must be nonnegative")
    if older_than_days is not None and older_than_days < 0:
        raise ValueError("older-than-days must be nonnegative")
    run_ids = store.run_ids()
    if older_than_days is not None:
        cutoff = (time.time() if now is None else now) - older_than_days * 86400
        removable = set(store.gc_candidates(older_than=cutoff))
    else:
        protected = set(run_ids[: (20 if keep is None else keep)])
        removable = set(store.gc_candidates(older_than=float("inf"))) - protected
    removed = [run_id for run_id in reversed(run_ids) if run_id in removable]
    kept = [run_id for run_id in run_ids if run_id not in removable]
    return removed, kept


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor gc")
    parser.add_argument("--provider", choices=["codex", "claude"], default="codex")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--keep", type=int, default=20)
    selection.add_argument("--older-than-days", type=float)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="apply the displayed lease-safe deletion plan",
    )
    args = parser.parse_args(argv)
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    path = store_path()
    if not path.exists():
        print(f"gc: no store at {path}")
        return int(ExitCode.SUCCESS)
    try:
        store = Store(path)
        removed, kept = plan_gc(
            store,
            keep=args.keep,
            older_than_days=args.older_than_days,
        )
        for run_id in removed:
            if not args.execute:
                print(f"would remove {run_id}")
                continue
            store.delete_run(run_id)
            _remove_run_directory(conductor_home() / "state", run_id)
            print(f"removed {run_id}")
    except ConductorError as exc:
        print(f"conductor gc: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    except (OSError, ValueError) as exc:
        print(f"conductor gc: {exc}", file=sys.stderr)
        return int(ExitCode.INTERNAL)
    action = "removed" if args.execute else "planned"
    print(
        f"gc: {action} {len(removed)}, kept {len(kept)} (state: {conductor_home() / 'state'})"
    )
    return int(ExitCode.SUCCESS)


def _remove_run_directory(state_root: Path, run_id: str) -> None:
    validate_identifier(run_id, "run_id")
    target = state_root / run_id
    if not target.exists():
        return
    if target.is_symlink() or target.parent != state_root:
        raise StateError(f"unsafe run state path: {target}")
    shutil.rmtree(target)


if __name__ == "__main__":
    raise SystemExit(main())
