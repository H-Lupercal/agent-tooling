"""Truthful, append-only records of how development tools contributed."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Literal, Mapping, cast

Actor = Literal["toolbelt", "conductor", "codex", "verification"]


@dataclass(frozen=True)
class ActivityRecord:
    timestamp: str
    actor: Actor
    operation: str
    inputs: Mapping[str, object]
    outputs: Mapping[str, object]
    affected_paths: tuple[str, ...]
    evidence_command: str


def append_record(path: Path, record: ActivityRecord) -> None:
    """Append one canonical JSON object without rewriting earlier evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(record), sort_keys=True, separators=(",", ":"))
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(payload + "\n")


def load_records(path: Path) -> list[ActivityRecord]:
    """Load records from a JSON Lines ledger."""
    records: list[ActivityRecord] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        value = cast(dict[str, object], json.loads(line))
        actor = value["actor"]
        if actor not in {"toolbelt", "conductor", "codex", "verification"}:
            raise ValueError(f"unknown activity actor: {actor}")
        records.append(
            ActivityRecord(
                timestamp=str(value["timestamp"]),
                actor=cast(Actor, actor),
                operation=str(value["operation"]),
                inputs=cast(dict[str, object], value["inputs"]),
                outputs=cast(dict[str, object], value["outputs"]),
                affected_paths=tuple(cast(list[str], value["affected_paths"])),
                evidence_command=str(value["evidence_command"]),
            )
        )
    return records


def render_markdown(records: list[ActivityRecord]) -> str:
    """Render a concise human-readable activity table."""
    rows = [
        "# Tool activity",
        "",
        "No code authorship attributed to Toolbelt or Conductor.",
        "",
        "| Actor | Operation | Evidence |",
        "|---|---|---|",
    ]
    rows.extend(
        f"| {record.actor} | {record.operation} | `{record.evidence_command}` |"
        for record in records
    )
    return "\n".join(rows) + "\n"

