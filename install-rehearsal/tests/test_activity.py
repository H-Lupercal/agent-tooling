from pathlib import Path

import pytest

from install_rehearsal.activity import (
    ActivityRecord,
    append_record,
    load_records,
    render_markdown,
)


def test_append_record_writes_canonical_jsonl(tmp_path: Path) -> None:
    target = tmp_path / "activity.jsonl"
    record = ActivityRecord(
        timestamp="2026-07-12T00:00:00Z",
        actor="toolbelt",
        operation="scan",
        inputs={"path": "."},
        outputs={"files_scanned": 1},
        affected_paths=(),
        evidence_command="toolbelt scan --path . --json",
    )

    append_record(target, record)

    content = target.read_text(encoding="utf-8")
    assert content.endswith("\n")
    assert '"actor":"toolbelt"' in content


def test_render_markdown_groups_records_by_actor() -> None:
    record = ActivityRecord(
        timestamp="2026-07-12T00:00:00Z",
        actor="conductor",
        operation="status",
        inputs={"last": True},
        outputs={"mode": "admission"},
        affected_paths=(),
        evidence_command="conductor status --last --pretty",
    )

    rendered = render_markdown([record])

    assert "| conductor | status |" in rendered
    assert "No code authorship attributed" in rendered


def test_load_records_round_trips_appended_record(tmp_path: Path) -> None:
    target = tmp_path / "activity.jsonl"
    record = ActivityRecord(
        timestamp="2026-07-12T00:00:00Z",
        actor="verification",
        operation="test",
        inputs={},
        outputs={"passed": 1},
        affected_paths=("tests/test_activity.py",),
        evidence_command="pytest tests/test_activity.py",
    )
    append_record(target, record)

    assert load_records(target) == [record]


def test_load_records_rejects_unknown_actor(tmp_path: Path) -> None:
    target = tmp_path / "activity.jsonl"
    target.write_text(
        '{"actor":"invented","affected_paths":[],"evidence_command":"none",'
        '"inputs":{},"operation":"fake","outputs":{},"timestamp":"now"}\n',
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown activity actor"):
        load_records(target)


def test_committed_ledger_loads_despite_trailing_blank_lines() -> None:
    ledger = Path(__file__).parents[1] / "docs" / "tool-activity.jsonl"

    assert load_records(ledger)


def test_committed_markdown_matches_machine_readable_ledger() -> None:
    docs = Path(__file__).parents[1] / "docs"

    assert (docs / "tool-activity.md").read_text(encoding="utf-8") == render_markdown(
        load_records(docs / "tool-activity.jsonl")
    )
