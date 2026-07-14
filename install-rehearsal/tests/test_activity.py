from pathlib import Path

from install_rehearsal.activity import ActivityRecord, append_record, render_markdown


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
