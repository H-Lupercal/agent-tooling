from __future__ import annotations

import datetime as _dt
import json
import sys
from pathlib import Path

from conductor.config import conductor_home


def read_payload() -> dict:
    raw = sys.stdin.read()
    if not raw.strip():
        return {}
    value = json.loads(raw)
    return value if isinstance(value, dict) else {}


def write_json(value: dict) -> None:
    sys.stdout.write(json.dumps(value) + "\n")


def log_error(hook_name: str, exc: BaseException) -> None:
    try:
        state = conductor_home() / "state"
        state.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now(_dt.UTC).isoformat()
        with (state / "errors.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{stamp}\t{hook_name}\t{exc!r}\n")
    except OSError:
        pass
