"""Atomic local receipt persistence and abandoned-profile markers."""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from install_rehearsal.models import Receipt, receipt_from_dict, receipt_to_json, validate_run_id


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        if os.name != "nt":
            directory_descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
    finally:
        temporary.unlink(missing_ok=True)


class ReceiptStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.receipts = root / "receipts"
        self.active = root / "active"

    def write(self, receipt: Receipt) -> Path:
        target = self.receipts / f"{receipt.run_id}.json"
        _atomic_write(target, receipt_to_json(receipt))
        return target

    def load(self, run_id: str) -> Receipt:
        validate_run_id(run_id)
        path = self.receipts / f"{run_id}.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        return receipt_from_dict(value)

    def latest(self) -> Receipt:
        candidates = list(self.receipts.glob("*.json")) if self.receipts.exists() else []
        if not candidates:
            raise FileNotFoundError("no rehearsal receipts found")
        latest_path = max(candidates, key=lambda path: (path.stat().st_mtime_ns, path.name))
        return self.load(latest_path.stem)

    def mark_active(self, run_id: str, profile: Path) -> None:
        validate_run_id(run_id)
        content = json.dumps(
            {"profile": str(profile.absolute()), "run_id": run_id},
            sort_keys=True,
            separators=(",", ":"),
        )
        _atomic_write(self.active / f"{run_id}.json", content + "\n")

    def clear_active(self, run_id: str) -> None:
        validate_run_id(run_id)
        (self.active / f"{run_id}.json").unlink(missing_ok=True)

    def abandoned_profiles(self) -> dict[str, Path]:
        if not self.active.exists():
            return {}
        profiles: dict[str, Path] = {}
        for marker in sorted(self.active.glob("*.json")):
            validate_run_id(marker.stem)
            value = cast(Mapping[str, object], json.loads(marker.read_text(encoding="utf-8")))
            profiles[marker.stem] = Path(str(value["profile"]))
        return profiles
