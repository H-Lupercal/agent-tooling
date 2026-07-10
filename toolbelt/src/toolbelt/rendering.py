from __future__ import annotations

import json
from typing import Any


def response(command: str, data: dict[str, Any], *, ok: bool = True) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "command": command,
        "ok": ok,
        "data": data,
    }


def error_response(
    command: str,
    *,
    code: str,
    message: str,
    exit_code: int,
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "command": command,
        "ok": False,
        "error": {
            "code": code,
            "message": message,
            "exit_code": exit_code,
        },
    }


def emit_json(value: dict[str, Any]) -> None:
    print(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    )


__all__ = ["emit_json", "error_response", "response"]
