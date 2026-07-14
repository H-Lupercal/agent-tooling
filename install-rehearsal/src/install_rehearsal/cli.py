"""Command-line orchestration for disposable installer rehearsals."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import os
from pathlib import Path
import secrets
import shutil
import sys
import tempfile
from typing import Sequence

from install_rehearsal import __version__
from install_rehearsal.models import Coverage, Receipt
from install_rehearsal.profiles import Profile, build_profile
from install_rehearsal.redaction import build_child_environment, redact_argv
from install_rehearsal.reporting import render_comparison, render_receipt
from install_rehearsal.runner import RunLimits, run_command
from install_rehearsal.snapshot import SnapshotLimits, diff_snapshots, take_snapshot
from install_rehearsal.store import ReceiptStore

TOOL_ERROR = 3
INSTALLER_FAILED = 10


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install-rehearsal",
        description="Observe a trusted installer in a redirected disposable user profile.",
    )
    parser.add_argument(
        "--store",
        type=Path,
        default=Path.home() / ".install-rehearsal",
        help="receipt store (default: %(default)s)",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="rehearse an installer command")
    run.add_argument("--json", action="store_true", help="emit the canonical receipt JSON")
    run.add_argument("--keep-profile", action="store_true", help="retain the disposable profile")
    run.add_argument("--timeout", type=float, default=120.0, help="child timeout in seconds")
    run.add_argument("--output-bytes", type=int, default=64 * 1024)
    run.add_argument("installer_argv", nargs=argparse.REMAINDER, metavar="COMMAND")

    show = subparsers.add_parser("show", help="display a stored receipt")
    show.add_argument("run_id", help="run ID or 'latest'")
    show.add_argument("--json", action="store_true", help="emit canonical JSON")

    compare = subparsers.add_parser("compare", help="compare two stored receipts")
    compare.add_argument("first")
    compare.add_argument("second")
    return parser


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{stamp}-{secrets.token_hex(4)}"


def _prepare_profile(profile: Profile) -> None:
    profile.root.mkdir(parents=True, exist_ok=True)
    for value in profile.environment.values():
        candidate = Path(value)
        try:
            candidate.relative_to(profile.root)
        except ValueError:
            continue
        candidate.mkdir(parents=True, exist_ok=True)


def _covered_paths(profile: Profile) -> tuple[str, ...]:
    values: set[str] = set()
    for value in profile.covered_paths:
        candidate = Path(value)
        try:
            relative = candidate.relative_to(profile.root)
        except ValueError:
            continue
        values.add("<DISPOSABLE_PROFILE>" if relative == Path(".") else relative.as_posix())
    return tuple(sorted(values))


def _resolve_executable(command: str, environment: dict[str, str]) -> Path | None:
    candidate = Path(command)
    if candidate.is_absolute() or candidate.parent != Path("."):
        return candidate.resolve() if candidate.is_file() else None
    discovered = shutil.which(command, path=environment.get("PATH"))
    return Path(discovered).resolve() if discovered else None


def _sha256_file(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(store: ReceiptStore, args: argparse.Namespace) -> int:
    caller_directory = Path.cwd()
    installer_argv = tuple(str(item) for item in args.installer_argv)
    if installer_argv and installer_argv[0] == "--":
        installer_argv = installer_argv[1:]
    if not installer_argv:
        raise ValueError("run requires '-- COMMAND [ARG ...]'")

    run_id = _new_run_id()
    profiles_dir = store.root / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_root = Path(tempfile.mkdtemp(prefix=f"{run_id}-", dir=profiles_dir))
    profile = build_profile(sys.platform, profile_root)
    _prepare_profile(profile)
    store.mark_active(run_id, profile_root)

    child_environment = build_child_environment(os.environ, profile.environment)
    inherited_keys = tuple(sorted(set(child_environment) - set(profile.environment)))
    started_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    before = take_snapshot(profile.root, SnapshotLimits())
    result = run_command(
        installer_argv,
        cwd=caller_directory,
        environment=child_environment,
        limits=RunLimits(timeout_seconds=args.timeout, output_bytes=args.output_bytes),
    )
    after = take_snapshot(profile.root, SnapshotLimits())
    executable = _resolve_executable(installer_argv[0], child_environment)
    receipt = Receipt(
        schema_version=1,
        run_id=run_id,
        trust_label="REHEARSAL_NOT_SANDBOXED",
        started_at=started_at,
        platform=sys.platform,
        tool_version=__version__,
        argv=redact_argv(installer_argv),
        executable_path=str(executable) if executable else None,
        executable_sha256=_sha256_file(executable),
        inherited_environment_keys=inherited_keys,
        run=result,
        coverage=Coverage(
            profile_root="<DISPOSABLE_PROFILE>",
            covered_paths=_covered_paths(profile),
            limitations=(
                "trusted installer only; this is not a security sandbox",
                "writes outside redirected user-profile paths are not observed",
                "network and system-wide effects are not isolated",
            ),
        ),
        filesystem_delta=diff_snapshots(before, after),
        warnings=("REHEARSAL_NOT_SANDBOXED",),
    )
    store.write(receipt)

    if not args.keep_profile:
        shutil.rmtree(profile_root)
        store.clear_active(run_id)
    sys.stdout.write(render_receipt(receipt, as_json=bool(args.json)))
    return 0 if result.termination_reason == "exited" and result.exit_code == 0 else INSTALLER_FAILED


def _show(store: ReceiptStore, args: argparse.Namespace) -> int:
    receipt = store.latest() if args.run_id == "latest" else store.load(str(args.run_id))
    sys.stdout.write(render_receipt(receipt, as_json=bool(args.json)))
    return 0


def _compare(store: ReceiptStore, args: argparse.Namespace) -> int:
    output, different = render_comparison(store.load(str(args.first)), store.load(str(args.second)))
    sys.stdout.write(output)
    return 1 if different else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    store = ReceiptStore(args.store)
    try:
        if args.command == "run":
            return _run(store, args)
        if args.command == "show":
            return _show(store, args)
        if args.command == "compare":
            return _compare(store, args)
    except (OSError, ValueError, KeyError) as exc:
        print(f"install-rehearsal: {exc}", file=sys.stderr)
        return TOOL_ERROR
    raise AssertionError(f"unhandled command: {args.command}")
