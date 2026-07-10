from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
from pathlib import Path


def finalize(path: Path, distribution: str) -> None:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("SBOM root must be a JSON object")
    metadata = payload.get("metadata")
    component = metadata.get("component") if isinstance(metadata, dict) else None
    if not isinstance(component, dict) or component.get("name") != distribution:
        raise ValueError(f"SBOM main component does not match {distribution!r}")

    version = importlib.metadata.version(distribution)
    if not version:
        raise ValueError(f"installed distribution {distribution!r} has no version")
    component["version"] = version

    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--distribution", required=True)
    args = parser.parse_args(argv)
    finalize(args.input, args.distribution)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
