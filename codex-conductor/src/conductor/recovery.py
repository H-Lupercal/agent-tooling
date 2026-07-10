from __future__ import annotations

import argparse
import json
import os
import sys

from conductor.config import provider_home
from conductor.errors import ConductorError, ExitCode, StateError
from conductor.ledger import store_path
from conductor.store import Store


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="conductor recover")
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    parser.add_argument("--run")
    parser.add_argument("--reservation")
    parser.add_argument("--outcome", choices=("cancelled", "failed", "expired"))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    if (args.reservation is None) != (args.outcome is None):
        parser.error("--reservation and --outcome must be supplied together")
    os.environ.setdefault("CODEX_CONDUCTOR_HOME", str(provider_home(args.provider)))
    try:
        path = store_path()
        if not path.exists():
            raise StateError(f"conductor store does not exist: {path}")
        store = Store(path)
        run_id = args.run or store.latest_run_id()
        if run_id is None:
            raise StateError("no conductor runs exist")
        if args.reservation is not None:
            resolved = store.resolve_recovery(
                args.reservation, run_id=run_id, outcome=args.outcome
            )
            payload = {
                "schema_version": 1,
                "run_id": run_id,
                "resolved": resolved.model_dump(mode="json"),
            }
        else:
            payload = {
                "schema_version": 1,
                "run_id": run_id,
                "recoverable": [
                    item.model_dump(mode="json")
                    for item in store.recoverable_reservations(run_id=run_id)
                ],
            }
    except ConductorError as exc:
        print(f"conductor recover: {exc}", file=sys.stderr)
        return int(exc.exit_code)
    output = json.dumps(payload, indent=2, sort_keys=True)
    print(output)
    return int(ExitCode.SUCCESS)


if __name__ == "__main__":
    raise SystemExit(main())
