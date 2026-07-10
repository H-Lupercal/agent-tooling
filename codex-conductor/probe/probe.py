from __future__ import annotations

import argparse
import json
from pathlib import Path

from conductor.capabilities import contract_digest, contract_mode, load_contract
from conductor.doctor import run_checks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Probe installed provider contracts without launching model work"
    )
    parser.add_argument("--provider", choices=("codex", "claude"), default="codex")
    parser.add_argument("--home", type=Path)
    args = parser.parse_args(argv)
    contract = load_contract(f"{args.provider}-current")
    report = run_checks(args.provider, home=args.home)
    payload = {
        "schema_version": 1,
        "provider": args.provider,
        "contract": contract.contract_name,
        "contract_digest": contract_digest(contract),
        "mode": contract_mode(contract).value,
        "doctor": report,
        "model_work_launched": False,
    }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
