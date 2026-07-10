"""Canonical v2 state paths.

The v1 JSONL/event-ledger API was intentionally removed. Runtime truth lives in
the SQLite store; this module only centralizes paths used by hooks and commands.
"""

from __future__ import annotations

from pathlib import Path

from conductor.config import conductor_home


def store_path() -> Path:
    return conductor_home() / "state" / "conductor.db"


def run_state_dir(run_id: str) -> Path:
    from conductor.store import validate_identifier

    validate_identifier(run_id, "run_id")
    return conductor_home() / "state" / run_id
