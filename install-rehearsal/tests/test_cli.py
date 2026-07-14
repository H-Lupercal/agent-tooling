from dataclasses import replace
import json
from pathlib import Path
import sys

from install_rehearsal.cli import main
from install_rehearsal.models import FileDelta, FileState, Receipt
from install_rehearsal.store import ReceiptStore


def test_run_creates_receipt_and_json_report(tmp_path: Path, capsys) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile_installer.py"

    code = main(
        [
            "--store",
            str(tmp_path / "store"),
            "run",
            "--json",
            "--",
            sys.executable,
            str(fixture),
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == 0
    assert payload["trust_label"] == "REHEARSAL_NOT_SANDBOXED"
    assert any(
        item["path"].endswith("example/config.toml")
        for item in payload["filesystem_delta"]
    )
    assert ReceiptStore(tmp_path / "store").latest().run_id == payload["run_id"]


def test_run_preserves_caller_working_directory(tmp_path: Path, capsys, monkeypatch) -> None:
    fixture = Path(__file__).parent / "fixtures" / "profile_installer.py"
    relative_fixture = tmp_path / "fixture.py"
    relative_fixture.write_text(fixture.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    code = main(
        [
            "--store",
            str(tmp_path / "store"),
            "run",
            "--json",
            "--",
            sys.executable,
            relative_fixture.name,
        ]
    )

    assert code == 0
    assert json.loads(capsys.readouterr().out)["run"]["exit_code"] == 0


def test_show_latest_renders_trust_boundary(tmp_path: Path, capsys) -> None:
    store = ReceiptStore(tmp_path)
    store.write(Receipt.example(run_id="run-1"))

    assert main(["--store", str(tmp_path), "show", "latest"]) == 0
    output = capsys.readouterr().out
    assert output.startswith("REHEARSAL_NOT_SANDBOXED\n")
    assert "Run: run-1" in output


def test_compare_detects_semantic_delta(tmp_path: Path, capsys) -> None:
    store = ReceiptStore(tmp_path)
    first_receipt = Receipt.example(run_id="run-1")
    created = FileState(
        kind="file",
        size=1,
        sha256="0" * 64,
        mode=None,
        symlink_target=None,
    )
    second_receipt = replace(
        first_receipt,
        run_id="run-2",
        filesystem_delta=(FileDelta("new.txt", "created", None, created),),
    )
    store.write(first_receipt)
    store.write(second_receipt)

    assert main(["--store", str(tmp_path), "compare", "run-1", "run-2"]) == 1
    assert "created in second" in capsys.readouterr().out


def test_compare_ignores_identity_and_timestamp(tmp_path: Path, capsys) -> None:
    store = ReceiptStore(tmp_path)
    first = Receipt.example(run_id="run-1")
    second = replace(first, run_id="run-2", started_at="2026-07-13T00:00:00Z")
    store.write(first)
    store.write(second)

    assert main(["--store", str(tmp_path), "compare", "run-1", "run-2"]) == 0
    assert "No semantic differences" in capsys.readouterr().out
